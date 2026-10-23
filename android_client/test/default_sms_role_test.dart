import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:privrelay/core/database.dart';
import 'package:privrelay/core/platform.dart';
import 'package:privrelay/data/repository.dart';

class FakeSmsRolePlatform extends SmsPlatform {
  bool isDefault = false;
  bool allowRequest = true;

  @override
  Future<bool> requestSmsRole() async {
    if (allowRequest) isDefault = true;
    return isDefault;
  }

  @override
  Future<Map<String, dynamic>> status() async => {'default_sms': isDefault};
}

void main() {
  test(
    'default SMS role is an explicit opt-in and refreshes native status',
    () async {
      final platform = FakeSmsRolePlatform();
      final repository = RelayRepository(
        AppDatabase(NativeDatabase.memory()),
        platform: platform,
      );

      platform.allowRequest = false;
      expect(await repository.requestDefaultSmsRole(), isFalse);
      expect(repository.permissions['default_sms'], isFalse);

      platform.allowRequest = true;
      expect(await repository.requestDefaultSmsRole(), isTrue);
      expect(repository.permissions['default_sms'], isTrue);
      await repository.close();
    },
  );
}
