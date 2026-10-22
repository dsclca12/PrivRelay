import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:dio/dio.dart';
import 'package:drift/drift.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:uuid/uuid.dart';
import 'package:web_socket_channel/io.dart';

import '../core/database.dart';
import '../core/platform.dart';
import 'models/message.dart';

int retryDelay(int attempt, double jitter) =>
    (min(1800, 5 * pow(2, min(attempt, 9))) * (0.8 + jitter * 0.4)).round();
String validateServer(String input, {bool allowHttp = false}) {
  final uri = Uri.tryParse(input.trim());
  if (uri == null ||
      !uri.hasAuthority ||
      uri.host.isEmpty ||
      uri.userInfo.isNotEmpty ||
      uri.hasQuery ||
      uri.hasFragment ||
      (uri.path != '' && uri.path != '/') ||
      (uri.scheme != 'https' && !(allowHttp && uri.scheme == 'http'))) {
    throw const FormatException('请输入 HTTPS 服务器地址（不含路径、账号或参数）');
  }
  return uri.replace(path: '').toString().replaceFirst(RegExp(r'/$'), '');
}

bool shouldNotify(String mode, String category, String action) =>
    action == 'allow' &&
    mode != 'off' &&
    (mode != 'important' ||
        [
          'otp',
          'transaction',
          'personal',
          'suspicious',
          'uncertain',
        ].contains(category));

class RelayRepository extends ChangeNotifier {
  final AppDatabase db;
  final SmsPlatform platform;
  final Dio http;
  final FlutterSecureStorage secure;
  RelayRepository(
    this.db, {
    this.platform = const SmsPlatform(),
    Dio? http,
    this.secure = const FlutterSecureStorage(),
  }) : http =
           http ??
           Dio(
             BaseOptions(
               connectTimeout: const Duration(seconds: 8),
               receiveTimeout: const Duration(seconds: 15),
               sendTimeout: const Duration(seconds: 15),
               followRedirects: false,
             ),
           );
  String server = '', deviceId = '', state = '本地模式', error = '';
  String? vaultPassphrase, vaultSalt;
  String? token;
  bool hidePreviews = false, screenProtection = true;
  bool appLockEnabled = false, appUnlocked = false, authenticating = false;
  String notificationMode = 'all';
  int retentionDays = 0;
  bool onboarded = false,
      busy = false,
      rePair = false,
      backgroundEnabled = true,
      _closed = false;
  int pending = 0, operationCount = 0;
  Map<String, dynamic> permissions = {};
  StreamSubscription? _network;
  IOWebSocketChannel? _socket;
  Timer? _retry, _wsRetry;
  Future<void>? _syncing;
  int _socketAttempt = 0;
  bool _listenEnabled = true;
  bool _remoteMore = false;

  static Future<RelayRepository> open({bool listen = true}) async {
    const p = SmsPlatform();
    // Prevent headless / foreground DB initialization and queue claims racing.
    while (!await p.lock()) {
      await Future<void>.delayed(const Duration(milliseconds: 100));
    }
    late AppDatabase db;
    try {
      db = await AppDatabase.open();
      await db.customSelect('SELECT 1').get();
    } finally {
      await p.unlock();
    }
    final r = RelayRepository(db);
    r._listenEnabled = listen;
    await r.load();
    if (listen) {
      await p.initialize();
      r._network = Connectivity().onConnectivityChanged.listen((_) {
        r.sync();
      });
      p.channel.setMethodCallHandler((call) async {
        if (call.method == 'changed') await r.sync();
      });
      r.connectSocket();
    }
    return r;
  }

