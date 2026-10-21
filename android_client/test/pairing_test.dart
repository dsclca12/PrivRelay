import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:privrelay/core/pairing.dart';

void main() {
  final fixture = jsonDecode(
    File('../contracts/pairing.json').readAsStringSync(),
  ) as Map<String, dynamic>;
  final now = DateTime.fromMillisecondsSinceEpoch(1900000000000);
  PairingQr parse(Map<String, dynamic> changes, {bool allowHttp = false}) =>
      PairingQr.parse(
        jsonEncode({...fixture, ...changes}),
        now: now,
        allowHttp: allowHttp,
      );

  test('web QR contract supplies phone server and one-time code', () {
    final qr = parse({});
    expect(qr.server, 'https://relay.example.com');
    expect(qr.code, fixture['pairing_code']);
    expect(qr.expiresAt, fixture['expires_at']);
  });
  test(
    'reject expired, unsupported and malformed QR before network access',
    () {
      for (final change in [
        {'expires_at': 1900000000},
        {'expires_at': '2000000000'},
        {'version': 2},
        {'type': 'other'},
        {'pairing_code': 'bad\ncode'},
        {'server': 'https://user:secret@relay.example.com'},
        {'server': 'https://relay.example.com/api'},
        {'server': 'https://relay.example.com?token=secret'},
        {'server': 'http://127.0.0.1:8787'},
      ]) {
        expect(() => parse(change), throwsFormatException);
      }
      for (final raw in ['https://example.com', '[]', 'null', 'x' * 4097]) {
        expect(() => PairingQr.parse(raw, now: now), throwsFormatException);
      }
    },
  );
  test('HTTP requires explicit development opt-in', () {
    expect(
      parse({'server': 'http://127.0.0.1:8787/'}, allowHttp: true).server,
      'http://127.0.0.1:8787',
    );
  });
}
