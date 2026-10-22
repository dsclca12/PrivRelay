import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../app/app.dart';
import '../data/models/message.dart';

class InboxPage extends ConsumerStatefulWidget {
  final bool quarantine;
  const InboxPage({super.key, this.quarantine = false});
  @override
  ConsumerState<InboxPage> createState() => _InboxPageState();
}

class _InboxPageState extends ConsumerState<InboxPage> {
  final search = TextEditingController();
  String? category;
  int limit = 50;
  bool archived = false;
  @override
  void dispose() {
    search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final r = watchRepository(ref);
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
          child: TextField(
            controller: search,
            onChanged: (_) => setState(() {
              limit = 50;
            }),
            decoration: InputDecoration(
              hintText: '搜索发件人或正文',
              prefixIcon: const Icon(Icons.search),
              filled: true,
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(16),
                borderSide: BorderSide.none,
              ),
            ),
          ),
        ),
        if (!widget.quarantine)
          SwitchListTile(
            title: const Text('查看已归档消息'),
            value: archived,
            onChanged: (value) => setState(() {
              archived = value;
              limit = 50;
            }),
          ),
        SizedBox(
          height: 48,
          child: ListView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 16),
            children: [
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: FilterChip(
                  label: const Text('全部'),
                  selected: category == null,
                  onSelected: (_) => setState(() {
                    category = null;
                    limit = 50;
                  }),
                ),
              ),
              for (final c in categories.entries)
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: FilterChip(
                    label: Text(c.value),
                    selected: category == c.key,
                    onSelected: (_) => setState(() {
                      category = c.key;
                      limit = 50;
                    }),
                  ),
                ),
            ],
          ),
        ),
        if (r.error.isNotEmpty)
          Padding(
            padding: const EdgeInsets.all(8),
            child: Text(r.error, style: Theme.of(context).textTheme.bodySmall),
          ),
        Expanded(
          child: FutureBuilder<List<SmsMessage>>(
            future: () async {
              final result = <SmsMessage>[];
              for (var offset = 0; offset < limit; offset += 50) {
                final page = await r.db.page(
                  quarantine: widget.quarantine,
                  archived: archived,
                  search: search.text,
                  category: category,
                  offset: offset,
                );
                result.addAll(page);
                if (page.length < 50) break;
              }
              return result;
            }(),
            builder: (context, snapshot) {
              if (!snapshot.hasData) {
                return const Center(child: CircularProgressIndicator());
              }
              final rows = snapshot.data!;
              return RefreshIndicator(
                onRefresh: r.sync,
                child: ListView.builder(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: const EdgeInsets.all(12),
                  itemCount: rows.isEmpty ? 1 : rows.length + 1,
                  itemBuilder: (context, i) {
                    if (rows.isEmpty) {
                      return Padding(
                        padding: const EdgeInsets.symmetric(
                          vertical: 64,
                          horizontal: 24,
                        ),
                        child: Column(
                          children: [
                            Icon(
                              widget.quarantine
                                  ? Icons.verified_user_outlined
                                  : Icons.forum_outlined,
                              size: 56,
                            ),
                            const SizedBox(height: 16),
                            Text(
                              search.text.isNotEmpty || category != null
                                  ? '没有匹配的短信'
                                  : widget.quarantine
                                  ? '这里暂时没有被隔离的消息'
                                  : '等待你的第一条短信',
                            ),
                            const SizedBox(height: 8),
                            Text(
                              widget.quarantine
                                  ? '隔离的消息始终可以恢复'
                                  : r.permissions['sms'] == true
                                  ? '新短信会先保存在本机，联网后自动同步'
                                  : '请在设置中允许接收新短信',
                              textAlign: TextAlign.center,
                            ),
                          ],
                        ),
                      );
                    }
                    if (i == rows.length) {
                      return rows.length < limit
                          ? const SizedBox(height: 24)
                          : TextButton(
                              onPressed: () => setState(() {
                                limit += 50;
                              }),
                              child: const Text('加载更多'),
                            );
                    }
                    final m = rows[i];
                    final date = DateTime.fromMillisecondsSinceEpoch(
                      m.receivedAt,
                    ).toLocal();
                    return Card(
                      margin: const EdgeInsets.only(bottom: 8),
                      child: InkWell(
                        borderRadius: BorderRadius.circular(12),
                        onTap: () => context.push('/message/${m.id}'),
                        child: Padding(
                          padding: const EdgeInsets.all(16),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Icon(
                                    m.action == 'quarantine'
                                        ? Icons.shield
                                        : m.category == 'otp'
                                        ? Icons.password
                                        : Icons.chat_bubble_outline,
                                    size: 20,
                                  ),
                                  const SizedBox(width: 10),
                                  Expanded(
                                    child: Text(
                                      m.sender,
                                      style: Theme.of(context)
                                          .textTheme
                                          .titleMedium,
                                    ),
                                  ),
                                  Text(
                                    '${date.month}/${date.day}',
                                    style: Theme.of(context)
                                        .textTheme
                                        .labelSmall,
                                  ),
                                ],
                              ),
                              const SizedBox(height: 10),
                              Text(
                                r.hidePreviews ? '短信内容已隐藏，点击查看' : m.body,
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                              ),
                              const SizedBox(height: 10),
                              Wrap(
                                spacing: 12,
                                runSpacing: 6,
                                children: [
                                  Text(
                                    categories[m.category]!,
                                    style: Theme.of(context)
                                        .textTheme
                                        .labelMedium,
                                  ),
                                  if (m.slot >= 0)
                                    Text(
                                      'SIM ${m.slot + 1}',
                                      style: Theme.of(context)
                                          .textTheme
                                          .labelMedium,
                                    ),
                                  Text(
                                    m.syncState == 'acked'
                                        ? '已同步'
                                        : m.syncState == 'rejected'
                                        ? '上传被拒绝 · 本地保留'
                                        : '已保存在本机',
                                    style: Theme.of(context)
                                        .textTheme
                                        .labelSmall,
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                      ),
                    );
                  },
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}

class DetailPage extends ConsumerWidget {
  final String id;
  const DetailPage({super.key, required this.id});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final r = watchRepository(ref);
    return Scaffold(
      appBar: AppBar(title: const Text('短信详情')),
      body: FutureBuilder<SmsMessage?>(
        future: r.db.find(id),
        builder: (context, snapshot) {
          final m = snapshot.data;
          if (m == null) return const Center(child: Text('正在读取消息或消息已清理'));
          return ListView(
            padding: const EdgeInsets.all(24),
            children: [
              Text(m.sender, style: Theme.of(context).textTheme.headlineSmall),
              const SizedBox(height: 8),
              Text(
                '${DateTime.fromMillisecondsSinceEpoch(m.receivedAt).toLocal()}${m.slot >= 0 ? ' · SIM ${m.slot + 1}' : ''}',
              ),
              const SizedBox(height: 24),
              SelectableText(
                m.body,
                style: Theme.of(context).textTheme.bodyLarge,
              ),
              const SizedBox(height: 24),
              const Divider(),
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.label_outline),
                title: Text(categories[m.category]!),
                subtitle: Text(
                  '置信度 ${(m.confidence * 100).toStringAsFixed(1)}% · 风险 ${(m.risk * 100).toStringAsFixed(1)}%\n${m.needsReview ? '模型建议人工复核' : '模型已返回结果'}',
                ),
              ),
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.policy_outlined),
                title: Text(m.action == 'quarantine' ? '已隔离' : '正常保留'),
                subtitle: Text(m.reason),
              ),
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('分类来源'),
                subtitle: Text(
                  '${switch (m.classificationSource) {
                    'llm' => 'AI / LLM',
                    'privatesms' => '轻量分类器',
                    '' => '尚未返回来源',
                    final source => source,
                  }}${m.llmPending ? ' · 等待 LLM 复核' : ''}',
                ),
              ),
              if (m.primaryClassification case final primary?)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('轻量模型原始结果'),
                  subtitle: Text(
                    '${categories[primary['category']] ?? primary['category']} · ${primary['model_version']}\n'
                    '置信度 ${((primary['confidence'] as num) * 100).toStringAsFixed(1)}% · '
                    '风险 ${((primary['spam_score'] as num) * 100).toStringAsFixed(1)}%\n'
                    '${primary['needs_review'] == true ? '模型建议人工复核' : '模型已返回结果'}',
                  ),
                ),
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('模型版本'),
                subtitle: Text(
                  m.modelVersion.isEmpty ? '尚未分类' : m.modelVersion,
                ),
              ),
              if (m.action == 'quarantine')
                FilledButton.icon(
                  onPressed: () => perform(context, () async {
                    await r.restore(id);
                    if (context.mounted) {
                      ScaffoldMessenger.of(
                        context,
                      ).showSnackBar(const SnackBar(content: Text('已恢复到收件箱')));
                    }
                  }),
                  icon: const Icon(Icons.restore),
                  label: const Text('恢复到收件箱'),
                ),
              OutlinedButton.icon(
                onPressed: () =>
                    perform(context, () => r.archive(id, !m.archived)),
                icon: Icon(
                  m.archived
                      ? Icons.unarchive_outlined
                      : Icons.archive_outlined,
                ),
                label: Text(m.archived ? '取消归档' : '归档消息'),
              ),
              OutlinedButton.icon(
                onPressed: () async {
                  final selected = await showDialog<String>(
                    context: context,
                    builder: (c) => SimpleDialog(
                      title: const Text('正确的分类是什么？'),
                      children: [
                        for (final category in categories.entries)
                          SimpleDialogOption(
                            onPressed: () => Navigator.pop(c, category.key),
                            child: Text(category.value),
                          ),
                      ],
                    ),
                  );
                  if (selected != null &&
                      context.mounted &&
                      await confirm(
                        context,
                        '保存纠错',
                        '纠错保存在本地并同步到你配对的服务器，不修改当前模型；不会自动用于训练。',
                      )) {
                    await r.feedback(id, selected);
                    if (context.mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('纠错已保存，等待审核')),
                      );
                    }
                  }
                },
                icon: const Icon(Icons.edit_outlined),
                label: const Text('纠正分类'),
              ),
            ],
          );
        },
      ),
    );
  }
}
