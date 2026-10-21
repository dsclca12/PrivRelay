import 'dart:async';

import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:privrelay/core/database.dart';
import 'package:privrelay/core/platform.dart';
import 'package:privrelay/data/models/message.dart';
import 'package:privrelay/data/repository.dart';

class FakeSpool extends SmsPlatform {
  Completer<void>? gate;
  final raw = <Map<String, dynamic>>[
    const SmsMessage(
      id: 'spool-id',
      sender: 'synthetic',
      body: 'test only',
      receivedAt: 100,
    ).toJson(),
  ];
  int confirmations = 0;
  @override
  Future<bool> lock() async => true;
  @override
  Future<void> unlock() async {}
  @override
  Future<List<Map<String, dynamic>>> peek() async {
    await gate?.future;
    return List.of(raw);
  }

  @override
  Future<void> ack(List<String> ids) async {
    confirmations++;
    raw.removeWhere((r) => ids.contains(r['message_id']));
  }

  @override
  Future<void> notify(String id) async {}
}

class FailingDatabase extends AppDatabase {
  FailingDatabase() : super(NativeDatabase.memory());
  @override
  Future<void> ingest(List<SmsMessage> batch) async {
    throw StateError('injected transaction failure');
  }
}

void main() {
  test('concurrent sync callers await the same committed work', () async {
    final db = AppDatabase(NativeDatabase.memory());
    final p = FakeSpool()..gate = Completer<void>();
    final r = RelayRepository(db, platform: p);
    final first = r.sync();
    final second = r.sync();
    expect(identical(first, second), isTrue);
    p.gate!.complete();
    await second;
    expect(await db.pendingCount(), 1);
    expect(p.confirmations, 1);
    await r.close();
  });
  test(
    'native spool remains unacknowledged if local transaction fails',
    () async {
      final db = FailingDatabase();
      final p = FakeSpool();
      final r = RelayRepository(db, platform: p);
      await r.sync();
      expect(p.confirmations, 0);
      expect(p.raw.length, 1);
      expect(r.error, isNotEmpty);
      await r.close();
    },
  );
  test('native ACK follows committed business data and replay creates no duplicate', () async {
    final db = AppDatabase(NativeDatabase.memory());
    final p = FakeSpool();
    final r = RelayRepository(db, platform: p);
    final replay = Map<String, dynamic>.from(p.raw.single);
    await r.sync();
    expect(p.confirmations, 1);
    expect(await db.find('spool-id'), isNotNull);
    p.raw.add(replay);
    await r.sync();
    expect(await db.pendingCount(), 1);
    expect(p.raw, isEmpty);
    await r.close();
  });
}
