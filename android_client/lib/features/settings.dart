import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../app/app.dart';

class SettingsPage extends ConsumerStatefulWidget {
  const SettingsPage({super.key});
  @override
  ConsumerState<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends ConsumerState<SettingsPage> {
  late final address = TextEditingController(
    text: ref.read(repositoryProvider).server,
  );
  final code = TextEditingController();
  bool allowHttp = false, pairing = false;
  @override
  void dispose() {
    address.dispose();
    code.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final r = watchRepository(ref);
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text('连接你的服务器', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 12),
        TextField(
          controller: address,
          keyboardType: TextInputType.url,
          autocorrect: false,
          decoration: const InputDecoration(
            labelText: '服务器地址',
            hintText: 'https://relay.example.com',
            border: OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: code,
          obscureText: true,
          autocorrect: false,
          enableSuggestions: false,
          decoration: const InputDecoration(
            labelText: '一次性配对码',
            border: OutlineInputBorder(),
          ),
        ),
        if (kDebugMode)
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            value: allowHttp,
            onChanged: (v) => setState(() => allowHttp = v!),
            title: const Text('开发测试：允许 HTTP'),
            subtitle: const Text('仅用于 ADB 回环或受控测试网络'),
          ),
        const SizedBox(height: 12),
        FilledButton(
          onPressed: pairing || r.busy
              ? null
              : () => perform(context, () async {
                  if (!await confirm(
                    context,
                    '确认同步目的地',
                    '服务器：${address.text}\n配对后将上传本机已接收及后续短信的正文，供服务器分类和同步。',
                  )) {
                    return;
                  }
                  setState(() => pairing = true);
                  try {
                    await r.pair(address.text, code.text, allowHttp: allowHttp);
                    code.clear();
                    if (context.mounted) {
                      ScaffoldMessenger.of(context)
                          .showSnackBar(const SnackBar(content: Text('配对成功')));
                    }
                  } finally {
                    if (mounted) setState(() => pairing = false);
                  }
                }),
          child: Text(pairing ? '正在配对…' : '配对并开始同步'),
        ),
        const SizedBox(height: 24),
        Text('采集与隐私', style: Theme.of(context).textTheme.titleLarge),
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.sms_outlined),
          title: const Text('接收新短信'),
          subtitle: Text(r.permissions['sms'] == true ? '已授权' : '未授权，已有消息仍可查看'),
          onTap: () => perform(context, r.requestSms),
        ),
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.notifications_outlined),
          title: const Text('通知权限'),
          subtitle: const Text('新短信通知只显示通用提示，锁屏不显示正文'),
          onTap: () => perform(context, r.requestNotifications),
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          value: r.backgroundEnabled,
          onChanged: (v) => perform(context, () => r.setBackground(v)),
          title: const Text('后台补发'),
          subtitle: const Text('使用系统任务调度；省电限制下可能延迟。关闭后仍会保存新短信。'),
        ),
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.rule),
          title: const Text('过滤规则'),
          subtitle: const Text('仅分类、智能过滤与主动授权的隔离'),
          onTap: () => context.push('/rules'),
        ),
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.devices),
          title: const Text('设备管理'),
          onTap: () => context.push('/devices'),
        ),
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.monitor_heart_outlined),
          title: const Text('同步诊断'),
          onTap: () => context.push('/diagnostics'),
        ),
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.cleaning_services_outlined),
          title: const Text('清理已上传记录'),
          subtitle: const Text('保留未上传及有待处理操作的消息'),
          onTap: () => perform(context, () async {
            if (await confirm(
              context,
              '清理本地记录？',
              '仅删除本机已上传且没有待处理操作的记录。服务器记录保留。',
            )) {
              await r.clearUploaded();
            }
          }),
        ),
        if (r.token != null)
          TextButton(
            onPressed: () => perform(context, () async {
              if (await confirm(
                context,
                '解除本机配对？',
                '停止向服务器上传，保留本地消息。需要撤销远程访问请先在设备管理中撤销本机。',
              )) {
                await r.unpair();
              }
            }),
            child: const Text('解除本机配对'),
          ),
        const Divider(),
        const Text(
          'PrivRelay · Android MVP 0.1\n本版不是默认短信应用，无法抑制系统短信应用的通知。自托管服务器能够读取正文。分类失败时正常保留，不会删除短信。',
          style: TextStyle(fontSize: 12),
        ),
        const SizedBox(height: 24),
      ],
    );
  }
}

