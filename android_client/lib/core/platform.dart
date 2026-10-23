import 'package:flutter/services.dart';

class SmsPlatform {
  final MethodChannel channel;
  const SmsPlatform({this.channel = const MethodChannel('dev.privrelay/sms')});
  Future<Map<String, dynamic>> status() async =>
      Map<String, dynamic>.from(await channel.invokeMapMethod('status') ?? {});
  Future<bool> requestSmsRole() async =>
      await channel.invokeMethod<bool>('requestSmsRole') ?? false;
  Future<bool> requestSms() async =>
      await channel.invokeMethod<bool>('requestSms') ?? false;
  Future<bool> requestReadSms() async =>
      await channel.invokeMethod<bool>('requestReadSms') ?? false;
  Future<List<Map<String, dynamic>>> importHistory([int limit = 5000]) async =>
      (await channel.invokeListMethod('importHistory', limit) ?? [])
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
  Future<bool> requestSendSms() async =>
      await channel.invokeMethod<bool>('requestSendSms') ?? false;
  Future<int> sendSms(String address, String body) async =>
      ((await channel.invokeMapMethod<String, dynamic>('sendSms', {
                'address': address,
                'body': body,
              }))?['parts']
              as num?)
          ?.toInt() ??
      0;
  Future<bool> requestNotifications() async =>
      await channel.invokeMethod<bool>('requestNotifications') ?? false;
  Future<List<Map<String, dynamic>>> peek() async =>
      (await channel.invokeListMethod('peek') ?? [])
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
  Future<void> ack(List<String> ids) => channel.invokeMethod('ack', ids);
  Future<bool> authenticate() async =>
      await channel.invokeMethod<bool>('authenticate') ?? false;
  Future<void> initialize() => channel.invokeMethod('initialize');
  Future<void> schedule([int seconds = 30]) =>
      channel.invokeMethod('schedule', seconds);
  Future<bool> lock() async =>
      await channel.invokeMethod<bool>('lock') ?? false;
  Future<void> unlock() => channel.invokeMethod('unlock');
  Future<void> setForegroundSync(bool enabled) =>
      channel.invokeMethod('foregroundSync', enabled);
  Future<List<Map<String, dynamic>>> takeLiveRelays() async =>
      (await channel.invokeListMethod('takeLiveRelays') ?? [])
          .map((item) => Map<String, dynamic>.from(item as Map))
          .toList();
  Future<void> publishLiveRelay(Map<String, dynamic> message) =>
      channel.invokeMethod('publishLiveRelay', message);
  Future<Map<String, dynamic>> identity() async =>
      Map<String, dynamic>.from((await channel.invokeMapMethod('identity'))!);
  Future<String> sign(String value) async =>
      (await channel.invokeMethod<String>('sign', value))!;
  Future<String> encryptVault(
    String plaintext,
    String passphrase,
    String salt,
  ) async => (await channel.invokeMethod<String>('encryptVault', {
    'plaintext': plaintext,
    'passphrase': passphrase,
    'salt': salt,
  }))!;
  Future<String> decryptVault(
    String ciphertext,
    String passphrase,
    String salt,
  ) async => (await channel.invokeMethod<String>('decryptVault', {
    'ciphertext': ciphertext,
    'passphrase': passphrase,
    'salt': salt,
  }))!;
  Future<void> protectScreen(bool enabled) =>
      channel.invokeMethod('protectScreen', enabled);
  Future<void> notify(String id) => channel.invokeMethod('notify', id);
}
