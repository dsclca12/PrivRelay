import 'dart:async';

import 'package:flutter/material.dart' hide Text;
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app/app.dart';
import 'data/repository.dart';
import 'core/localized_text.dart';

@pragma('vm:entry-point')
Future<void> backgroundMain() async {
  WidgetsFlutterBinding.ensureInitialized();
  RelayRepository? repository;
  try {
    repository = await RelayRepository.open(listen: false);
    await repository.sync();
  } finally {
    await repository?.close();
    await const MethodChannel('dev.privrelay/worker').invokeMethod('done');
  }
}

@pragma('vm:entry-point')
Future<void> foregroundListenMain() async {
  WidgetsFlutterBinding.ensureInitialized();
  RelayRepository? repository;
  try {
    repository = await RelayRepository.open(
      listen: true,
      persistentSocket: true,
    );
    await repository.sync();
    // The native foreground service owns this isolate. Android destroys the engine
    // when the user disables persistent sync or the OS stops the service.
    await Completer<void>().future;
  } finally {
    await repository?.close();
  }
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const Bootstrap());
}

class Bootstrap extends StatefulWidget {
  const Bootstrap({super.key});
  @override
  State<Bootstrap> createState() => _BootstrapState();
}

class _BootstrapState extends State<Bootstrap> {
  late Future<RelayRepository> future = RelayRepository.open();
  @override
  Widget build(BuildContext context) => FutureBuilder<RelayRepository>(
    future: future,
    builder: (context, snapshot) {
      if (snapshot.hasData) {
        return ProviderScope(
          overrides: [repositoryProvider.overrideWithValue(snapshot.data!)],
          child: const RelayApp(),
        );
      }
      return MaterialApp(
        home: Scaffold(
          body: Center(
            child: snapshot.hasError
                ? Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.lock_outline, size: 48),
                        const Text(
                          '无法打开受保护的本地数据。请保留应用数据，稍后重试。',
                          textAlign: TextAlign.center,
                        ),
                        FilledButton(
                          onPressed: () {
                            setState(() {
                              future = RelayRepository.open();
                            });
                          },
                          child: const Text('重试'),
                        ),
                      ],
                    ),
                  )
                : const CircularProgressIndicator(),
          ),
        ),
      );
    },
  );
}
