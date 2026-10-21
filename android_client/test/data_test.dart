import 'dart:convert';

import 'package:drift/drift.dart' hide isNull;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:privrelay/core/database.dart';
import 'package:privrelay/data/models/message.dart';
import 'package:privrelay/data/repository.dart';

void main() {
  late AppDatabase db;
  setUp(() {
    db = AppDatabase(NativeDatabase.memory());
  });
  tearDown(() async {
    await db.close();
  });
  SmsMessage msg(String id, {String body = '测试短信', int time = 100}) =>
      SmsMessage(id: id, sender: '测试发件人', body: body, receivedAt: time);
  test('contract rejects unknown category and invalid probabilities', () {
    final data = msg('m1').toJson();
    expect(SmsMessage.fromJson(data).body, '测试短信');
    expect(
      () => SmsMessage.fromJson({...data, 'category': 'unknown'}),
      throwsFormatException,
    );
    expect(
      () => SmsMessage.fromJson({...data, 'confidence': double.nan}),
      throwsFormatException,
    );
    expect(
      () => SmsMessage.fromJson({...data, 'risk': 1.1}),
      throwsFormatException,
    );
  });
  test(
    'spool replay is idempotent and a rolled back batch can retry',
    () async {
      await db.ingest([msg('m1'), msg('m1')]);
      expect((await db.page()).length, 1);
      try {
        await db.transaction(() async {
          await db.ingest([msg('m2')]);
          throw StateError('interrupted');
        });
      } catch (_) {}
      expect(await db.find('m2'), isNull);
      await db.ingest([msg('m2')]);
      expect(await db.pendingCount(), 2);
    },
  );
  test('pagination and literal search are bounded', () async {
    await db.ingest(
      List.generate(
        120,
        (i) => msg('m$i', body: i == 10 ? "100%_' quote 测试" : '消息$i', time: i),
      ),
    );
    expect((await db.page()).length, 50);
    expect((await db.page(offset: 100)).length, 20);
    expect((await db.page(search: '%_')).length, 1);
    expect((await db.page(search: "' OR 1=1 --")).length, 0);
    await db.ingest([msg('quote',body:'hello "double" quote')]);
    expect((await db.page(search:'"double"')).length,1);
    expect((await db.page(search:'uncertain')).length,0,reason:'Search excludes model and policy metadata');
  });
  test('pending restore cannot be overwritten by a stale pull', () async {
    final data = msg('m1').toJson()
      ..['category'] = 'marketing'
      ..['action'] = 'quarantine';
    await db.saveRemote(SmsMessage.fromJson(data));
    expect((await db.page(quarantine: true)).length, 1);
    await db
        .into(db.operations)
        .insert(
          OperationsCompanion.insert(
            id: 'op1',
            messageId: 'm1',
            kind: 'restore',
            payload: jsonEncode({}),
          ),
        );
    await db.saveRemote(SmsMessage.fromJson(data));
    expect((await db.find('m1'))!.action, 'allow');
  });
  test('interrupted uploading rows recover to pending', () async {
    await db.ingest([msg('m1')]);
    await db
        .update(db.messages)
        .write(const MessagesCompanion(state: Value('uploading')));
    await db.recoverUploads();
    expect((await db.find('m1'))!.syncState, 'pending');
  });
  test('retry has capped exponential backoff and jitter', () {
    expect(retryDelay(0, 0), 4);
    expect(retryDelay(1, 0.5), 10);
    expect(retryDelay(100, 1), 2160);
    expect(retryDelay(4, 0), lessThan(retryDelay(4, 1)));
  });
  test('server validation enforces trust boundary', () {
    expect(validateServer('https://example.com/'), 'https://example.com');
    for (final input in [
      'http://example.com',
      'https://u:p@example.com',
      'https://example.com/api',
      'https://example.com?q=1',
      'bad',
    ]) {
      expect(() => validateServer(input), throwsFormatException);
    }
    expect(
      validateServer('http://127.0.0.1:8787', allowHttp: true),
      'http://127.0.0.1:8787',
    );
  });
}