  Future<void> load() async {
    server =
        await db.pref('server') ?? const String.fromEnvironment('SERVER_URL');
    token = await secure.read(key: 'token');
    vaultPassphrase = await secure.read(key: 'vault_passphrase');
    vaultSalt = await secure.read(key: 'vault_salt');
    deviceId = (await platform.identity())['device_id'] as String;
    onboarded = await db.pref('onboarded') == 'true';
    rePair = await db.pref('re_pair') == 'true';
    backgroundEnabled = await db.pref('background') != 'false';
    appLockEnabled = await db.pref('app_lock') == 'true';
    hidePreviews = await db.pref('hide_previews') == 'true';
    screenProtection = await db.pref('screen_protection') != 'false';
    notificationMode = await db.pref('notification_mode') ?? 'all';
    retentionDays = int.tryParse(await db.pref('retention_days') ?? '') ?? 0;
    permissions = await platform.status();
    state = rePair
        ? '需要重新配对'
        : token == null
        ? '本地模式'
        : '等待同步';
    pending = await db.pendingCount();
    operationCount = (await db.select(db.operations).get()).length;
  }

  void lockApp() {
    if (appLockEnabled && !authenticating) {
      appUnlocked = false;
      changed();
    }
  }

  Future<bool> unlockApp() async {
    if (authenticating) return false;
    authenticating = true;
    changed();
    try {
      final success = await platform.authenticate();
      if (success) appUnlocked = true;
      return success;
    } finally {
      authenticating = false;
      changed();
    }
  }

  Future<void> setAppLock(bool enabled) async {
    if (!await unlockApp()) throw StateError('未完成身份验证，请先为设备设置锁屏密码后重试');
    if (enabled) await setPrivacy(protection: true);
    await db.setPref('app_lock', '$enabled');
    appLockEnabled = enabled;
    changed();
  }

  void changed() {
    if (!_closed) notifyListeners();
  }

  Future<void> finishOnboarding() async {
    await db.setPref('onboarded', 'true');
    onboarded = true;
    changed();
  }

  Future<void> setVaultPassphrase(String value) async {
    final normalized = value.trim();
    if (normalized.length < 12 ||
        normalized.runes.any((r) => r < 33 || r > 126)) {
      throw const FormatException('端到端加密口令至少 12 个字符，且只能包含可见 ASCII 字符');
    }
    // Stage the candidate until pairing verifies it against existing ciphertext.
    // A typo must not replace the key used by an established connection.
    vaultPassphrase = normalized;
    changed();
  }

  Future<void> requestSms() async {
    await platform.requestSms();
    permissions = await platform.status();
    changed();
  }

  Future<void> requestNotifications() async {
    await platform.requestNotifications();
    permissions = await platform.status();
    changed();
  }

