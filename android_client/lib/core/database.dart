import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:path_provider/path_provider.dart';

import '../data/models/message.dart';

part 'database.g.dart';

class Messages extends Table {
  TextColumn get id => text()();
  TextColumn get payload => text()();
  IntColumn get received => integer()();
  TextColumn get category => text().withDefault(const Constant('uncertain'))();
  TextColumn get action => text().withDefault(const Constant('allow'))();
  TextColumn get state => text().withDefault(const Constant('pending'))();
  IntColumn get attempts => integer().withDefault(const Constant(0))();
  IntColumn get retryAt => integer().withDefault(const Constant(0))();
  @override
  Set<Column> get primaryKey => {id};
}

class Operations extends Table {
  TextColumn get id => text()();
  TextColumn get messageId => text()();
  TextColumn get kind => text()();
  TextColumn get payload => text()();
  IntColumn get attempts => integer().withDefault(const Constant(0))();
  IntColumn get retryAt => integer().withDefault(const Constant(0))();
  @override
  Set<Column> get primaryKey => {id};
}

class Preferences extends Table {
  TextColumn get key => text()();
  TextColumn get value => text()();
  @override
  Set<Column> get primaryKey => {key};
}

@DriftDatabase(tables: [Messages, Operations, Preferences])
class AppDatabase extends _$AppDatabase {
  AppDatabase(super.executor);
  @override
  int get schemaVersion => 1;
  static Future<AppDatabase> open() async {
    const secure = FlutterSecureStorage();
    var key = await secure.read(key: 'database_key');
    if (key == null) {
      // Native workers are serialized with the foreground consumer before opening.
      key = List.generate(
        32,
        (_) => Random.secure().nextInt(256).toRadixString(16).padLeft(2, '0'),
      ).join();
      await secure.write(key: 'database_key', value: key);
    }
    final path =
        '${(await getApplicationSupportDirectory()).path}/privrelay.db';
    final dbKey = key;
    return AppDatabase(
      NativeDatabase.createInBackground(
        File(path),
        setup: (db) {
          if (db.select('PRAGMA cipher_version').isEmpty) {
            throw StateError('SQLCipher is required');
          }
          db.execute('PRAGMA key = "x\'$dbKey\'"');
          db.execute('PRAGMA busy_timeout = 5000');
          db.execute('PRAGMA journal_mode = WAL');
          db.execute('PRAGMA foreign_keys = ON');
        },
      ),
    );
  }

  Future<String?> pref(String key) async => (await (select(
    preferences,
  )..where((t) => t.key.equals(key))).getSingleOrNull())?.value;
  Future<void> setPref(String key, String value) => into(
    preferences,
  ).insertOnConflictUpdate(PreferencesCompanion.insert(key: key, value: value));
  Future<void> ingest(List<SmsMessage> batch) => transaction(() async {
    for (final m in batch) {
      await into(messages).insert(
        MessagesCompanion.insert(
          id: m.id,
          payload: jsonEncode(m.toJson()),
          received: m.receivedAt,
        ),
        mode: InsertMode.insertOrIgnore,
      );
    }
  });
  Future<List<SmsMessage>> page({
    bool quarantine = false,
    bool archived = false,
    String search = '',
    String? category,
    int offset = 0,
  }) async {
    final q = select(messages)
      ..where(
        (t) => quarantine
            ? t.action.equals('quarantine')
            : t.action.equals('allow'),
      );
    if (!quarantine) {
      q.where(
        (t) => CustomExpression<bool>(
          "COALESCE(json_extract(payload, '\$.archived'), 0) = ${archived ? 1 : 0}",
        ),
      );
    }
    if (category != null) {
      q.where((t) => t.category.equals(category));
    }
    // JSON extraction searches literal text, never raw SQL or LIKE wildcards.
    if (search.isNotEmpty) {
      Expression<bool> containsField(
        Expression<String> payload,
        String field,
      ) => FunctionCallExpression<int>('instr', [
        FunctionCallExpression<String>('lower', [
          FunctionCallExpression<String>('json_extract', [
            payload,
            Variable('\$.$field'),
          ]),
        ]),
        Variable(search.toLowerCase()),
      ]).isBiggerThanValue(0);
      q.where(
        (t) =>
            containsField(t.payload, 'body') |
            containsField(t.payload, 'sender'),
      );
    }
    q
      ..orderBy([
        (t) => OrderingTerm.desc(t.received),
        (t) => OrderingTerm.desc(t.id),
      ])
      ..limit(50, offset: offset);
    return (await q.get()).map(decode).toList();
  }

