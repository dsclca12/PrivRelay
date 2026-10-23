import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:privrelay/core/database.dart';
import 'package:privrelay/data/models/message.dart';

void main() {
  test('history import deduplicates against old live IDs and itself', () async {
    final db = AppDatabase(NativeDatabase.memory());
    await db.ingest([
      const SmsMessage(
        id: 'legacy-random-live-id',
        sender: '+15550100',
        body: 'synthetic history sample',
        receivedAt: 1_800_000_000_123,
        subscriptionId: 4,
      ),
    ]);

    final duplicate = const SmsMessage(
      id: 'deterministic-import-id',
      sender: '+15550100',
      body: 'synthetic history sample',
      receivedAt: 1_800_000_000_123,
      subscriptionId: 4,
    );
    final unique = const SmsMessage(
      id: 'next-import-id',
      sender: '+15550100',
      body: 'different synthetic sample',
      receivedAt: 1_800_000_000_456,
      subscriptionId: 4,
    );

    expect(await db.ingestHistory([duplicate, unique, unique]), 1);
    expect((await db.select(db.messages).get()).length, 2);
    expect(await db.find('legacy-random-live-id'), isNotNull);
    expect(await db.find('deterministic-import-id'), isNull);
    expect(await db.find('next-import-id'), isNotNull);
    await db.close();
  });
}