  Future<void> pair(
    String address,
    String code, {
    bool allowHttp = false,
  }) async {
    if (busy) throw StateError('请等待当前同步完成');
    busy = true;
    changed();
    var locked = false;
    var paired = false;
    String? previousPassphrase;
    try {
      locked = await platform.lock();
      if (!locked) throw StateError('后台同步正在进行，请稍后重试');
      previousPassphrase = await secure.read(key: 'vault_passphrase');
      server = await db.pref('server') ?? server;
      final target = validateServer(
        address,
        allowHttp: kDebugMode && allowHttp,
      );
      final pairingCode = code.trim();
      if (pairingCode.isEmpty) throw const FormatException('请输入一次性配对码');
      if ((vaultPassphrase ?? '').length < 12 ||
          vaultPassphrase!.runes.any((r) => r < 33 || r > 126)) {
        throw StateError('请先设置至少 12 个可见 ASCII 字符的端到端加密口令');
      }
      if (server.isNotEmpty &&
          target != server &&
          ((await db.select(db.messages).get()).isNotEmpty ||
              (await db.select(db.operations).get()).isNotEmpty)) {
        throw StateError('切换服务器前请先处理待发送数据并清理本地记录');
      }
      final identity = await platform.identity();
      final nonce = const Uuid().v4();
      final canonical =
          '${identity['device_id']}\n${identity['public_key']}\n$nonce\n$pairingCode\ne2ee-v1';
      final res = await http.post(
        '$target/api/v1/devices/register',
        data: {
          ...identity,
          'nonce': nonce,
          'pairing_code': pairingCode,
          'signature': await platform.sign(canonical),
          'e2ee': true,
          'name': 'Android 手机',
        },
      );
      final newToken = (res.data as Map)['token'] as String;
      if (newToken.isEmpty) throw const FormatException('Empty token');
      final params = await http.get<Map<String, dynamic>>(
        '$target/api/v2/crypto/params',
        options: Options(headers: {'Authorization': 'Bearer $newToken'}),
      );
      final salt = params.data?['salt'] as String?;
      if (salt == null || salt.isEmpty) {
        throw const FormatException('服务器未提供加密参数');
      }
      final probe = await http.get<Map<String, dynamic>>(
        '$target/api/v2/encrypted-messages',
        options: Options(headers: {'Authorization': 'Bearer $newToken'}),
        queryParameters: {'cursor': '0', 'limit': 1},
      );
      final existing = probe.data?['messages'] as List;
      if (existing.isNotEmpty) {
        try {
          final envelope = existing.first as Map;
          final plain = await platform.decryptVault(
            envelope['ciphertext'] as String,
            vaultPassphrase!,
            salt,
          );
          SmsMessage.fromJson(
            Map<String, dynamic>.from(jsonDecode(plain) as Map),
          );
        } catch (_) {
          throw StateError('共享加密口令不匹配，未上传或迁移短信；请输入其他设备使用的相同口令');
        }
      }
      await secure.write(key: 'token', value: newToken);
      await secure.write(key: 'vault_passphrase', value: vaultPassphrase);
      await secure.write(key: 'vault_salt', value: salt);
      vaultSalt = salt;
      await db.transaction(() async {
        if (target != server) await db.setPref('cursor', '0');
        await db.setPref('encrypted_cursor', '0');
        await db.setPref('e2ee_migration_done', 'false');
        await (db.update(db.messages))
            .write(const MessagesCompanion(state: Value('pending')));
        await db.setPref('server', target);
        await db.setPref('re_pair', 'false');
      });
      server = target;
      token = newToken;
      rePair = false;
      error = '';
      state = '已配对';
      paired = true;
      connectSocket();
    } on DioException catch (e) {
      throw StateError('配对失败（${e.response?.statusCode ?? '连接不可用'}）');
    } finally {
      if (!paired && previousPassphrase != null) {
        vaultPassphrase = previousPassphrase;
      }
      if (locked) await platform.unlock();
      busy = false;
      changed();
    }
    await sync();
  }

  Options get auth => Options(headers: {'Authorization': 'Bearer $token'});
  Future<void> sync() {
    if (_closed) return Future.value();
    return _syncing ??= _runSync().whenComplete(() {
      _syncing = null;
    });
  }

