import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:privrelay/core/database.dart';
import 'package:privrelay/data/models/message.dart';
import 'package:privrelay/data/repository.dart';

import 'fake_vault_platform.dart';
import 'sync_queue_regression_test.dart' show QueuePlatform, accept, reject;

class ControlledRepository extends RelayRepository {
  ControlledRepository(super.db, {required super.http})
    : super(platform: QueuePlatform()) {
    server = 'https://relay.example';
    token = 'synthetic-token';
    vaultPassphrase = 'synthetic-passphrase';
    vaultSalt = 'synthetic-salt';
  }
  @override
  Future<void> sync() async {}
}

const message = SmsMessage(
  id: 'message',
  sender: 'TEST',
  body: 'synthetic',
  receivedAt: 100,
  category: 'marketing',
  action: 'quarantine',
  serverRevision: 1,
);

class RejectVaultPlatform extends QueuePlatform {
  @override
  Future<Map<String, dynamic>> identity() async => {
    'device_id': 'test',
    'public_key': 'synthetic',
  };
  @override
  Future<String> sign(String value) async => 'synthetic-signature';
  @override
  Future<String> decryptVault(
    String cipher,
    String passphrase,
    String salt,
  ) async => throw const FormatException('synthetic wrong key');
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('operation receipt adopts newer remote state and preserves later queued intent', () async {
    final db = AppDatabase(NativeDatabase.memory());
    final http = Dio();
    final r = ControlledRepository(db, http: http);
    addTearDown(r.close);
    await db.saveRemote(message);
    await r.restore(message.id);
    await r.feedback(message.id, 'service');
    final restore = (await db.operationHeads()).single;
    final remote = message.toJson()
      ..['action'] = 'allow'
      ..['archived'] = true;
    http.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          final envelope = (options.data as Map)['messages'][0];
          expect(envelope['operation_id'], restore.id);
          expect(envelope['operation_kind'], 'restore');
          accept(options, handler, {
            'messages': [
              {
                'message_id': message.id,
                'received_at': message.receivedAt,
                'revision': 3,
                'operation_replayed': true,
                'ciphertext': base64Encode(utf8.encode(jsonEncode(remote))),
              },
            ],
          });
        },
      ),
    );
    await r.flushOperations(1000);
    final saved = (await db.find(message.id))!;
    expect(
      saved.archived,
      isTrue,
      reason: 'Old restore must not undo a newer remote archive',
    );
    expect(saved.correctedCategory, 'service');
    expect(saved.serverRevision, 3);
    expect((await db.select(db.operations).get()).single.kind, 'feedback');
  });
  test('wrong shared passphrase cannot replace saved credentials or upload local messages', () async {
    FlutterSecureStorage.setMockInitialValues({
      'token': 'old-token',
      'vault_passphrase': 'existing-passphrase',
      'vault_salt': 'old-salt',
    });
    final db = AppDatabase(NativeDatabase.memory());
    final http = Dio();
    final r = RelayRepository(db, http: http, platform: RejectVaultPlatform())
      ..server = 'https://relay.example'
      ..token = 'old-token'
      ..vaultPassphrase = 'candidate-wrong-passphrase';
    addTearDown(r.close);
    final paths = <String>[];
    http.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          paths.add(options.path);
          if (options.path.endsWith('/register')) {
            accept(options, handler, {'token': 'new-token'});
          } else if (options.path.endsWith('/params')) {
            accept(options, handler, {'salt': 'new-salt'});
          } else if (options.method == 'GET') {
            accept(options, handler, {
              'messages': [
                {'ciphertext': 'synthetic-existing-cipher'},
              ],
            });
          } else {
            fail('Must not upload or migrate before verifying the shared key');
          }
        },
      ),
    );
    await expectLater(r.pair(r.server, 'synthetic-code'), throwsStateError);
    expect(await r.secure.read(key: 'token'), 'old-token');
    expect(await r.secure.read(key: 'vault_passphrase'), 'existing-passphrase');
    expect(await r.secure.read(key: 'vault_salt'), 'old-salt');
    expect(r.vaultPassphrase, 'existing-passphrase');
    expect(paths, hasLength(3));
  });
  test(
    'missing operation ACK retains local intent and retry metadata',
    () async {
      final db = AppDatabase(NativeDatabase.memory());
      final http = Dio();
      final r = ControlledRepository(db, http: http);
      addTearDown(r.close);
      await db.saveRemote(message);
      await r.restore(message.id);
      http.interceptors.add(
        InterceptorsWrapper(
          onRequest: (options, handler) {
            expect((options.data as Map)['messages'][0]['base_revision'], 1);
            expect(
              decodedEnvelope((options.data as Map)['messages'][0])['action'],
              'allow',
            );
            accept(options, handler, {'messages': []});
          },
        ),
      );
      await expectLater(r.flushOperations(1000), throwsFormatException);
      final op = (await db.select(db.operations).get()).single;
      expect(op.kind, 'restore');
      expect(op.attempts, 1);
      expect((await db.find(message.id))!.action, 'allow');
    },
  );

  test('CAS conflict pulls fresh revision and merges queued correction without replacing original prediction', () async {
    final db = AppDatabase(NativeDatabase.memory());
    final http = Dio();
    final r = ControlledRepository(db, http: http);
    addTearDown(r.close);
    await db.saveRemote(message);
    await r.feedback(message.id, 'service');
    var conflict = true;
    http.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          if (options.method == 'GET') {
            accept(options, handler, {
              'messages': [
                {
                  'message_id': message.id,
                  'received_at': message.receivedAt,
                  'revision': 2,
                  'ciphertext': base64Encode(
                    utf8.encode(
                      jsonEncode(message.toJson()..['archived'] = true),
                    ),
                  ),
                },
              ],
              'cursor': 2,
              'has_more': false,
            });
          } else if (conflict) {
            conflict = false;
            reject(options, handler, 409);
          } else {
            final envelope = (options.data as Map)['messages'][0];
            expect(envelope['base_revision'], 2);
            final plain = decodedEnvelope(envelope);
            expect(plain['category'], 'marketing');
            expect(plain['corrected_category'], 'service');
            expect(plain['archived'], isTrue);
            accept(options, handler, {
              'messages': [
                {'message_id': message.id, 'revision': 3},
              ],
            });
          }
        },
      ),
    );
    await expectLater(r.flushOperations(1000), throwsA(isA<DioException>()));
    expect((await db.select(db.operations).get()).length, 1);
    expect((await db.find(message.id))!.serverRevision, 2);
    await r.flushOperations(3600000);
    final saved = (await db.find(message.id))!;
    expect(saved.correctedCategory, 'service');
    expect(saved.category, 'marketing');
    expect(saved.archived, isTrue);
    expect(saved.serverRevision, 3);
    expect(await db.select(db.operations).get(), isEmpty);
  });
}
