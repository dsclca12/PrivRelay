import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../data/repository.dart';
import '../features/inbox.dart';
import '../features/ai_settings.dart';
import '../features/settings.dart';

final repositoryProvider = Provider<RelayRepository>(
  (ref) => throw UnimplementedError(),
);
final pulseProvider = StreamProvider<int>((ref) {
  final r = ref.watch(repositoryProvider);
  final controller = StreamController<int>();
  var count = 0;
  void listener() {
    controller.add(++count);
  }

  r.addListener(listener);
  ref.onDispose(() {
    r.removeListener(listener);
    controller.close();
  });
  return controller.stream;
});
RelayRepository watchRepository(WidgetRef ref) {
  ref.watch(pulseProvider);
  return ref.watch(repositoryProvider);
}

class RelayApp extends ConsumerStatefulWidget {
  const RelayApp({super.key});
  @override
  ConsumerState<RelayApp> createState() => _RelayAppState();
}

class _RelayAppState extends ConsumerState<RelayApp>
    with WidgetsBindingObserver {
  late final r = ref.read(repositoryProvider);
  late final router = GoRouter(
    initialLocation: r.onboarded ? '/inbox' : '/welcome',
    routes: [
      GoRoute(path: '/welcome', builder: (_, _) => const WelcomePage()),
      GoRoute(
        path: '/message/:id',
        builder: (_, s) => DetailPage(id: s.pathParameters['id']!),
      ),
      ShellRoute(
        builder: (context, state, child) =>
            Shell(location: state.uri.path, child: child),
        routes: [
          GoRoute(path: '/inbox', builder: (_, _) => const InboxPage()),
          GoRoute(
            path: '/quarantine',
            builder: (_, _) => const InboxPage(quarantine: true),
          ),
          GoRoute(path: '/settings', builder: (_, _) => const SettingsPage()),
          GoRoute(
            path: '/diagnostics',
            builder: (_, _) => const DiagnosticsPage(),
          ),
          GoRoute(path: '/ai', builder: (_, _) => const AISettingsPage()),
          GoRoute(path: '/rules', builder: (_, _) => const RulesPage()),
          GoRoute(path: '/devices', builder: (_, _) => const DevicesPage()),
        ],
      ),
    ],
  );
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    unawaited(r.sync());
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.hidden) {
      r.lockApp();
    }
    if (state == AppLifecycleState.resumed) {
      r.load().then((_) {
        r.changed();
        r.sync();
        r.connectSocket();
      });
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    router.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    watchRepository(ref);
    return MaterialApp.router(
      title: 'PrivRelay',
      debugShowCheckedModeBanner: false,
      locale: const Locale('zh', 'CN'),
      supportedLocales: const [Locale('zh', 'CN'), Locale('en')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff24655b)),
        scaffoldBackgroundColor: const Color(0xfff5f7f6),
        cardTheme: const CardThemeData(elevation: 0),
      ),
      darkTheme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xff71cbb6),
          brightness: Brightness.dark,
        ),
      ),
      builder: (context, child) {
        if (!r.appLockEnabled || r.appUnlocked) {
          return child ?? const SizedBox.shrink();
        }
        return Scaffold(
          body: Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.lock_outline, size: 48),
                  const SizedBox(height: 16),
                  const Text('PrivRelay 已锁定'),
                  const SizedBox(height: 16),
                  FilledButton(
                    onPressed: r.authenticating
                        ? null
                        : () => perform(context, () async {
                            if (!await r.unlockApp()) {
                              throw StateError('未完成验证，请重试');
                            }
                          }),
                    child: Text(r.authenticating ? '正在验证…' : '使用设备密码解锁'),
                  ),
                ],
              ),
            ),
          ),
        );
      },
      routerConfig: router,
    );
  }
}

Future<void> perform(BuildContext context, Future<void> Function() task) async {
  try {
    await task();
  } catch (e) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            e is StateError || e is FormatException ? '$e' : '操作未完成，请检查连接后重试',
          ),
        ),
      );
    }
  }
}

Future<bool> confirm(BuildContext context, String title, String body) async =>
    await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(title),
        content: Text(body),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(c, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(c, true),
            child: const Text('确认'),
          ),
        ],
      ),
    ) ??
    false;

