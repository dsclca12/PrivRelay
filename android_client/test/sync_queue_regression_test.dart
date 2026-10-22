import 'dart:async';

import 'package:dio/dio.dart';
import 'package:drift/native.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:privrelay/core/database.dart';
import 'package:privrelay/core/platform.dart';
import 'package:privrelay/data/models/message.dart';
import 'package:privrelay/data/repository.dart';

class QueuePlatform extends SmsPlatform {
  bool available = true;
  int unlocks = 0;
  @override
  Future<bool> lock() async => available;
  @override
  Future<void> unlock() async {
    unlocks++;
  }

  @override
  Future<List<Map<String, dynamic>>> peek() async => [];
  @override
  Future<void> notify(String id) async {}
  @override
  Future<void> schedule([int seconds = 30]) async {}
}

// UI mutations stay queued while tests explicitly control request timing.
class QueueRepository extends RelayRepository {
  QueueRepository(super.db, {required super.http});
  @override
  Future<void> sync() async {}
}

const fixture = SmsMessage(
  id: 'message',
  sender: 'TEST',
  body: 'synthetic',
  receivedAt: 100,
);

void reject(
  RequestOptions options,
  RequestInterceptorHandler handler,
  int code,
) {
  handler.reject(
    DioException(
      requestOptions: options,
      type: DioExceptionType.badResponse,
      response: Response(requestOptions: options, statusCode: code),
    ),
  );
}

