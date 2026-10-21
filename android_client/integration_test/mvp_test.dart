import 'dart:io';

import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:path_provider/path_provider.dart';
import 'package:privrelay/app/app.dart';
import 'package:privrelay/core/database.dart';
import 'package:privrelay/data/repository.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'Android MVP: pair, native spool, encryption, retry, quarantine, restore, feedback, revoke',
    (tester) async {
      const code = String.fromEnvironment('PAIRING_CODE');
      expect(
        code,
        isNotEmpty,
        reason: 'Start the test server and supply its one-time code',
      );
      final r = await RelayRepository.open(listen: false);
      await r.setBackground(
        false,
      ); // Test runner owns the root Dart entrypoint.
      await r.finishOnboarding();
      await r.pair('http://127.0.0.1:8787', code, allowHttp: true);
      await r.saveRules({
        'mode': 'block',
        'threshold': 0.95,
        'whitelist': <String>[],
        'blacklist': ['PR-MVP'],
      });
      final stamp = DateTime.now().millisecondsSinceEpoch;
      const channel = MethodChannel('dev.privrelay/sms');
      final fixture = {
        'sender': 'PR-MVP',
        'body': '【测试商店】周末全场优惠，欢迎选购，退订回T。',
        'received_at': stamp,
        'subscription_id': 101,
        'slot': 0,
      };
      final id = await channel.invokeMethod<String>('testInject', fixture);
      expect(await channel.invokeMethod<String>('testInject', fixture), id);
      final id2 = await channel.invokeMethod<String>('testInject', {
        ...fixture,
        'body': '【测试银行】验证码123456，请勿告知他人。',
        'received_at': stamp + 1,
        'slot': 1,
        'subscription_id': 102,
      });
      // Simulate unreachable transport without touching the phone's network settings.
      final server = r.server;
      r.server = 'http://127.0.0.1:18789';
      await r.sync();
      expect(r.pending, greaterThanOrEqualTo(2));
      expect(
        (await r.platform.peek()),
        isEmpty,
        reason: 'Native ACK follows durable local import, even offline',
      );
      expect((await r.db.find(id!))!.syncState, 'failed');
      r.server = server;
      await r.db
          .update(r.db.messages)
          .write(const MessagesCompanion(retryAt: Value(0)));
      await r.sync();
      expect(r.pending, 0);
      final marketing = await r.db.find(id);
      final otp = await r.db.find(id2!);
      expect(marketing!.action, 'quarantine');
      expect(marketing.modelVersion, isNotEmpty);
      expect(otp!.action, 'allow');
      expect(otp.slot, 1);
      await tester.pumpWidget(
        ProviderScope(
          overrides: [repositoryProvider.overrideWithValue(r)],
          child: const RelayApp(),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('收件箱'), findsOneWidget);
      await tester.tap(find.text('拦截箱'));
      await tester.pumpAndSettle();
      expect(find.text('PR-MVP'), findsOneWidget);
      await tester.tap(find.text('PR-MVP'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('恢复到收件箱'));
      await tester.tap(find.text('恢复到收件箱'));
      await tester.pumpAndSettle();
      expect((await r.db.find(id))!.action, 'allow');
      await tester.ensureVisible(find.text('纠正分类'));
      await tester.tap(find.text('纠正分类'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('服务通知').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('确认'));
      await tester.pumpAndSettle();
      await r.sync();
      expect(
        (await r.db.find(id))!.category,
        'marketing',
        reason: 'Feedback must retain original model prediction',
      );
      final path = (await getApplicationSupportDirectory()).path;
      final bytes = await File('$path/privrelay.db')
          .openRead(0, 16)
          .fold<List<int>>([], (a, b) => a..addAll(b));
      expect(
        String.fromCharCodes(bytes),
        isNot(startsWith('SQLite format 3')),
        reason: 'SQLCipher encrypts the database header',
      );
      expect(
        (await r.db.page(search: '测试银行')).where((m) => m.id == id2).length,
        1,
      );
      await r.revoke(r.deviceId);
      await r.sync();
      expect(r.rePair, isTrue);
      expect(
        await r.db.find(id),
        isNotNull,
        reason: 'Revocation preserves local data',
      );
      await r.unpair();
      await r.setBackground(true);
      await tester.pumpWidget(const SizedBox());
      await r.close();
    },
  );
}
