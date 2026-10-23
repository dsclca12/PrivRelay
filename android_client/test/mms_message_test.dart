import 'package:flutter_test/flutter_test.dart';
import 'package:privrelay/data/models/message.dart';

void main() {
  test(
    'MMS attachment metadata and encrypted payload round-trip in message JSON',
    () {
      const message = SmsMessage(
        id: '018f0000-0000-7000-8000-000000000001',
        sender: '+15551234567',
        body: 'photo',
        receivedAt: 1710000000000,
        contentKind: 'mms',
        attachments: [
          {
            'filename': 'photo.jpg',
            'mime_type': 'image/jpeg',
            'data_base64': 'AQID',
            'size': 3,
          },
        ],
        attachmentsTruncated: true,
      );

      final decoded = SmsMessage.fromJson(message.toJson());
      expect(decoded.contentKind, 'mms');
      expect(decoded.attachments.single['data_base64'], 'AQID');
      expect(decoded.attachmentsTruncated, isTrue);
    },
  );
}
