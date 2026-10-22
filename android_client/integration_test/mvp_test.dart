import 'dart:convert';
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
import 'package:privrelay/data/models/message.dart';
import 'package:privrelay/data/repository.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'Android E2EE: native spool, encrypted retry, synthetic quarantine UI, correction, revoke',
    (tester) async {
      const code = String.fromEnvironment('PAIRING_CODE');
      const passphrase = String.fromEnvironment('VAULT_PASSPHRASE');
      expect(
        code,
        isNotEmpty,
        reason: 'Start the test server and supply its one-time code',
      );
      expect(
        passphrase.length,
        greaterThanOrEqualTo(12),
        reason: 'Supply the shared synthetic test vault passphrase using VAULT_PASSPHRASE',
      );
      final r = await RelayRepository.open(listen: false);
      await r.setBackground(
        false,
      ); // Test runner owns the root Dart entrypoint.
      await r.finishOnboarding();
      await r.setVaultPassphrase(passphrase);
      await r.pair('http://127.0.0.1:8787', code, allowHttp: true);
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
      await r.db.setPref('server', 'http://127.0.0.1:18789');
      await r.sync();
      expect(r.pending, greaterThanOrEqualTo(2));
      expect(
        (await r.platform.peek()),
        isEmpty,
        reason: 'Native ACK follows durable local import, even offline',
      );
      expect((await r.db.find(id!))!.syncState, 'failed');
      await r.db.setPref('server', server);
      await r.db
          .update(r.db.messages)
          .write(const MessagesCompanion(retryAt: Value(0)));
      await r.sync();
      expect(r.pending, 0);
      final original = (await r.db.find(id))!;
      final otp = (await r.db.find(id2!))!;
      // The E2EE server cannot classify SMS bodies: new messages stay unclassified.
      expect(original.action, 'allow');
      expect(original.category, 'uncertain');
      expect(original.modelVersion, isEmpty);
      expect(otp.action, 'allow');
      expect(otp.category, 'uncertain');
      expect(otp.modelVersion, isEmpty);
      expect(otp.slot, 1);
      expect(original.syncState, 'acked');
      expect(otp.syncState, 'acked');
      final envelopePage = await r.http.get(
        '$server/api/v2/encrypted-messages',
        options: r.auth,
        queryParameters: {'cursor': 0, 'limit': 200},
      );
      final envelopes = (envelopePage.data as Map)['messages'] as List;
      for (final expected in [original, otp]) {
        final envelope = envelopes.singleWhere(
          (item) => item['message_id'] == expected.id,
        ) as Map;
        expect(envelope.containsKey('body'), isFalse);
        expect(envelope.containsKey('sender'), isFalse);
        final plaintext = await r.platform.decryptVault(
          envelope['ciphertext'] as String,
          passphrase,
          r.vaultSalt!,
        );
        final decoded = SmsMessage.fromJson(
          Map<String, dynamic>.from(jsonDecode(plaintext) as Map),
        );
        expect(decoded.body, expected.body);
        expect(decoded.id, expected.id);
      }
      // Explicit local fixture exercises reversible quarantine UI. This is not
      // evidence of model classification or server-side filtering under E2EE.
      final synthetic = SmsMessage.fromJson(
        original.toJson()
          ..['category'] = 'marketing'
          ..['action'] = 'quarantine'
          ..['model_version'] = 'synthetic-fixture'
          ..['classification_source'] = 'synthetic-fixture'
          ..['reason'] = '合成隔离测试夹具，非模型预测',
      );
      await (r.db.update(r.db.messages)..where((t) => t.id.equals(id))).write(
        MessagesCompanion(
          payload: Value(jsonEncode(synthetic.toJson())),
          category: const Value('marketing'),
          action: const Value('quarantine'),
          state: const Value('pending'),
          retryAt: const Value(0),
        ),
      );
      await r.sync();
      expect((await r.db.find(id))!.action, 'quarantine');
      expect((await r.db.find(id))!.modelVersion, 'synthetic-fixture');
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
      await r.sync();
      await tester.pump(const Duration(seconds: 5));
      await tester.ensureVisible(find.text('纠正分类'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('纠正分类'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('服务通知').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('确认'));
      await tester.pumpAndSettle();
      await r.sync();
      if (r.operationCount > 0) await r.sync();
      expect(
        (await r.db.find(id))!.category,
        'marketing',
        reason: 'Feedback must retain the original synthetic prediction',
      );
      expect((await r.db.find(id))!.correctedCategory, 'service');
      expect((await r.db.find(id))!.modelVersion, 'synthetic-fixture');
      expect(await r.db.select(r.db.operations).get(), isEmpty);
      expect((await r.db.find(id))!.syncState, 'acked');
      expect((await r.db.find(id2))!.syncState, 'acked');
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
      expect(
        await r.db.find(id2),
        isNotNull,
        reason: 'Both collected messages survive revocation',
      );
      await r.unpair();
      await r.setBackground(true);
      await tester.pumpWidget(const SizedBox());
      await r.close();
    },
  );
}
