import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../app/app.dart';
import '../data/models/message.dart';

class AISettingsPage extends ConsumerStatefulWidget {
  const AISettingsPage({super.key});
  @override
  ConsumerState<AISettingsPage> createState() => _AISettingsPageState();
}

class _AISettingsPageState extends ConsumerState<AISettingsPage> {
  final address = TextEditingController(),
      model = TextEditingController(),
      keyInput = TextEditingController();
  Map<String, dynamic>? config;
  bool busy = false, failed = false, clearKey = false;
  String testResult = '';
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    setState(() => failed = false);
    try {
      final value = await ref.read(repositoryProvider).aiSettings();
      if (!mounted) return;
      setState(() {
        config = value;
        address.text = value['base_url'] as String;
        model.text = value['model'] as String;
      });
    } catch (_) {
      if (mounted) setState(() => failed = true);
    }
  }

  @override
  void dispose() {
    address.dispose();
    model.dispose();
    keyInput.dispose();
    super.dispose();
  }

  Future<void> save() async {
    if (busy) return;
    final value = config!;
    if (value['mode'] != 'disabled') {
      if (address.text.trim().isEmpty || model.text.trim().isEmpty) {
        throw StateError('请填写接口地址和模型名称');
      }
      if (!await confirm(
        context,
        '确认 AI 处理目的地',
        '将向 ${address.text.trim()} 发送短信发件人和正文用于分类。${value['auto_quarantine'] == true ? '同时允许符合条件的营销和可疑消息进入可恢复的隔离箱。' : ''}',
      )) {
        return;
      }
    }
    if (!mounted) return;
    setState(() => busy = true);
    try {
      final result = await ref.read(repositoryProvider).saveAI({
        ...value,
        'base_url': address.text.trim(),
        'model': model.text.trim(),
        'api_key': keyInput.text,
        'clear_api_key': clearKey,
      });
      if (!mounted) return;
      setState(() {
        config = result;
        clearKey = false;
        keyInput.clear();
        testResult = 'AI 配置已保存';
      });
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> test() async {
    if (busy) return;
    setState(() => busy = true);
    try {
      final result = await ref.read(repositoryProvider).testAI();
      if (mounted) {
        setState(
          () => testResult =
              '连接成功 · ${result['model_version']} · ${categories[result['category']]}（合成测试，不保存为短信）',
        );
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final value = config;
    if (failed) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('请先配对并连接服务器'),
            TextButton(onPressed: load, child: const Text('重试')),
          ],
        ),
      );
    }
    if (value == null) return const Center(child: CircularProgressIndicator());
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text('AI / LLM 自动分类', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 16),
        DropdownButtonFormField<String>(
          initialValue: value['mode'] as String,
          isExpanded: true,
          decoration: const InputDecoration(labelText: '分类方式'),
          items: const [
            DropdownMenuItem(value: 'disabled', child: Text('关闭 LLM，使用轻量分类器')),
            DropdownMenuItem(
              value: 'fallback',
              child: Text('轻量模型失败或需复核时使用 LLM'),
            ),
            DropdownMenuItem(value: 'primary', child: Text('直接使用 LLM 分类')),
          ],
          onChanged: busy ? null : (v) => setState(() => value['mode'] = v),
        ),
        const SizedBox(height: 16),
        TextField(
          controller: address,
          enabled: !busy,
          keyboardType: TextInputType.url,
          autocorrect: false,
          decoration: const InputDecoration(
            labelText: 'API 基础地址（通常以 /v1 结尾）',
            border: OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: model,
          enabled: !busy,
          autocorrect: false,
          decoration: const InputDecoration(
            labelText: '模型名称',
            border: OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: keyInput,
          enabled: !busy,
          obscureText: true,
          autocorrect: false,
          enableSuggestions: false,
          decoration: InputDecoration(
            labelText: value['has_api_key'] == true
                ? 'API Key（已保存，留空保留）'
                : 'API Key（免鉴权服务可留空）',
            border: const OutlineInputBorder(),
          ),
        ),
        CheckboxListTile(
          contentPadding: EdgeInsets.zero,
          value: clearKey,
          onChanged: busy ? null : (v) => setState(() => clearKey = v!),
          title: const Text('清除已保存密钥'),
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          value: value['allow_http'] == true,
          title: const Text('允许 HTTP'),
          subtitle: const Text('仅限可信本机或内网'),
          onChanged: busy
              ? null
              : (v) => setState(() => value['allow_http'] = v),
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          value: value['auto_quarantine'] == true,
          title: const Text('允许 LLM 自动隔离'),
          subtitle: const Text('仅营销和可疑短信；还需启用过滤或拦截模式'),
          onChanged: busy
              ? null
              : (v) => setState(() => value['auto_quarantine'] = v),
        ),
        Text('最低置信度与风险分数：${((value['threshold'] as num) * 100).round()}%'),
        Slider(
          value: (value['threshold'] as num).toDouble(),
          min: 0.8,
          max: 1,
          divisions: 20,
          onChanged: busy
              ? null
              : (v) => setState(() => value['threshold'] = v),
        ),
        const Text('两项分数均需达到阈值，模型分数未经校准。验证码、交易、安全内容、白名单和人工恢复优先保护；错误时正常保留。'),
        const SizedBox(height: 12),
        const Text('默认地址、模型和密钥为空，不会自动连接服务。配置用于新消息与待分类消息，不回溯全部历史。'),
        const SizedBox(height: 16),
        FilledButton(
          onPressed: busy ? null : () => perform(context, save),
          child: const Text('保存 AI 配置'),
        ),
        OutlinedButton(
          onPressed: busy ? null : () => perform(context, test),
          child: const Text('测试已保存配置（合成短信）'),
        ),
        if (busy) const LinearProgressIndicator(),
        if (testResult.isNotEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Text(testResult),
          ),
      ],
    );
  }
}
