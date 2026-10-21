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
  String? token;
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
    deviceId = (await platform.identity())['device_id'] as String;
    onboarded = await db.pref('onboarded') == 'true';
    rePair = await db.pref('re_pair') == 'true';
    backgroundEnabled = await db.pref('background') != 'false';
    permissions = await platform.status();
    state = rePair
        ? '需要重新配对'
        : token == null
        ? '本地模式'
        : '等待同步';
    pending = await db.pendingCount();
    operationCount = (await db.select(db.operations).get()).length;
  }

  void changed() {
    if (!_closed) notifyListeners();
  }

  Future<void> finishOnboarding() async {
    await db.setPref('onboarded', 'true');
    onboarded = true;
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
    try {
      final target = validateServer(
        address,
        allowHttp: kDebugMode && allowHttp,
      );
      final pairingCode = code.trim();
      if (pairingCode.isEmpty) throw const FormatException('请输入一次性配对码');
      if (server.isNotEmpty &&
          target != server &&
          ((await db.select(db.messages).get()).isNotEmpty ||
              (await db.select(db.operations).get()).isNotEmpty)) {
        throw StateError('切换服务器前请先处理待发送数据并清理本地记录');
      }
      final identity = await platform.identity();
      final nonce = const Uuid().v4();
      final canonical =
          '${identity['device_id']}\n${identity['public_key']}\n$nonce\n$pairingCode';
      final res = await http.post(
        '$target/api/v1/devices/register',
        data: {
          ...identity,
          'nonce': nonce,
          'pairing_code': pairingCode,
          'signature': await platform.sign(canonical),
          'name': 'Android 手机',
        },
      );
      final newToken = (res.data as Map)['token'] as String;
      if (newToken.isEmpty) throw const FormatException('Empty token');
      await secure.write(key: 'token', value: newToken);
      await db.transaction(() async {
        if (target != server) await db.setPref('cursor', '0');
        await db.setPref('server', target);
        await db.setPref('re_pair', 'false');
      });
      server = target;
      token = newToken;
      rePair = false;
      error = '';
      state = '已配对';
      connectSocket();
    } on DioException catch (e) {
      throw StateError('配对失败（${e.response?.statusCode ?? '连接不可用'}）');
    } finally {
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
      await db.recoverUploads();
      // Never ACK the native spool until the complete local transaction commits.
      while (true) {
        final raw = await platform.peek();
        if (raw.isEmpty) break;
        await db.ingest(raw.map(SmsMessage.fromJson).toList());
        await platform.ack(raw.map((e) => e['message_id'] as String).toList());
        if (token == null) {
          for (final item in raw) {
            await platform.notify(item['message_id'] as String);
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
      if (batch.isNotEmpty) {
        final ids = batch.map((e) => e.id).toList();
        await (db.update(db.messages)..where((t) => t.id.isIn(ids))).write(
          const MessagesCompanion(state: Value('uploading')),
        );
        try {
          final response = await http.post(
            '$server/api/v1/messages/sync',
            options: auth,
            data: {
              'messages': batch.map((e) => db.decode(e).toJson()).toList(),
            },
          );
          final acked = <String>{};
          for (final item in (response.data as Map)['messages'] as List) {
            final m = SmsMessage.fromJson(Map<String, dynamic>.from(item));
            if (ids.contains(m.id)) {
              await db.saveRemote(m);
              acked.add(m.id);
              if (m.action == 'allow') await platform.notify(m.id);
            }
          }
          for (final row in batch.where((e) => !acked.contains(e.id))) {
            await fail(row);
          }
          if (acked.isNotEmpty) {
            await db.setPref('last_ack', DateTime.now().toIso8601String());
          }
        } catch (e) {
          final status = e is DioException ? e.response?.statusCode : null;
          final permanent =
              status != null &&
              status >= 400 &&
              status < 500 &&
              ![401, 403, 408, 429].contains(status);
          for (final row in batch) {
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
            await platform.notify(row.id);
          }
          rethrow;
        }
      }
      await flushOperations(now);
      await pull();
      state = '同步完成';
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
        final ops =
            await (db.select(db.operations)
                  ..orderBy([(t) => OrderingTerm.asc(t.retryAt)])
                  ..limit(1))
                .get();
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
    var cursor = await db.pref('cursor') ?? '0';
    for (var page = 0; page < 5; page++) {
      final r = await http.get(
        '$server/api/v1/messages',
        options: auth,
        queryParameters: {'cursor': cursor, 'limit': 50},
      );
      final data = Map<String, dynamic>.from(r.data as Map);
      await db.transaction(() async {
        for (final item in data['messages'] as List) {
          await db.saveRemote(
            SmsMessage.fromJson(Map<String, dynamic>.from(item)),
          );
        }
        cursor = data['cursor'].toString();
        await db.setPref('cursor', cursor);
      });
      _remoteMore = data['has_more'] == true;
      if (!_remoteMore) break;
    }
  }

  Future<void> restore(String id) async {
    final m = await db.find(id);
    if (m == null) return;
    await db.transaction(() async {
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
        ..['reason'] = '用户恢复';
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

  Future<void> feedback(String id, String category) async {
    if (!categories.containsKey(category)) throw ArgumentError('category');
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
    changed();
    unawaited(sync());
  }

  Future<void> flushOperations(int now) async {
    final ops =
        await (db.select(db.operations)
              ..where((t) => t.retryAt.isSmallerOrEqualValue(now))
              ..limit(50))
            .get();
    for (final op in ops) {
      final m = await db.find(op.messageId);
      if (m?.syncState != 'acked') continue;
      try {
        final r = await http.post(
          '$server/api/v1/messages/${op.messageId}/${op.kind}',
          options: auth,
          data: {
            ...jsonDecode(op.payload) as Map<String, dynamic>,
            'operation_id': op.id,
          },
        );
        await db.transaction(() async {
          await (db.delete(
            db.operations,
          )..where((t) => t.id.equals(op.id))).go();
          if (op.kind == 'restore') {
            await db.saveRemote(
              SmsMessage.fromJson(Map<String, dynamic>.from(r.data)),
            );
          }
        });
      } catch (_) {
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
    changed();
  }

  Future<void> setBackground(bool enabled) async {
    await db.setPref('background', '$enabled');
    backgroundEnabled = enabled;
    await platform.channel.invokeMethod('background', enabled);
    changed();
  }

  Future<void> clearUploaded() async {
    final ops = await db.select(db.operations).get();
    await (db.delete(db.messages)..where(
          (t) =>
              t.state.equals('acked') &
              t.id.isNotIn(ops.map((o) => o.messageId)),
        ))
        .go();
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