class DiagnosticsPage extends ConsumerWidget {
  const DiagnosticsPage({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = watchRepository(ref);
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text('同步诊断', style: Theme.of(context).textTheme.titleLarge),
        ListTile(title: const Text('当前状态'), subtitle: Text(r.state)),
        ListTile(title: const Text('待上传短信'), trailing: Text('${r.pending}')),
        ListTile(
          title: const Text('待同步操作'),
          trailing: Text('${r.operationCount}'),
        ),
        FutureBuilder<int>(
          future: r.db.countState(['rejected']),
          builder: (_, s) => ListTile(
            title: const Text('上传被拒绝（本地保留）'),
            trailing: Text('${s.data ?? 0}'),
          ),
        ),
        FutureBuilder<String?>(
          future: r.db.pref('last_rejection'),
          builder: (_, s) =>
              s.data == null ? const SizedBox.shrink() : Text(s.data!),
        ),
        FutureBuilder<String?>(
          future: r.db.pref('last_ack'),
          builder: (_, s) => ListTile(
            title: const Text('最近确认'),
            subtitle: Text(s.data ?? '尚无确认'),
          ),
        ),
        FutureBuilder<String?>(
          future: r.db.pref('last_error'),
          builder: (_, s) => ListTile(
            title: const Text('最近错误（不含短信内容）'),
            subtitle: Text(s.data ?? '暂无错误'),
          ),
        ),
        ListTile(
          title: const Text('接收权限'),
          subtitle: Text(r.permissions['sms'] == true ? '已授权' : '未授权'),
        ),
        ListTile(
          title: const Text('原生暂存'),
          subtitle: Text(
            '${r.permissions['spool_count'] ?? '—'} 条（启动与后台任务自动消费）',
          ),
        ),
        FilledButton.icon(
          onPressed: () => r.sync(),
          icon: const Icon(Icons.sync),
          label: const Text('立即同步'),
        ),
        OutlinedButton(
          onPressed: () => perform(context, () async {
            final h = await r.health();
            if (context.mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text(
                    '服务在线 · 分类器${h['classifier'] == 'ok' ? '正常' : '暂不可用（正常保留消息）'}',
                  ),
                ),
              );
            }
          }),
          child: const Text('检查服务健康'),
        ),
        const Padding(
          padding: EdgeInsets.only(top: 24),
          child: Text(
            '系统强行停止应用后 Android 会暂停广播和任务，需手动重新打开。普通后台进程回收由持久化暂存和 WorkManager 恢复。',
          ),
        ),
      ],
    );
  }
}

class RulesPage extends ConsumerStatefulWidget {
  const RulesPage({super.key});
  @override
  ConsumerState<RulesPage> createState() => _RulesPageState();
}

class _RulesPageState extends ConsumerState<RulesPage> {
  Map<String, dynamic>? value;
  String? error;
  final white = TextEditingController(), black = TextEditingController();
  @override
  void initState() {
    super.initState();
    ref
        .read(repositoryProvider)
        .rules()
        .then((v) {
          if (mounted) {
            setState(() {
              value = v;
              white.text = (v['whitelist'] as List).join('\n');
              black.text = (v['blacklist'] as List).join('\n');
            });
          }
        })
        .catchError((Object _) {
          if (mounted) setState(() => error = '请先配对并连接服务器');
        });
  }