  Future<void> _runSync() async {
    if (busy || _closed) return;
    _retry?.cancel();
    busy = true;
    changed();
    var locked = false;
    try {
      locked = await platform.lock();
      if (!locked) {
        _retry?.cancel();
        _retry = Timer(const Duration(seconds: 2), sync);
        return;
      }
      // Other engines may have paired, unpaired or changed settings since load.
      final persistedServer = await db.pref('server');
      if (persistedServer != null) {
        server = persistedServer;
        token = await secure.read(key: 'token');
        vaultPassphrase =
            await secure.read(key: 'vault_passphrase') ?? vaultPassphrase;
        vaultSalt = await secure.read(key: 'vault_salt') ?? vaultSalt;
        rePair = await db.pref('re_pair') == 'true';
      }
      backgroundEnabled = await db.pref('background') != 'false';
      notificationMode = await db.pref('notification_mode') ?? 'all';
      retentionDays = int.tryParse(await db.pref('retention_days') ?? '') ?? 0;
      await applyRetention();
      await db.recoverUploads();
      // Never ACK the native spool until the complete local transaction commits.
      while (true) {
        final raw = await platform.peek();
        if (raw.isEmpty) break;
        await db.ingest(raw.map(SmsMessage.fromJson).toList());
        await platform.ack(raw.map((e) => e['message_id'] as String).toList());
        if (token == null) {
          for (final item in raw) {
            await notifyMessage(SmsMessage.fromJson(item));
          }
        }
      }
      if (server.isEmpty || token == null || rePair) {
        state = rePair ? '需要重新配对' : '本地模式';
        return;
      }
      state = '正在同步';
      final now = DateTime.now().millisecondsSinceEpoch;
      // Bounded work per invocation; remaining work is rescheduled below.
      final batch =
          await (db.select(db.messages)
                ..where(
                  (t) =>
                      t.state.isIn(['pending', 'failed']) &
                      t.retryAt.isSmallerOrEqualValue(now),
                )
                ..orderBy([(t) => OrderingTerm.asc(t.received)])
                ..limit(50))
              .get();
      if (batch.isNotEmpty) await _uploadMessages(batch);

      await flushOperations(now);
      if (await db.pendingCount() == 0 &&
          (await db.select(db.operations).get()).isEmpty &&
          await db.pref('e2ee_migration_done') != 'true') {
        try {
          await http.post(
            '$server/api/v2/legacy-migration',
            options: auth,
            data: {'complete': true},
          );
          await db.setPref('e2ee_migration_done', 'true');
          await db.setPref('migration_notice', '');
        } on DioException catch (e) {
          if (e.response?.statusCode != 409) rethrow;
          await db.setPref(
            'migration_notice',
            '服务器仍有未迁移的旧记录，已保留；请使用保存这些记录的设备完成迁移',
          );
        }
      }
      await pull();
      await applyRetention();
      final migrationNotice = await db.pref('migration_notice') ?? '';
      state = migrationNotice.isEmpty ? '同步完成' : migrationNotice;
      error = '';
    } on DioException catch (e) {
      final status = e.response?.statusCode;
      if (status == 401 || status == 403) {
        rePair = true;
        await db.setPref('re_pair', 'true');
        state = '需要重新配对';
        _socket?.sink.close();
      } else {
        state = '等待重试';
      }
      error = status == null ? '网络暂不可用，消息已保存在本机' : '服务请求失败（$status），本地记录已保留';
      await db.setPref('last_error', error);
    } catch (_) {
      state = '等待重试';
      error = '处理暂未完成，记录已保留';
      await db.setPref('last_error', error);
    } finally {
      if (locked) await platform.unlock();
      busy = false;
      pending = await db.pendingCount();
      operationCount = (await db.select(db.operations).get()).length;
      changed();
      if (!_closed &&
          !rePair &&
          token != null &&
          (pending + operationCount > 0 || error.isNotEmpty || _remoteMore)) {
        _retry?.cancel();
        final rows =
            await (db.select(db.messages)
                  ..where((t) => t.state.isNotIn(['acked', 'rejected']))
                  ..orderBy([(t) => OrderingTerm.asc(t.retryAt)])
                  ..limit(1))
                .get();
        final ops = await db.operationHeads();
        final times = [
          if (rows.isNotEmpty) rows.first.retryAt,
          if (ops.isNotEmpty) ops.first.retryAt,
        ];
        final seconds = _remoteMore && error.isEmpty
            ? 1
            : times.isEmpty
            ? 60
            : max(
                1,
                (times.reduce(min) - DateTime.now().millisecondsSinceEpoch) ~/
                    1000,
              );
        _retry = Timer(Duration(seconds: seconds), sync);
        if (backgroundEnabled) await platform.schedule(seconds);
      }
    }
  }