class Shell extends ConsumerWidget {
  final String location;
  final Widget child;
  const Shell({super.key, required this.location, required this.child});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = watchRepository(ref);
    final index = location == '/inbox'
        ? 0
        : location == '/quarantine'
        ? 1
        : 2;
    return Scaffold(
      appBar: AppBar(
        title: const Text('PrivRelay'),
        actions: [
          IconButton(
            tooltip: '同步',
            onPressed: r.busy ? null : () => r.sync(),
            icon: const Icon(Icons.sync),
          ),
          IconButton(
            tooltip: '诊断',
            onPressed: () => context.push('/diagnostics'),
            icon: const Icon(Icons.monitor_heart_outlined),
          ),
        ],
      ),
      body: Column(
        children: [
          Semantics(
            liveRegion: true,
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
              child: Row(
                children: [
                  Icon(
                    r.rePair
                        ? Icons.link_off
                        : r.busy
                        ? Icons.sync
                        : Icons.shield_outlined,
                    size: 16,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      '${r.state}${r.pending > 0 ? ' · ${r.pending} 条待发送' : ''}',
                      style: Theme.of(context).textTheme.labelMedium,
                    ),
                  ),
                  if (r.rePair)
                    TextButton(
                      onPressed: () => context.go('/settings'),
                      child: const Text('重新配对'),
                    ),
                ],
              ),
            ),
          ),
          Expanded(child: child),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: index,
        onDestinationSelected: (i) =>
            context.go(['/inbox', '/quarantine', '/settings'][i]),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.inbox_outlined),
            selectedIcon: Icon(Icons.inbox),
            label: '收件箱',
          ),
          NavigationDestination(
            icon: Icon(Icons.shield_outlined),
            selectedIcon: Icon(Icons.shield),
            label: '拦截箱',
          ),
          NavigationDestination(icon: Icon(Icons.tune), label: '设置'),
        ],
      ),
    );
  }
}

class WelcomePage extends ConsumerWidget {
  const WelcomePage({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = watchRepository(ref);
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(28),
          children: [
            const SizedBox(height: 40),
            const Align(
              alignment: Alignment.centerLeft,
              child: Icon(Icons.mark_email_read_outlined, size: 64),
            ),
            const SizedBox(height: 24),
            Text(
              '短信，留在你的掌控中',
              style: Theme.of(context).textTheme.headlineMedium,
            ),
            const SizedBox(height: 16),
            const Text('PrivRelay 先将短信加密保存在本机。只有配对你确认的自托管服务器后，才会上传用于分类和跨设备同步。'),
            const SizedBox(height: 20),
            const ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(Icons.lock_outline),
              title: Text('本地加密'),
              subtitle: Text('不接入第三方统计，不在诊断中记录正文。'),
            ),
            const ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(Icons.cloud_outlined),
              title: Text('自托管分类'),
              subtitle: Text('配对后服务器能够读取短信正文，本版不提供端到端加密。'),
            ),
            const ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(Icons.notifications_none),
              title: Text('关于拦截'),
              subtitle: Text('本版不是默认短信应用，只隔离本应用消息；不能阻止系统短信应用的通知。'),
            ),
            const SizedBox(height: 24),
            FilledButton.icon(
              onPressed: () => perform(context, () async {
                await r.requestSms();
              }),
              icon: Icon(
                r.permissions['sms'] == true ? Icons.check : Icons.sms_outlined,
              ),
              label: Text(
                r.permissions['sms'] == true ? '已允许接收新短信' : '允许接收新短信',
              ),
            ),
            TextButton(
              onPressed: () async {
                await r.finishOnboarding();
                if (context.mounted) context.go('/settings');
              },
              child: const Text('继续设置服务器'),
            ),
            TextButton(
              onPressed: () async {
                await r.finishOnboarding();
                if (context.mounted) context.go('/inbox');
              },
              child: const Text('先在本地使用'),
            ),
            const Text(
              '拒绝权限也能查看已有消息。不会请求读取系统历史短信。',
              style: TextStyle(fontSize: 12),
            ),
          ],
        ),
      ),
    );
  }
}