  @override
  void dispose() {
    white.dispose();
    black.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final v = value;
    if (v == null) {
      return Center(
        child: error == null ? const CircularProgressIndicator() : Text(error!),
      );
    }
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text('过滤规则', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 16),
        DropdownButtonFormField<String>(
          initialValue: v['mode'],
          decoration: const InputDecoration(labelText: '工作模式'),
          items: const [
            DropdownMenuItem(value: 'classify', child: Text('仅分类')),
            DropdownMenuItem(value: 'filter', child: Text('智能过滤')),
            DropdownMenuItem(value: 'block', child: Text('自动隔离')),
          ],
          onChanged: (m) async {
            if (m == 'block' &&
                !await confirm(
                  context,
                  '启用自动隔离？',
                  '只隔离本应用消息，不删除短信；验证码与交易消息优先保护。当前模型未校准，单凭模型分数不会触发自动隔离，黑名单可生效。',
                )) {
              return;
            }
            setState(() => v['mode'] = m);
          },
        ),
        const SizedBox(height: 16),
        Text('阈值 ${(v['threshold'] as num).toStringAsFixed(2)}'),
        Slider(
          value: (v['threshold'] as num).toDouble(),
          min: 0.8,
          max: 1,
          divisions: 20,
          onChanged: (x) => setState(() => v['threshold'] = x),
        ),
        TextField(
          controller: white,
          minLines: 2,
          maxLines: 4,
          decoration: const InputDecoration(
            labelText: '白名单（完整发件人，每行一个）',
            border: OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: black,
          minLines: 2,
          maxLines: 4,
          decoration: const InputDecoration(
            labelText: '黑名单（完整发件人，每行一个）',
            border: OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 16),
        const Text('白名单优先。验证码、交易通知、疑似安全验证码内容和分类失败消息不自动隔离。未校准的模型只提供分类建议。'),
        const SizedBox(height: 16),
        FilledButton(
          onPressed: () => perform(context, () async {
            List<String> lines(String s) => s
                .split('\n')
                .map((s) => s.trim())
                .where((s) => s.isNotEmpty)
                .toSet()
                .toList();
            await ref.read(repositoryProvider).saveRules({
              ...v,
              'whitelist': lines(white.text),
              'blacklist': lines(black.text),
            });
            if (context.mounted) {
              ScaffoldMessenger.of(context)
                  .showSnackBar(const SnackBar(content: Text('规则已保存，将用于新消息')));
            }
          }),
          child: const Text('保存规则'),
        ),
      ],
    );
  }
}

class DevicesPage extends ConsumerWidget {
  const DevicesPage({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = watchRepository(ref);
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text('设备管理', style: Theme.of(context).textTheme.titleLarge),
        ListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('本机标识'),
          subtitle: SelectableText(r.deviceId),
        ),
        FutureBuilder<List<dynamic>>(
          future: r.devices(),
          builder: (context, s) {
            if (s.hasError) return const Text('未连接服务器，请先配对');
            if (!s.hasData) return const LinearProgressIndicator();
            return Column(
              children: [
                for (final d in s.data!)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.smartphone),
                    title: Text(d['name'] as String),
                    subtitle: Text(
                      d['active'] == true
                          ? '已授权${d['device_id'] == r.deviceId ? ' · 本机' : ''}'
                          : '已撤销',
                    ),
                    trailing: d['active'] == true
                        ? IconButton(
                            tooltip: '撤销授权',
                            icon: const Icon(Icons.link_off),
                            onPressed: () => perform(context, () async {
                              if (await confirm(
                                context,
                                '撤销设备？',
                                '该设备将无法继续读取或上传短信，本地历史保留。',
                              )) {
                                await r.revoke(d['device_id'] as String);
                              }
                            }),
                          )
                        : null,
                  ),
              ],
            );
          },
        ),
      ],
    );
  }
}