  Future<void> _uploadMessages(List<Message> batch) async {
    final ids = batch.map((e) => e.id).toList();
    final acknowledged = <SmsMessage>[];
    await (db.update(db.messages)..where((t) => t.id.isIn(ids))).write(
      const MessagesCompanion(state: Value('uploading')),
    );
    try {
      final response = await http.post(
        '$server/api/v2/encrypted-messages/sync',
        data: {
          'messages': [
            for (final row in batch)
              {
                'message_id': row.id,
                'received_at': row.received,
                'base_revision': db.decode(row).serverRevision,
                'ciphertext': await _encryptMessage(db.decode(row)),
              },
          ],
        },
        options: auth,
      );
      final acked = <String>{};
      for (final item in (response.data as Map)['messages'] as List) {
        final data = Map<String, dynamic>.from(item);
        final local = await db.find(data['message_id'] as String);
        if (local == null) continue;
        final m = local;
        if (ids.contains(m.id) && acked.add(m.id)) {
          acknowledged.add(
            SmsMessage.fromJson(
              m.toJson()..['server_revision'] = data['revision'] ?? 0,
            ),
          );
        }
      }
      // Validate the complete response before committing any local ACK.
      await db.transaction(() async {
        for (final message in acknowledged) {
          await db.saveUploadAck(message);
        }
        for (final row in batch.where((e) => !acked.contains(e.id))) {
          await fail(row);
        }
        if (acked.isNotEmpty) {
          await db.setPref('last_ack', DateTime.now().toIso8601String());
        }
      });
      if (acked.isNotEmpty) {
        await http.post(
          '$server/api/v2/legacy-migration',
          options: auth,
          data: {'message_ids': acked.toList()},
        );
      }
    } catch (e) {
      final status = e is DioException ? e.response?.statusCode : null;
      final revisionConflict =
          status == 409 &&
          e is DioException &&
          e.response?.data is Map &&
          (e.response!.data as Map)['error'] == 'revision_conflict';
      if (revisionConflict) {
        await pull();
        for (final row in batch) {
          if ((await db.find(row.id))?.syncState != 'acked') await fail(row);
        }
        rethrow;
      }
      if (batch.length > 1 && [400, 409, 413, 422].contains(status)) {
        final middle = batch.length ~/ 2;
        await _uploadMessages(batch.sublist(0, middle));
        await _uploadMessages(batch.sublist(middle));
        return;
      }
      final permanent =
          status != null &&
          status >= 400 &&
          status < 500 &&
          ![401, 403, 408, 429].contains(status);
      for (final row in batch) {
        // ACKed messages stay committed if a subsequent migration request fails.
        if ((await db.find(row.id))?.syncState == 'acked') continue;
        if (permanent) {
          await (db.update(db.messages)..where((t) => t.id.equals(row.id)))
              .write(const MessagesCompanion(state: Value('rejected')));
          await db.setPref(
            'last_rejection',
            '上传被服务器拒绝（$status），消息仍在本机，请检查服务接口及消息长度',
          );
        } else {
          await fail(row);
        }
        await notifyMessage(db.decode(row));
      }
      if (!permanent) rethrow;
    }
    // Notification errors must never reset committed uploads or notify quarantine.
    for (final message in acknowledged) {
      await notifyMessage(message);
    }
  }

  Future<void> fail(Message row) =>
      (db.update(db.messages)..where((t) => t.id.equals(row.id))).write(
        MessagesCompanion(
          state: const Value('failed'),
          attempts: Value(row.attempts + 1),
          retryAt: Value(
            DateTime.now().millisecondsSinceEpoch +
                retryDelay(row.attempts, Random().nextDouble()) * 1000,
          ),
        ),
      );
  Future<void> pull() async {
    var cursor = await db.pref('encrypted_cursor') ?? '0';
    for (var page = 0; page < 5; page++) {
      final r = await http.get(
        '$server/api/v2/encrypted-messages',
        options: auth,
        queryParameters: {'cursor': cursor, 'limit': 50},
      );
      final data = Map<String, dynamic>.from(r.data as Map);
      await db.transaction(() async {
        for (final item in data['messages'] as List) {
          final envelope = Map<String, dynamic>.from(item);
          final plain = await platform.decryptVault(
            envelope['ciphertext'] as String,
            vaultPassphrase!,
            vaultSalt!,
          );
          final message = SmsMessage.fromJson(
            Map<String, dynamic>.from(jsonDecode(plain) as Map)
              ..['server_revision'] = envelope['revision'] ?? 0,
          );
          if (message.id != envelope['message_id'] ||
              message.receivedAt != envelope['received_at'] ||
              message.serverRevision <= 0) {
            throw const FormatException('密文消息身份或版本不匹配');
          }
          await db.saveRemote(message);
        }
        cursor = data['cursor'].toString();
        await db.setPref('encrypted_cursor', cursor);
      });
      _remoteMore = data['has_more'] == true;
      if (!_remoteMore) break;
    }
  }

