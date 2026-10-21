import 'dart:convert';

import '../data/repository.dart' show validateServer;

/// Versioned QR contract shared with web_client and contracts/pairing.json.
class PairingQr {
  final String server;
  final String code;
  final int expiresAt;
  const PairingQr(this.server, this.code, this.expiresAt);

  static PairingQr parse(String raw, {bool allowHttp = false, DateTime? now}) {
    if (raw.length > 4096) throw const FormatException('二维码内容过长');
    final Object? data;
    try {
      data = jsonDecode(raw);
    } catch (_) {
      throw const FormatException('请扫描 PrivRelay 设备中心生成的二维码');
    }
    if (data is! Map<String, dynamic> ||
        data['type'] != 'privrelay-pairing' ||
        data['version'] != 1 ||
        data['server'] is! String ||
        data['pairing_code'] is! String ||
        data['expires_at'] is! int) {
      throw const FormatException('不是支持的 PrivRelay 配对二维码');
    }
    final code = data['pairing_code'] as String;
    if (!RegExp(r'^[A-Za-z0-9_-]{16,128}$').hasMatch(code)) {
      throw const FormatException('配对码格式无效');
    }
    final expiry = data['expires_at'] as int;
    if (expiry <= (now ?? DateTime.now()).millisecondsSinceEpoch ~/ 1000) {
      throw const FormatException('二维码已过期，请在设备中心重新生成');
    }
    return PairingQr(
      validateServer(data['server'] as String, allowHttp: allowHttp),
      code,
      expiry,
    );
  }
}
