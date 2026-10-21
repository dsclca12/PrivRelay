import 'package:drift/native.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:privrelay/app/app.dart';
import 'package:privrelay/core/database.dart';
import 'package:privrelay/data/models/message.dart';
import 'package:privrelay/data/repository.dart';

class LocalRepository extends RelayRepository {
  LocalRepository(super.db) {
    onboarded = true;
    permissions = {'sms': false};
  }
  @override
  Future<void> sync() async {}
  @override
  void connectSocket() {}
}

void main() {
  testWidgets(
    'inbox search, quarantine restore and correction preserve prediction',
    (tester) async {
      final db = AppDatabase(NativeDatabase.memory());
      final r = LocalRepository(db);
      await db.ingest([
        const SmsMessage(
          id: 'test-normal',
          sender: '正常发件人',
          body: '合成测试消息',
          receivedAt: 100,
        ),
      ]);
      await db.saveRemote(
        const SmsMessage(
          id: 'test-marketing',
          sender: '营销发件人',
          body: '合成优惠活动',
          receivedAt: 200,
          category: 'marketing',
          action: 'quarantine',
          confidence: 0.99,
        ),
      );
      await tester.pumpWidget(
        ProviderScope(
          overrides: [repositoryProvider.overrideWithValue(r)],
          child: const RelayApp(),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('正常发件人'), findsOneWidget);
      await tester.enterText(find.byType(TextField), '不存在');
      await tester.pumpAndSettle();
      expect(find.text('没有匹配的短信'), findsOneWidget);
      await tester.tap(find.text('拦截箱'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), '');
      await tester.pumpAndSettle();
      await tester.tap(find.text('营销发件人'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('恢复到收件箱'));
      await tester.tap(find.text('恢复到收件箱'));
      await tester.pumpAndSettle();
      expect((await db.find('test-marketing'))!.action, 'allow');
      await tester.ensureVisible(find.text('纠正分类'));
      await tester.tap(find.text('纠正分类'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('服务通知').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('确认'));
      await tester.pumpAndSettle();
      expect((await db.select(db.operations).get()).length, 2);
      expect((await db.find('test-marketing'))!.category, 'marketing');
      await tester.pumpWidget(const SizedBox());
      await db.close();
    },
  );
  testWidgets('welcome supports declined permissions and large text', (
    tester,
  ) async {
    final db = AppDatabase(NativeDatabase.memory());
    final r = LocalRepository(db)..onboarded = false;
    await tester.pumpWidget(
      ProviderScope(
        overrides: [repositoryProvider.overrideWithValue(r)],
        child: const RelayApp(),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('允许接收新短信'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('先在本地使用'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('先在本地使用'));
    await tester.pumpAndSettle();
    expect(find.text('等待你的第一条短信'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    await db.close();
  });
}