  Future<String> _encryptMessage(SmsMessage message) async {
    final passphrase = vaultPassphrase;
    final salt = vaultSalt;
    if (passphrase == null || salt == null) throw StateError('端到端加密尚未配置');
    return platform.encryptVault(
      jsonEncode(message.toJson()),
      passphrase,
      salt,
    );
  }

  Future<void> restore(String id) async {
    final m = await db.find(id);
    if (m == null) return;
    await db.transaction(() async {
      await (db.delete(db.operations)..where(
            (t) =>
                t.messageId.equals(id) & t.kind.isIn(['archive', 'unarchive']),
          ))
          .go();
      await db
          .into(db.operations)
          .insert(
            OperationsCompanion.insert(
              id: const Uuid().v4(),
              messageId: id,
              kind: 'restore',
              payload: '{}',
            ),
          );
      final data = m.toJson()
        ..['action'] = 'allow'
        ..['reason'] = '用户恢复'
        ..['archived'] = false;
      await (db.update(db.messages)..where((t) => t.id.equals(id))).write(
        MessagesCompanion(
          action: const Value('allow'),
          payload: Value(jsonEncode(data)),
        ),
      );
    });
    changed();
    unawaited(sync());
  }

  Future<void> archive(String id, bool archived) async {
    final m = await db.find(id);
    if (m == null) return;
    await db.transaction(() async {
      await (db.delete(db.operations)..where(
            (t) =>
                t.messageId.equals(id) & t.kind.isIn(['archive', 'unarchive']),
          ))
          .go();
      await db
          .into(db.operations)
          .insert(
            OperationsCompanion.insert(
              id: const Uuid().v4(),
              messageId: id,
              kind: archived ? 'archive' : 'unarchive',
              payload: '{}',
            ),
          );
      final data = m.toJson()..['archived'] = archived;
      await (db.update(db.messages)..where((t) => t.id.equals(id))).write(
        MessagesCompanion(payload: Value(jsonEncode(data))),
      );
    });
    changed();
    unawaited(sync());
  }

  Future<void> feedback(String id, String category) async {
    if (!categories.containsKey(category)) throw ArgumentError('category');
    final message = await db.find(id);
    if (message == null) return;
    final data = message.toJson()..['corrected_category'] = category;
    await db.transaction(() async {
      await db
          .into(db.operations)
          .insert(
            OperationsCompanion.insert(
              id: const Uuid().v4(),
              messageId: id,
              kind: 'feedback',
              payload: jsonEncode({'corrected_category': category}),
            ),
          );
      await (db.update(db.messages)..where((t) => t.id.equals(id))).write(
        MessagesCompanion(payload: Value(jsonEncode(data))),
      );
    });
    changed();
    unawaited(sync());
  }

