import 'package:flutter/material.dart' hide Text;
import 'package:mobile_scanner/mobile_scanner.dart';

import '../core/pairing.dart';
import '../core/localized_text.dart';

class PairingScannerPage extends StatefulWidget {
  final bool allowHttp;
  const PairingScannerPage({super.key, required this.allowHttp});

  @override
  State<PairingScannerPage> createState() => _PairingScannerPageState();
}

class _PairingScannerPageState extends State<PairingScannerPage> {
  bool completed = false;
  String? error;

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('扫码绑定')),
    body: Column(
      children: [
        Expanded(
          // The widget owns its controller and camera lifecycle.
          child: MobileScanner(
            onDetect: (capture) {
              if (completed) return;
              for (final barcode in capture.barcodes) {
                final raw = barcode.rawValue;
                if (raw == null) continue;
                try {
                  final pairing = PairingQr.parse(
                    raw,
                    allowHttp: widget.allowHttp,
                  );
                  completed = true;
                  Navigator.of(context).pop(pairing);
                  return;
                } on FormatException catch (e) {
                  if (error != e.message) setState(() => error = e.message);
                }
              }
            },
            errorBuilder: (_, _) => const Center(
              child: Padding(
                padding: EdgeInsets.all(24),
                child: Text('无法启动相机，请在系统设置中允许相机权限后重试；也可返回手动输入配对码。'),
              ),
            ),
          ),
        ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Text(error ?? '扫描 Web 控制台「设备中心」的二维码，随后确认同步服务器。'),
          ),
        ),
      ],
    ),
  );
}
