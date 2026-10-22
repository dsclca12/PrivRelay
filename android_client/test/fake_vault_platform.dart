import 'dart:convert';

import 'package:privrelay/core/platform.dart';

// Reversible test transport only; production cryptography remains native.
mixin FakeVault on SmsPlatform {
  @override
  Future<String> encryptVault(
    String plain,
    String passphrase,
    String salt,
  ) async => base64Encode(utf8.encode(plain));
  @override
  Future<String> decryptVault(
    String cipher,
    String passphrase,
    String salt,
  ) async => utf8.decode(base64Decode(cipher));
}

Map<String, dynamic> decodedEnvelope(dynamic envelope) =>
    Map<String, dynamic>.from(
      jsonDecode(utf8.decode(base64Decode(envelope['ciphertext'] as String)))
          as Map,
    );
