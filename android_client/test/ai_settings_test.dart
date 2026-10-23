import 'package:drift/native.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:privrelay/app/app.dart';
import 'package:privrelay/core/database.dart';
import 'package:privrelay/data/repository.dart';
import 'package:privrelay/features/ai_settings.dart';

class ConfigRepository extends RelayRepository {
  ConfigRepository(super.db);
  Map<String, dynamic>? saved;
  @override
  Future<Map<String, dynamic>> aiSettings() async => {
    'mode': 'disabled',
    'base_url': '',
    'model': '',
    'has_api_key': false,
    'allow_http': false,
    'auto_quarantine': false,
    'threshold': 0.95,
  };
  @override
  Future<Map<String, dynamic>> saveAI(Map<String, dynamic> value) async {
    saved = Map.of(value);
    return {...value, 'api_key': '', 'has_api_key': true};
  }
}

void main() {
  testWidgets(
    'AI defaults are empty and activation needs destination confirmation',
    (tester) async {
      final db = AppDatabase(NativeDatabase.memory());
      final r = ConfigRepository(db);
      await tester.pumpWidget(
        ProviderScope(
          overrides: [repositoryProvider.overrideWithValue(r)],
          child: const MaterialApp(
            locale: Locale('zh', 'CN'),
            supportedLocales: [Locale('zh', 'CN'), Locale('en')],
            localizationsDelegates: GlobalMaterialLocalizations.delegates,
            home: Scaffold(body: AISettingsPage()),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final fields = find.byType(TextField);
      for (var i = 0; i < 3; i++) {
        expect(
          tester.widget<TextField>(fields.at(i)).controller!.text,
          isEmpty,
        );
      }
      expect(tester.widget<TextField>(fields.at(2)).obscureText, isTrue);
      expect(r.saved, isNull);
      await tester.enterText(fields.at(0), 'https://model.example/v1');
      await tester.enterText(fields.at(1), 'test-model');
      await tester.enterText(fields.at(2), 'synthetic-secret');
      await tester.tap(find.byType(DropdownButtonFormField<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('直接使用 LLM 分类').last);
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('保存 AI 配置'),
        300,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(find.text('保存 AI 配置'));
      await tester.pumpAndSettle();
      expect(find.text('确认 AI 处理目的地'), findsOneWidget);
      expect(r.saved, isNull);
      await tester.tap(find.text('取消'));
      await tester.pumpAndSettle();
      expect(r.saved, isNull);
      await tester.tap(find.text('保存 AI 配置'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('确认'));
      await tester.pumpAndSettle();
      expect(r.saved!['base_url'], 'https://model.example/v1');
      expect(r.saved!['api_key'], 'synthetic-secret');
      expect(r.saved!['auto_quarantine'], isFalse);
      await tester.pumpWidget(const SizedBox());
      await r.close();
    },
  );
}
