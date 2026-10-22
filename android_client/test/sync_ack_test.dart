import 'dart:convert';
import 'dart:io';

import 'package:drift/drift.dart' hide isNotNull, isNull;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:privrelay/core/database.dart';
import 'package:privrelay/core/platform.dart';
import 'package:privrelay/data/models/message.dart';
import 'package:privrelay/data/repository.dart';

import 'fake_vault_platform.dart';

class NotificationFailurePlatform extends SmsPlatform with FakeVault {
  final notifications = <String>[];
  @override
  Future<bool> lock() async => true;
  @override
  Future<void> unlock() async {}
  @override
  Future<List<Map<String, dynamic>>> peek() async => [];
  @override
  Future<void> schedule([int seconds = 30]) async {}
  @override
  Future<void> notify(String id) async {
    notifications.add(id);
    throw StateError('synthetic notification failure');
  }
}

void main() {
  test('notification failure preserves all committed ACKs and quarantine silence', () async {
    final db = AppDatabase(NativeDatabase.memory());
    final messages = [
      for (final id in ['allowed', 'quarantined'])
        SmsMessage(id: id, sender: 'TEST', body: 'synthetic', receivedAt: 100),
    ];
    await db.ingest(messages);
    // E2EE ACKs carry IDs, while classification remains in the local envelope.
    await (db.update(
      db.messages,
    )..where((t) => t.id.equals('quarantined'))).write(
      MessagesCompanion(
        payload: Value(
          jsonEncode({...messages[1].toJson(), 'action': 'quarantine'}),
        ),
        action: const Value('quarantine'),
      ),
    );
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final listener = server.listen((request) async {
      request.response.headers.contentType = ContentType.json;
      request.response.write(
        jsonEncode({
          'messages': [
            messages[0].toJson(),
            {...messages[1].toJson(), 'action': 'quarantine'},
          ],
        }),
      );
      await request.response.close();
    });
    final platform = NotificationFailurePlatform();
    final r = RelayRepository(db, platform: platform)
      ..server = 'http://127.0.0.1:${server.port}'
      ..vaultPassphrase = 'synthetic-passphrase'
      ..vaultSalt = 'synthetic-salt'
      ..token = 'synthetic-token';
    try {
      await r.sync();
      expect(await db.countState(['acked']), 2);
      expect(await db.pendingCount(), 0);
      expect((await db.find('quarantined'))!.action, 'quarantine');
      expect(platform.notifications, ['allowed']);
      expect(await db.pref('last_ack'), isNotNull);
    } finally {
      await r.close();
      await listener.cancel();
      await server.close(force: true);
    }
  });
}