  Future<void> flushOperations(int now) async {
    // A delayed restore must not be overtaken by a later archive on the same
    // message, otherwise retrying restore would undo the user's latest action.
    final ops = await db.operationHeads(dueBefore: now);
    for (final op in ops) {
      // An action can be replaced while another message's request is in flight.
      final current = await (db.select(
        db.operations,
      )..where((t) => t.id.equals(op.id))).getSingleOrNull();
      if (current == null) continue;
      final m = await db.find(op.messageId);
      if (m?.syncState != 'acked') continue;
      try {
        // Message operations are folded into the encrypted message envelope;
        // no restore/archive metadata is sent as a plaintext API request.
        final data = m!.toJson();
        if (op.kind == 'restore') {
          data['action'] = 'allow';
          data['reason'] = '用户恢复';
          data['archived'] = false;
        } else if (op.kind == 'archive' || op.kind == 'unarchive') {
          data['archived'] = op.kind == 'archive';
        } else if (op.kind == 'feedback') {
          data['corrected_category'] =
              (jsonDecode(op.payload) as Map)['corrected_category'];
        }
        final response = await http.post(
          '$server/api/v2/encrypted-messages/sync',
          options: auth,
          data: {
            'messages': [
              {
                'message_id': m.id,
                'received_at': m.receivedAt,
                'base_revision': m.serverRevision,
                'operation_id': op.id,
                'operation_kind': op.kind,
                'ciphertext': await _encryptMessage(SmsMessage.fromJson(data)),
              },
            ],
          },
        );
        final acknowledgements = (response.data as Map)['messages'] as List;
        if (!acknowledgements.any(
          (item) => item is Map && item['message_id'] == m.id,
        )) {
          throw const FormatException('操作未收到逐消息确认');
        }
        final ack = acknowledgements.firstWhere(
          (item) => item is Map && item['message_id'] == m.id,
        ) as Map;
        var committed = data;
        if (ack['operation_replayed'] == true) {
          if (ack['received_at'] != m.receivedAt ||
              ack['revision'] is! num ||
              (ack['revision'] as num) <= 0) {
            throw const FormatException('操作重放确认身份不匹配');
          }
          final plain = await platform.decryptVault(
            ack['ciphertext'] as String,
            vaultPassphrase!,
            vaultSalt!,
          );
          final remote = SmsMessage.fromJson(
            Map<String, dynamic>.from(jsonDecode(plain) as Map),
          );
          if (remote.id != m.id || remote.receivedAt != m.receivedAt) {
            throw const FormatException('操作重放确认身份不匹配');
          }
          committed = remote.toJson();
        }
        await db.transaction(() async {
          await (db.delete(
            db.operations,
          )..where((t) => t.id.equals(op.id))).go();
          committed['server_revision'] = ack['revision'] ?? m.serverRevision;
          await db.saveRemote(SmsMessage.fromJson(committed));
        });
      } catch (e) {
        if (e is DioException && e.response?.statusCode == 409) {
          await pull();
        }
        await (db.update(
          db.operations,
        )..where((t) => t.id.equals(op.id))).write(
          OperationsCompanion(
            attempts: Value(op.attempts + 1),
            retryAt: Value(
              now + retryDelay(op.attempts, Random().nextDouble()) * 1000,
            ),
          ),
        );
        rethrow;
      }
    }
  }

  void connectSocket() {
    _wsRetry?.cancel();
    final old = _socket;
    _socket = null;
    old?.sink.close();
    if (!_listenEnabled ||
        _closed ||
        token == null ||
        rePair ||
        server.isEmpty) {
      return;
    }
    final uri = Uri.parse(server).replace(
      scheme: server.startsWith('https:') ? 'wss' : 'ws',
      path: '/api/v1/ws',
    );
    final socket = IOWebSocketChannel.connect(
      uri,
      headers: {'Authorization': 'Bearer $token'},
      connectTimeout: const Duration(seconds: 8),
    );
    _socket = socket;
    socket.ready
        .then((_) {
          _socketAttempt = 0;
          if (!_closed) sync();
        })
        .catchError((Object _) {});
    socket.stream.listen(
      (_) {
        sync();
      },
      onError: (Object _) {},
      onDone: () {
        if (!_closed && identical(_socket, socket) && !rePair) {
          _wsRetry = Timer(
            Duration(
              seconds: retryDelay(_socketAttempt++, Random().nextDouble()),
            ),
            connectSocket,
          );
        }
      },
    );
  }

  Future<Map<String, dynamic>> health() async {
    final r = await http.get('$server/healthz', options: auth);
    return Map<String, dynamic>.from(r.data);
  }

