import 'package:flutter/services.dart';

class SmsPlatform {
  final MethodChannel channel;
  const SmsPlatform({this.channel = const MethodChannel('dev.privrelay/sms')});
  Future<Map<String, dynamic>> status() async =>
      Map<String, dynamic>.from(await channel.invokeMapMethod('status') ?? {});
  Future<bool> requestSms() async =>
      await channel.invokeMethod<bool>('requestSms') ?? false;
  Future<bool> requestNotifications() async =>
      await channel.invokeMethod<bool>('requestNotifications') ?? false;
  Future<List<Map<String, dynamic>>> peek() async =>
      (await channel.invokeListMethod('peek') ?? [])
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
  Future<void> ack(List<String> ids) => channel.invokeMethod('ack', ids);
  Future<void> initialize() => channel.invokeMethod('initialize');
  Future<void> schedule([int seconds = 30]) =>
      channel.invokeMethod('schedule', seconds);
  Future<bool> lock() async =>
      await channel.invokeMethod<bool>('lock') ?? false;
  Future<void> unlock() => channel.invokeMethod('unlock');
  Future<Map<String, dynamic>> identity() async =>
      Map<String, dynamic>.from((await channel.invokeMapMethod('identity'))!);
  Future<String> sign(String value) async =>
      (await channel.invokeMethod<String>('sign', value))!;
  Future<void> protectScreen(bool enabled) =>
      channel.invokeMethod('protectScreen', enabled);
  Future<void> notify(String id) => channel.invokeMethod('notify', id);
}
