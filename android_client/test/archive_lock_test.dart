import 'package:drift/native.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:privrelay/app/app.dart';
import 'package:privrelay/core/database.dart';
import 'package:privrelay/core/platform.dart';
import 'package:privrelay/data/models/message.dart';
import 'package:privrelay/data/repository.dart';

class AuthPlatform extends SmsPlatform {
  bool accepted = false;
  @override
  Future<bool> authenticate() async => accepted;
}

class LockedRepository extends RelayRepository {
  LockedRepository(super.db, AuthPlatform auth) : super(platform: auth) {
    onboarded = true;
  }
  @override
  Future<void> load() async {}
  @override
  Future<void> sync() async {}
  @override
  void connectSocket() {}
}

void main() {
  test('archive is hidden in inbox, visible in archive and quarantine, and queued state survives pulls', () async {
    final db = AppDatabase(NativeDatabase.memory());
    final r = LockedRepository(db, AuthPlatform());
    const message = SmsMessage(
      id: 'archive-test',
      sender: 'TEST',
      body: 'synthetic',
      receivedAt: 100,
    );
    await db.saveRemote(message);
    await r.archive(message.id, true);
    expect(await db.page(), isEmpty);
    expect((await db.page(archived: true)).single.id, message.id);
    await db.saveRemote(message);
    expect((await db.find(message.id))!.archived, isTrue);
    await r.archive(message.id, false);
    expect((await db.page()).single.id, message.id);
    expect((await db.select(db.operations).get()).length, 1);
    final data = message.toJson()
      ..['action'] = 'quarantine'
      ..['archived'] = true;
    await (db.delete(db.operations)).go();
    await db.saveRemote(SmsMessage.fromJson(data));
    expect((await db.page(quarantine: true)).single.archived, isTrue);
    await db.close();
  });
  testWidgets(
    'app lock hides messages, rejects cancellation and relocks after background',
    (tester) async {
      final db = AppDatabase(NativeDatabase.memory());
      final auth = AuthPlatform();
      final r = LockedRepository(db, auth)..appLockEnabled = true;
      await db.ingest([
        const SmsMessage(
          id: 'secret',
          sender: 'PRIVATE TEST',
          body: 'sensitive body',
          receivedAt: 100,
        ),
      ]);
      await tester.pumpWidget(
        ProviderScope(
          overrides: [repositoryProvider.overrideWithValue(r)],
          child: const RelayApp(),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('PrivRelay 已锁定'), findsOneWidget);
      expect(find.text('PRIVATE TEST'), findsNothing);
      expect(await r.unlockApp(), isFalse);
      await tester.pumpAndSettle();
      expect(find.text('PRIVATE TEST'), findsNothing);
      auth.accepted = true;
      await r.unlockApp();
      await tester.pumpAndSettle();
      expect(find.text('PRIVATE TEST'), findsOneWidget);
      for (final state in [
        AppLifecycleState.inactive,
        AppLifecycleState.hidden,
        AppLifecycleState.paused,
      ]) {
        tester.binding.handleAppLifecycleStateChanged(state);
      }
      expect(r.appUnlocked, isFalse);
      for (final state in [
        AppLifecycleState.hidden,
        AppLifecycleState.inactive,
        AppLifecycleState.resumed,
      ]) {
        tester.binding.handleAppLifecycleStateChanged(state);
      }
      await tester.pumpAndSettle();
      expect(find.text('PRIVATE TEST'), findsNothing);
      expect(find.text('PrivRelay 已锁定'), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
      await db.close();
    },
  );
}