  SmsMessage decode(Message row) => SmsMessage.fromJson({
    ...jsonDecode(row.payload) as Map<String, dynamic>,
    'sync_state': row.state,
  });
  Future<SmsMessage?> find(String id) async {
    final row = await (select(
      messages,
    )..where((t) => t.id.equals(id))).getSingleOrNull();
    return row == null ? null : decode(row);
  }

  // The server ACKs the transport ID but may reuse a canonical stored message
  // for a deduplicated SMS. Migrate local actions before applying that ACK.
  Future<SmsMessage> saveUploadAck(SmsMessage message, {String? canonicalId}) =>
      transaction(() async {
        final target = canonicalId == null || canonicalId == message.id
            ? message
            : SmsMessage.fromJson(
                message.toJson()..['message_id'] = canonicalId,
              );
        if (target.id != message.id) {
          await (update(operations)
                ..where((t) => t.messageId.equals(message.id)))
              .write(OperationsCompanion(messageId: Value(target.id)));
          await (delete(messages)..where((t) => t.id.equals(message.id))).go();
        }
        await saveRemote(target);
        return (await find(target.id))!;
      });

  Future<void> saveRemote(SmsMessage m) async {
    final ops =
        await (select(operations)
              ..where((t) => t.messageId.equals(m.id))
              ..orderBy([
                (t) => OrderingTerm.asc(const CustomExpression<int>('rowid')),
              ]))
            .get();
    final data = m.toJson();
    for (final op in ops) {
      if (op.kind == 'restore') {
        data['action'] = 'allow';
        data['reason'] = '用户恢复';
        data['archived'] = false;
      } else if (op.kind == 'archive' || op.kind == 'unarchive') {
        data['archived'] = op.kind == 'archive';
      }
    }
    await into(messages).insertOnConflictUpdate(
      MessagesCompanion.insert(
        id: m.id,
        payload: jsonEncode(data),
        received: m.receivedAt,
        category: Value(m.category),
        action: Value(data['action'] as String),
        state: const Value('acked'),
      ),
    );
  }

  // SQLite rowid preserves insertion order without a schema migration. Only
  // the oldest outstanding action for each message may be sent or scheduled.
  Future<List<Operation>> operationHeads({int? dueBefore}) async {
    final rows = await customSelect(
      'SELECT op.* FROM operations AS op '
      'WHERE (? IS NULL OR op.retry_at <= ?) AND NOT EXISTS ('
      'SELECT 1 FROM operations AS older '
      'WHERE older.message_id = op.message_id AND older.rowid < op.rowid) '
      'ORDER BY op.retry_at, op.rowid LIMIT 50',
      variables: [Variable<int>(dueBefore), Variable<int>(dueBefore)],
      readsFrom: {operations},
    ).get();
    return rows.map((row) => operations.map(row.data)).toList();
  }

  Future<int> countState(List<String> states) async {
    final count = messages.id.count();
    final query = selectOnly(messages)
      ..addColumns([count])
      ..where(messages.state.isIn(states));
    return (await query.getSingle()).read(count) ?? 0;
  }

  // Keep queued operations and recoverable quarantine records, even when old.
  Future<int> clearUploaded({int? before}) => customUpdate(
    "DELETE FROM messages WHERE state = 'acked' "
    "AND id NOT IN (SELECT message_id FROM operations) "
    "AND (? IS NULL OR (received < ? AND action = 'allow'))",
    variables: [Variable<int>(before), Variable<int>(before)],
    updates: {messages},
    updateKind: UpdateKind.delete,
  );

  Future<int> pendingCount() => countState(['pending', 'uploading', 'failed']);
  Future<void> recoverUploads() =>
      (update(messages)..where((t) => t.state.equals('uploading'))).write(
        const MessagesCompanion(state: Value('pending')),
      );
}