void accept(
  RequestOptions options,
  RequestInterceptorHandler handler,
  Object data,
) {
  handler.resolve(
    Response(requestOptions: options, statusCode: 200, data: data),
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() {
    FlutterSecureStorage.setMockInitialValues({'token': 'current-token'});
  });

  test('a delayed restore cannot be overtaken by a later archive', () async {
    final db = AppDatabase(NativeDatabase.memory());
    final http = Dio();
    final r = QueueRepository(db, http: http)..server = 'https://relay.example';
    addTearDown(r.close);
    await db.saveRemote(fixture);
    await r.restore(fixture.id);
    await r.archive(fixture.id, true);
    var first = true;
    final actions = <String>[];
    http.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          actions.add(options.path.split('/').last);
          if (first) {
            first = false;
            reject(options, handler, 503);
          } else {
            accept(
              options,
              handler,
              fixture.toJson()
                ..['archived'] = options.path.endsWith('/archive'),
            );
          }
        },
      ),
    );
    final now = DateTime.now().millisecondsSinceEpoch;
    await expectLater(r.flushOperations(now), throwsA(isA<DioException>()));
    await r.flushOperations(now + 1);
    expect(actions, ['restore']);
    final head = (await db.operationHeads()).single;
    expect(head.kind, 'restore');
    expect(head.retryAt, greaterThan(now + 1));
    await r.flushOperations(now + 3600000);
    await r.flushOperations(now + 3600000);
    expect(actions, ['restore', 'restore', 'archive']);
    expect((await db.find(fixture.id))!.archived, isTrue);
    expect(await db.select(db.operations).get(), isEmpty);
  });

  test('an archive response preserves a newer unarchive action', () async {
    final db = AppDatabase(NativeDatabase.memory());
    final http = Dio();
    final r = QueueRepository(db, http: http)..server = 'https://relay.example';
    addTearDown(r.close);
    await db.saveRemote(fixture);
    await r.archive(fixture.id, true);
    final started = Completer<void>();
    final release = Completer<void>();
    http.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          started.complete();
          await release.future;
          accept(options, handler, fixture.toJson()..['archived'] = true);
        },
      ),
    );
    final flush = r.flushOperations(DateTime.now().millisecondsSinceEpoch);
    await started.future;
    await r.archive(fixture.id, false);
    release.complete();
    await flush;
    expect((await db.find(fixture.id))!.archived, isFalse);
    expect((await db.select(db.operations).get()).single.kind, 'unarchive');
  });

  test('a canceled operation in the selected batch is never sent', () async {
    final db = AppDatabase(NativeDatabase.memory());
    final http = Dio();
    final r = QueueRepository(db, http: http)..server = 'https://relay.example';
    addTearDown(r.close);
    const second = SmsMessage(
      id: 'second',
      sender: 'TEST',
      body: 'x',
      receivedAt: 101,
    );
    await db.saveRemote(fixture);
    await db.saveRemote(second);
    await r.archive(fixture.id, true);
    await r.archive(second.id, true);
    final started = Completer<void>();
    final release = Completer<void>();
    final paths = <String>[];
    http.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          paths.add(options.path);
          if (!started.isCompleted) {
            started.complete();
            await release.future;
          }
          accept(options, handler, fixture.toJson()..['archived'] = true);
        },
      ),
    );
    final flush = r.flushOperations(DateTime.now().millisecondsSinceEpoch);
    await started.future;
    await r.restore(second.id);
    release.complete();
    await flush;
    expect(paths, ['https://relay.example/api/v1/messages/message/archive']);
    expect((await db.select(db.operations).get()).single.kind, 'restore');
    expect((await db.find(second.id))!.archived, isFalse);
  });

  for (final status in [409, 413, 422]) {
    test(
      'a $status batch isolates rejection and uploads valid neighbors',
      () async {
        final db = AppDatabase(NativeDatabase.memory());
        final http = Dio();
        final r = RelayRepository(db, http: http, platform: QueuePlatform());
        addTearDown(r.close);
        await db.setPref('server', 'https://relay.example');
        await db.ingest([
          for (final id in ['good-before', 'bad', 'good-after'])
            SmsMessage(
              id: id,
              sender: 'TEST',
              body: 'synthetic',
              receivedAt: 100,
            ),
        ]);
        http.interceptors.add(
          InterceptorsWrapper(
            onRequest: (options, handler) {
              if (options.method == 'GET') {
                accept(options, handler, {
                  'messages': [],
                  'cursor': 0,
                  'has_more': false,
                });
                return;
              }
              final messages = (options.data as Map)['messages'] as List;
              if (messages.any((m) => m['message_id'] == 'bad')) {
                reject(options, handler, status);
              } else {
                accept(options, handler, {'messages': messages});
              }
            },
          ),
        );
        await r.sync();
        expect(await db.countState(['acked']), 2);
        expect((await db.find('bad'))!.syncState, 'rejected');
        expect(r.error, isEmpty);
        expect(await db.pref('last_rejection'), contains('$status'));
      },
    );
  }

  test('a transient split failure preserves acknowledged neighbors', () async {
    final db = AppDatabase(NativeDatabase.memory());
    final http = Dio();
    final r = RelayRepository(db, http: http, platform: QueuePlatform());
    addTearDown(r.close);
    await db.setPref('server', 'https://relay.example');
    await db.ingest([
      const SmsMessage(id: 'good', sender: 'TEST', body: 'x', receivedAt: 100),
      const SmsMessage(id: 'bad', sender: 'TEST', body: 'x', receivedAt: 101),
    ]);
    http.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          final messages = (options.data as Map)['messages'] as List;
          if (messages.length > 1) {
            reject(options, handler, 422);
          } else if (messages.single['message_id'] == 'bad') {
            reject(options, handler, 503);
          } else {
            accept(options, handler, {'messages': messages});
          }
        },
      ),
    );
    await r.sync();
    expect((await db.find('good'))!.syncState, 'acked');
    expect((await db.find('bad'))!.syncState, 'failed');
    expect(r.error, contains('503'));
  });

  test('sync refreshes persisted credentials and observes another engine unpairing', () async {
    final db = AppDatabase(NativeDatabase.memory());
    final http = Dio();
    final r = RelayRepository(db, http: http, platform: QueuePlatform())
      ..server = 'https://old.example'
      ..token = 'old-token'
      ..rePair = true;
    addTearDown(r.close);
    await db.setPref('server', 'https://current.example');
    await db.setPref('re_pair', 'false');
    final requests = <RequestOptions>[];
    http.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          requests.add(options);
          accept(options, handler, {
            'messages': [],
            'cursor': 0,
            'has_more': false,
          });
        },
      ),
    );
    await r.sync();
    expect(requests.single.uri.host, 'current.example');
    expect(requests.single.headers['Authorization'], 'Bearer current-token');
    expect(r.rePair, isFalse);
    await r.secure.delete(key: 'token');
    await r.sync();
    expect(requests, hasLength(1));
    expect(r.token, isNull);
    expect(r.state, '本地模式');
  });

  test('deduplicated upload ACK migrates the local row and queued action atomically', () async {
    final db = AppDatabase(NativeDatabase.memory());
    final http = Dio();
    final r = RelayRepository(db, http: http, platform: QueuePlatform());
    addTearDown(r.close);
    await db.setPref('server', 'https://relay.example');
    final canonical = SmsMessage.fromJson(
      fixture.toJson()..['message_id'] = 'canonical',
    );
    await db.saveRemote(canonical);
    await db.ingest([fixture]);
    await db
        .into(db.operations)
        .insert(
          OperationsCompanion.insert(
            id: 'archive-operation',
            messageId: fixture.id,
            kind: 'archive',
            payload: '{}',
          ),
        );
    final paths = <String>[];
    http.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          paths.add(options.path);
          if (options.path.endsWith('/sync')) {
            accept(options, handler, {
              'messages': [
                fixture.toJson()..['canonical_message_id'] = canonical.id,
              ],
            });
          } else if (options.path.endsWith('/archive')) {
            accept(options, handler, canonical.toJson()..['archived'] = true);
          } else {
            accept(options, handler, {
              'messages': [],
              'cursor': 1,
              'has_more': false,
            });
          }
        },
      ),
    );
    await r.sync();
    expect(r.error, isEmpty);
    expect(await db.find(fixture.id), isNull);
    expect((await db.select(db.messages).get()).single.id, canonical.id);
    expect((await db.find(canonical.id))!.archived, isTrue);
    expect(
      paths,
      contains('https://relay.example/api/v1/messages/canonical/archive'),
    );
    expect(await db.select(db.operations).get(), isEmpty);
  });

  test('alias migration preserves the chronological intent of merged action queues', () async {
    final db = AppDatabase(NativeDatabase.memory());
    addTearDown(db.close);
    final canonical = SmsMessage.fromJson(
      fixture.toJson()..['message_id'] = 'canonical',
    );
    await db.ingest([fixture]);
    await db.saveRemote(canonical);
    await db
        .into(db.operations)
        .insert(
          OperationsCompanion.insert(
            id: 'older-archive',
            messageId: fixture.id,
            kind: 'archive',
            payload: '{}',
          ),
        );
    await db
        .into(db.operations)
        .insert(
          OperationsCompanion.insert(
            id: 'newer-restore',
            messageId: canonical.id,
            kind: 'restore',
            payload: '{}',
          ),
        );
    final saved = await db.saveUploadAck(fixture, canonicalId: canonical.id);
    expect(saved.id, canonical.id);
    expect(saved.archived, isFalse);
    expect(
      (await db.select(db.operations).get()).map((op) => op.messageId),
      everyElement(canonical.id),
    );
    expect((await db.operationHeads()).single.id, 'older-archive');
    expect(await db.find(fixture.id), isNull);
  });

  test(
    'pairing and unpairing preserve credentials while another engine syncs',
    () async {
      final db = AppDatabase(NativeDatabase.memory());
      final platform = QueuePlatform()..available = false;
      final r = RelayRepository(db, platform: platform)
        ..server = 'https://current.example'
        ..token = 'current-token';
      addTearDown(r.close);
      await db.setPref('server', r.server);
      await expectLater(
        r.pair('https://new.example', 'pairing-code'),
        throwsStateError,
      );
      expect(r.busy, isFalse);
      await expectLater(r.unpair(), throwsStateError);
      expect(r.busy, isFalse);
      expect(r.token, 'current-token');
      expect(await r.secure.read(key: 'token'), 'current-token');
      expect(await db.pref('server'), 'https://current.example');
      expect(
        platform.unlocks,
        0,
        reason: 'Never release another engine’s lock',
      );
    },
  );
}
