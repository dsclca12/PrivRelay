import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:privrelay/core/localized_text.dart' as localized;

void main() {
  testWidgets('SMS role and composer labels are translated in English', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('en'),
        home: Builder(
          builder: (context) => ListView(
            children: [
              Text(localized.localizeText(context, '默认短信应用')),
              Text(localized.localizeText(context, '导入系统短信历史')),
              Text(localized.localizeText(context, '发送短信')),
              Text(localized.localizeText(context, '收件号码')),
              Text(localized.localizeText(context, '短信正文')),
              Text(localized.localizeText(context, '重要短信保护')),
              Text(
                localized.localizeText(
                  context,
                  'PrivateSMS-Classifier: risk_category:marketing',
                ),
              ),
            ],
          ),
        ),
      ),
    );
    expect(find.text('Default SMS app'), findsOneWidget);
    expect(find.text('Import SMS history'), findsOneWidget);
    expect(find.text('Send SMS'), findsOneWidget);
    expect(find.text('Recipient phone number'), findsOneWidget);
    expect(find.text('Message text'), findsOneWidget);
    expect(find.text('Protected as an important message'), findsOneWidget);
    expect(
      find.text('Classified as Marketing with elevated risk'),
      findsOneWidget,
    );
  });
}
