import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:privrelay/core/database.dart';
import 'package:privrelay/core/platform.dart';
import 'package:privrelay/data/models/message.dart';
import 'package:privrelay/data/repository.dart';

class EmptySpool extends SmsPlatform {
  final scheduled = <int>[];
  @override
  Future<bool> lock() async => true;
  @override
  Future<void> unlock() async {}
  @override
  Future<List<Map<String, dynamic>>> peek() async => [];
  @override
  Future<void> schedule([int seconds = 30]) async => scheduled.add(seconds);
  String? signed;
  @override
  Future<Map<String, dynamic>> identity() async => {
    'device_id': 'synthetic-phone-identity',
    'public_key': 'synthetic-key',
  };
  @override
  Future<String> sign(String value) async {
    signed = value;
    return 'synthetic-signature';
  }
}

class PairingRepository extends RelayRepository {
  PairingRepository(super.db, {required super.platform});
  @override
  void connectSocket() {}
}

void main() {
  test(
    'changing server resets the old cursor and trims the signed pairing code',
    () async {
      FlutterSecureStorage.setMockInitialValues({});
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final cursors = <String>[];
      final listener = server.listen((request) async {
        request.response.headers.contentType = ContentType.json;
        if (request.uri.path.endsWith('/register')) {
          final data =
              jsonDecode(await utf8.decoder.bind(request).join()) as Map;
          expect(data['pairing_code'], 'synthetic-pairing-code');
          request.response.statusCode = 201;
          request.response.write(
            jsonEncode({
              'token': 'synthetic-token',
              'device_id': data['device_id'],
            }),
          );
        } else {
          cursors.add(request.uri.queryParameters['cursor']!);
          request.response.write(
            jsonEncode({'messages': [], 'cursor': 0, 'has_more': false}),
          );
        }
        await request.response.close();
      });
      final db = AppDatabase(NativeDatabase.memory());
      await db.setPref('cursor', '900');
      final platform = EmptySpool();
      final r = PairingRepository(db, platform: platform)
        ..server = 'https://old.example.com';
      try {
        await r.pair(
          'http://127.0.0.1:${server.port}',
          '  synthetic-pairing-code\n',
          allowHttp: true,
        );
        expect(platform.signed, endsWith('\nsynthetic-pairing-code'));
        expect(cursors, ['0']);
        expect(await db.pref('cursor'), '0');
        expect(r.error, isEmpty);
      } finally {
        await r.close();
        await listener.cancel();
        await server.close(force: true);
      }
    },
  );
  test('bounded pull schedules remaining remote pages even without pending uploads', () async {
    FlutterSecureStorage.setMockInitialValues({'token': 'synthetic-token'});
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final cursors = <int>[];
    final listener = server.listen((request) async {
      expect(request.headers.value('Authorization'), 'Bearer synthetic-token');
      final cursor = int.parse(request.uri.queryParameters['cursor']!);
      cursors.add(cursor);
      final end = min(cursor + 50, 301);
      request.response.headers.contentType = ContentType.json;
      request.response.write(
        jsonEncode({
          'messages': [
            for (var i = cursor; i < end; i++)
              SmsMessage(
                id: 'remote-$i',
                sender: 'synthetic',
                body: 'pagination fixture',
                receivedAt: i,
              ).toJson(),
          ],
          'cursor': end,
          'has_more': end < 301,
        }),
      );
      await request.response.close();
    });
    final db = AppDatabase(NativeDatabase.memory());
    await db.setPref('server', 'http://127.0.0.1:${server.port}');
    final platform = EmptySpool();
    final r = RelayRepository(db, platform: platform)
      ..server = 'http://127.0.0.1:${server.port}'
      ..token = 'synthetic-token';
    try {
      await r.sync();
      expect(r.error, isEmpty);
      expect(r.pending, 0);
      expect(await db.pref('cursor'), '250');
      expect(platform.scheduled, [
        1,
      ], reason: 'More remote history must cause an immediate continuation');
      await r.sync();
      expect(await db.pref('cursor'), '301');
      expect(await db.countState(['acked']), 301);
      expect(cursors, [0, 50, 100, 150, 200, 250, 300]);
      expect(platform.scheduled, [
        1,
      ], reason: 'Completed history must not schedule a busy loop');
    } finally {
      await r.close();
      await listener.cancel();
      await server.close(force: true);
    }
  });
}