  Future<Map<String, dynamic>> rules() async => Map<String, dynamic>.from(
    (await http.get('$server/api/v1/filter/rules', options: auth)).data,
  );
  Future<void> saveRules(Map<String, dynamic> value) async {
    await http.put('$server/api/v1/filter/rules', options: auth, data: value);
    changed();
  }

  Future<Map<String, dynamic>> aiSettings() async => Map<String, dynamic>.from(
    (await http.get('$server/api/v1/ai/settings', options: auth)).data,
  );
  Future<Map<String, dynamic>> saveAI(Map<String, dynamic> value) async =>
      Map<String, dynamic>.from(
        (await http.put(
          '$server/api/v1/ai/settings',
          options: auth,
          data: value,
        )).data,
      );
  Future<Map<String, dynamic>> testAI() async => Map<String, dynamic>.from(
    (await http.post('$server/api/v1/ai/test', options: auth, data: {})).data,
  );

  Future<List<dynamic>> devices() async =>
      (await http.get('$server/api/v1/devices', options: auth)).data as List;
  Future<void> revoke(String id) async {
    await http.delete('$server/api/v1/devices/$id', options: auth);
    if (id == deviceId) {
      rePair = true;
      await db.setPref('re_pair', 'true');
      state = '需要重新配对';
      _retry?.cancel();
      _wsRetry?.cancel();
      final socket = _socket;
      _socket = null;
      await socket?.sink.close();
      changed();
    }
  }

  Future<void> unpair() async {
    if (busy) throw StateError('请等待同步完成');
    busy = true;
    changed();
    var locked = false;
    try {
      locked = await platform.lock();
      if (!locked) throw StateError('后台同步正在进行，请稍后重试');
      final socket = _socket;
      _socket = null;
      await socket?.sink.close();
      _retry?.cancel();
      _wsRetry?.cancel();
      await secure.delete(key: 'token');
      token = null;
      rePair = false;
      await db.setPref('re_pair', 'false');
      state = '本地模式';
    } finally {
      if (locked) await platform.unlock();
      busy = false;
      changed();
    }
  }

  Future<void> setBackground(bool enabled) async {
    await db.setPref('background', '$enabled');
    backgroundEnabled = enabled;
    await platform.channel.invokeMethod('background', enabled);
    changed();
  }

  Future<void> notifyMessage(SmsMessage message) async {
    if (shouldNotify(notificationMode, message.category, message.action)) {
      await platform.notify(message.id);
    }
  }

  Future<void> setPrivacy({bool? previews, bool? protection}) async {
    if (protection == false && appLockEnabled) {
      throw StateError('请先关闭应用锁，再关闭防截屏保护');
    }
    if (protection != null) {
      await platform.protectScreen(protection);
      await db.setPref('screen_protection', '$protection');
      screenProtection = protection;
    }
    if (previews != null) {
      await db.setPref('hide_previews', '$previews');
      hidePreviews = previews;
    }
    changed();
  }

  Future<void> setNotificationMode(String mode) async {
    if (!['all', 'important', 'off'].contains(mode)) {
      throw ArgumentError.value(mode);
    }
    await db.setPref('notification_mode', mode);
    notificationMode = mode;
    changed();
  }

  Future<void> setRetention(int days) async {
    if (![0, 30, 90, 365].contains(days)) throw ArgumentError.value(days);
    await db.setPref('retention_days', '$days');
    retentionDays = days;
    await applyRetention();
    changed();
  }

  Future<void> applyRetention() async {
    if (retentionDays <= 0) return;
    await db.clearUploaded(
      before: DateTime.now()
          .subtract(Duration(days: retentionDays))
          .millisecondsSinceEpoch,
    );
  }

  Future<void> clearUploaded() async {
    await db.clearUploaded();
    changed();
  }

  Future<void> close() async {
    _closed = true;
    _retry?.cancel();
    _wsRetry?.cancel();
    await _network?.cancel();
    await _socket?.sink.close();
    await _syncing;
    await db.close();
    super.dispose();
  }
}
