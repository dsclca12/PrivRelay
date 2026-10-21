import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:privrelay/data/models/message.dart';

void main() {
  test('Android accepts the shared Go sync ACK contract', () {
    final json = Map<String, dynamic>.from(
      jsonDecode(File('../contracts/message.json').readAsStringSync()) as Map,
    );
    final message = SmsMessage.fromJson(json);
    expect(message.id, 'test-message-0001');
    expect(message.body, '合成短信：周末优惠活动');
    expect(message.receivedAt, 1000);
    expect(message.subscriptionId, 1);
    expect(message.slot, 0);
    expect(message.category, 'uncertain');
    expect(message.action, 'allow');
    expect(message.needsReview, isTrue);
    expect(message.modelVersion, isEmpty);
    expect(message.confidence, 0);
    expect(message.risk, 0);
    // Backend adds revision and device metadata; Android must tolerate them.
    expect(message.toJson()['message_id'], json['message_id']);
  });
}
