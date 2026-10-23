import 'package:flutter/material.dart' as m;

const _english = <String, String>{
  '默认短信应用': 'Default SMS app',
  'PrivRelay 当前管理系统短信收件箱': 'PrivRelay currently manages the system SMS inbox.',
  '由 Android 系统管理短信；设为默认应用后可接收 SMS_DELIVER 并写入系统收件箱。': 'Android currently manages SMS. Set PrivRelay as default to receive delivered SMS and write to the system inbox.',
  '设为默认': 'Set as default',
  '未更改默认短信应用': 'The default SMS app was not changed.',
  '可在设置中选择申请默认短信角色；未切换时仅管理本应用消息，不能关闭系统短信应用的通知。': 'You can request the default SMS role in Settings. Until then, PrivRelay manages only its own messages and cannot turn off system SMS notifications.',
  '确认发送': 'Review and send',
  '正在发送…': 'Sending…',
  '仅分类，正常保留': 'Classified only; kept in the inbox',
  '重要短信保护': 'Protected as an important message',
  '白名单保护': 'Protected by the allowlist',
  '分类不确定，正常保留': 'Classification was uncertain; kept in the inbox',
  '用户黑名单规则': 'Matched a user blocklist rule',
  '分类不可用，正常保留': 'Classification unavailable; kept in the inbox',
  '上游拦截决策不可用，正常保留': 'Classifier decision unavailable; kept in the inbox',
  'uncalibrated_category_allow': 'Uncalibrated category; allowed',
  'below_safe_block_gate': 'Below the safe blocking threshold',
  'personal': 'Personal',
  'otp': 'Verification code',
  'service': 'Service notice',
  'transaction': 'Transaction',
  'marketing': 'Marketing',
  'suspicious': 'Suspicious',
  'uncertain': 'Uncertain',
  '无法打开受保护的本地数据。请保留应用数据，稍后重试。':
      'Could not open protected local data. Keep app data and try again later.',
  '重试': 'Retry',
  'PrivRelay 已锁定': 'PrivRelay is locked',
  '取消': 'Cancel',
  '确认': 'Confirm',
  '重新配对': 'Pair again',
  '短信，留在你的掌控中': 'Your messages, under your control',
  'PrivRelay 先将短信加密保存在本机。只有配对你确认的自托管服务器后，才会上传用于分类和跨设备同步。': 'PrivRelay first encrypts messages on this device. They are uploaded for classification and sync only after you pair a self-hosted server you trust.',
  '本地加密': 'Encrypted on this device',
  '不接入第三方统计，不在诊断中记录正文。':
      'No third-party analytics. Diagnostics never include message text.',
  '自托管分类': 'Self-hosted classification',
  '短信正文在设备上端到端加密后同步，服务器不能读取或分类；当前客户端暂不提供自动分类。': 'Message text is end-to-end encrypted on this device before sync, so the server cannot read or classify it. Automatic classification is not available in this client yet.',
  '关于拦截': 'About filtering',
  '本版不是默认短信应用，只隔离本应用消息；不能阻止系统短信应用的通知。': 'This is not the default SMS app. It only quarantines messages in this app and cannot suppress notifications from your system SMS app.',
  '继续设置服务器': 'Set up a server',
  '先在本地使用': 'Use locally for now',
  '拒绝权限也能查看已有消息。不会请求读取系统历史短信。': 'You can view existing messages without granting permission. PrivRelay will not request access to SMS history.',
  '配对成功': 'Paired successfully',
  '连接你的服务器': 'Connect your server',
  '扫码绑定服务器': 'Scan to pair with a server',
  '开发测试：允许 HTTP': 'Development: allow HTTP',
  '仅用于 ADB 回环或受控测试网络': 'Only for ADB loopback or a controlled test network',
  '采集与隐私': 'Collection and privacy',
  '接收新短信': 'Receive new SMS',
  '通知权限': 'Notification permission',
  '新短信通知只显示通用提示，锁屏不显示正文': 'New message notifications are generic and never show message text on the lock screen',
  '所有正常保留的短信': 'All messages kept in the inbox',
  '重要与风险消息（含待确定）': 'Important and risk messages (including uncertain)',
  '关闭本应用提醒': 'Turn off app notifications',
  '隐藏列表正文': 'Hide message previews',
  '收件箱与拦截箱只显示发件人，进入详情后查看正文': 'The inbox and quarantine show senders only. Open a message to view its text.',
  '防止截屏与录屏': 'Block screenshots and screen recording',
  '保护应用全部页面，并隐藏最近任务中的画面':
      'Protect every screen and hide the app preview in Recents',
  '应用锁': 'App lock',
  '启动和返回应用时验证设备锁屏密码；后台收信与同步继续运行': 'Verify your device screen lock when opening or returning to the app. Background receiving and sync continue.',
  '本地自动保留期限': 'Local retention period',
  '永久保留（默认）': 'Keep forever (default)',
  '30 天': '30 days',
  '90 天': '90 days',
  '365 天': '365 days',
  '清理仅影响本机缓存；服务器仍保留历史。重新配对或远程更新时可能再次拉取。': 'Cleanup affects this device only. The server keeps its history, which may be downloaded again after pairing or a remote update.',
  '后台补发': 'Background retry',
  '使用系统任务调度；省电限制下可能延迟。关闭后仍会保存新短信。': 'Uses system scheduling and may be delayed by battery restrictions. New messages are still saved when disabled.',
  '前台实时同步（可选）': 'Foreground sync (optional)',
  '显示持续通知并提高后台补发及时性；会增加耗电，系统仍可能限制运行。': 'Shows a persistent notification and can improve background delivery. It uses more battery and may still be limited by Android.',
  'AI / LLM 自动分类': 'AI / LLM classification',
  '配置 OpenAI 兼容 API、复核与自动隔离':
      'Configure an OpenAI-compatible API, review, and automatic quarantine',
  '过滤规则': 'Filtering rules',
  '仅分类、智能过滤与主动授权的隔离':
      'Classification, smart filtering, and explicitly authorized quarantine',
  '设备管理': 'Device management',
  '同步诊断': 'Sync diagnostics',
  '清理已上传记录': 'Clear uploaded messages',
  '保留未上传及有待处理操作的消息':
      'Keep messages that have not uploaded or have pending actions',
  '解除本机配对': 'Unpair this device',
  '当前状态': 'Current status',
  '待上传短信': 'Messages waiting to upload',
  '待同步操作': 'Actions waiting to sync',
  '上传被拒绝（本地保留）': 'Upload rejected (kept locally)',
  '最近确认': 'Last acknowledgement',
  '最近错误（不含短信内容）': 'Last error (message text excluded)',
  '接收权限': 'SMS permission',
  '原生暂存': 'Native queue',
  '立即同步': 'Sync now',
  '检查服务健康': 'Check server health',
  '仅分类': 'Classify only',
  '智能过滤': 'Smart filtering',
  '自动隔离': 'Automatic quarantine',
  '规则已保存，将用于新消息': 'Rules saved. They apply to new messages.',
  '保存规则': 'Save rules',
  '本机标识': 'This device ID',
  '未连接服务器，请先配对': 'Not connected to a server. Pair first.',
  '查看已归档消息': 'View archived messages',
  '全部': 'All',
  '加载更多': 'Load more',
  '短信详情': 'Message details',
  '正在读取消息或消息已清理': 'Loading message or message has been removed',
  '分类来源': 'Classification source',
  '轻量模型原始结果': 'Original lightweight model result',
  '模型版本': 'Model version',
  '已恢复到收件箱': 'Restored to inbox',
  '恢复到收件箱': 'Restore to inbox',
  '正确的分类是什么？': 'What is the correct category?',
  '纠错已保存，等待审核': 'Correction saved and awaiting review',
  '纠正分类': 'Correct category',
  '扫码绑定': 'Scan to pair',
  '无法启动相机，请在系统设置中允许相机权限后重试；也可返回手动输入配对码。': 'Could not start the camera. Allow camera access in system settings and try again, or go back and enter the pairing code manually.',
  '请先配对并连接服务器': 'Pair with and connect to a server first',
  '当前 Android 使用端到端加密同步，服务器无法读取或分类密文短信。以下配置只对旧版明文客户端生效，不会对本机加密消息启用 AI 分类或自动隔离。': 'This Android client syncs with end-to-end encryption, so the server cannot read or classify message text. These settings only apply to legacy plaintext clients and do not enable AI classification or automatic quarantine for encrypted messages on this device.',
  '关闭 LLM，使用轻量分类器': 'Disable LLM and use the lightweight classifier',
  '轻量模型失败或需复核时使用 LLM':
      'Use the LLM when the lightweight model fails or requests review',
  '直接使用 LLM 分类': 'Classify directly with the LLM',
  '清除已保存密钥': 'Clear saved key',
  '允许 HTTP': 'Allow HTTP',
  '仅限可信本机或内网': 'Trusted local or private networks only',
  '允许 LLM 自动隔离': 'Allow automatic LLM quarantine',
  '仅营销和可疑短信；还需启用过滤或拦截模式': 'Marketing and suspicious messages only; filtering or quarantine mode must also be enabled',
  '两项分数均需达到阈值，模型分数未经校准。验证码、交易、安全内容、白名单和人工恢复优先保护；错误时正常保留。': 'Both scores must meet the threshold; model scores are not calibrated. OTPs, transactions, security messages, allowlisted senders, and manually restored messages are protected. Errors keep messages in the inbox.',
  '默认地址、模型和密钥为空，不会自动连接服务。配置用于新消息与待分类消息，不回溯全部历史。': 'The address, model, and key are blank by default, so no service is contacted. Settings apply to new and unclassified messages, not all history.',
  '保存 AI 配置': 'Save AI settings',
  '测试已保存配置（合成短信）': 'Test saved settings (synthetic SMS)',
  'PrivRelay · Android MVP 0.1\n可选申请 Android 默认短信角色；未切换时系统短信应用仍负责短信通知。SMS 正文端到端加密同步，MMS 附件暂不跨设备同步。分类失败时保留消息。': 'PrivRelay · Android MVP 0.1\nYou can request Android’s default SMS role. Until then, the system SMS app handles SMS notifications. SMS text syncs end-to-end encrypted; MMS attachments do not sync between devices yet. Classification failures keep messages in the inbox.',
  '系统强行停止应用后 Android 会暂停广播和任务，需手动重新打开。普通后台进程回收由持久化暂存和 WorkManager 恢复。': 'After Android force-stops the app, broadcasts and tasks pause until you open it again. Persistent storage and WorkManager recover from ordinary background process termination.',
  '服务在线 · 分类器': 'Server online · classifier',
  '验证码': 'One-time password',
  '服务通知': 'Service notice',
  '交易通知': 'Transaction notice',
  '营销短信': 'Marketing',
  '可疑短信': 'Suspicious',
  '待确认': 'Uncertain',
  '个人短信': 'Personal',
  '白名单优先。验证码、交易通知、疑似安全验证码内容和分类失败消息不自动隔离。未校准的模型只提供分类建议。': 'Allowlisted senders take priority. OTPs, transaction notices, suspected security codes, and messages that failed classification are never quarantined automatically. Uncalibrated models only provide suggestions.',
  '没有匹配的短信': 'No matching messages',
  '这里暂时没有被隔离的消息': 'Nothing is quarantined right now',
  '等待你的第一条短信': 'Waiting for your first message',
  '隔离的消息始终可以恢复': 'Quarantined messages can always be restored',
  '新短信会先保存在本机，联网后自动同步':
      'New messages are saved on this device and sync when online',
  '请在设置中允许接收新短信': 'Allow SMS receiving in Settings',
  '短信内容已隐藏，点击查看': 'Message text hidden. Tap to view.',
  '已同步': 'Synced',
  '上传被拒绝 · 本地保留': 'Upload rejected · kept locally',
  '已保存在本机': 'Saved on this device',
  '尚未返回来源': 'Source not reported',
  '等待 LLM 复核': 'Waiting for LLM review',
  '尚未分类': 'Not classified yet',
  '保存纠错': 'Save correction',
  '纠错保存在本地并同步到你配对的服务器，不修改当前模型；不会自动用于训练。': 'The correction is saved locally and synced to your paired server. It does not change the current model and is not used for training automatically.',
  '确认同步目的地': 'Confirm sync destination',
  '端到端加密口令（至少 12 个字符）':
      'End-to-end encryption passphrase (at least 12 characters)',
  '在每台授权设备上输入相同口令；口令不会发送到服务器。': 'Enter the same passphrase on each authorized device. It is never sent to the server.',
  '服务器地址': 'Server address',
  '一次性配对码': 'One-time pairing code',
  '显示语言 / Display language': 'Display language',
  '新短信提醒': 'New message notifications',
  '启用本地自动清理？': 'Enable automatic local cleanup?',
  '立即及每次同步时，清理期限外已上传的正常消息。隔离消息、未上传记录与待处理操作保留；服务器记录不删除。': 'Immediately and during each sync, remove uploaded inbox messages older than the retention period. Quarantined messages, unsent messages, and messages with pending actions are kept. Server records are not deleted.',
  '清理本地记录？': 'Clear local records?',
  '仅删除本机已上传且没有待处理操作的记录。服务器记录保留。': 'Only uploaded records on this device with no pending actions will be deleted. Server records are kept.',
  '解除本机配对？': 'Unpair this device?',
  '停止向服务器上传，保留本地消息。需要撤销远程访问请先在设备管理中撤销本机。': 'Stop uploading to the server while keeping local messages. To revoke remote access, revoke this device in Device Management first.',
  '分类方式': 'Classification mode',
  'API 基础地址（通常以 /v1 结尾）': 'API base URL (usually ends in /v1)',
  '模型名称': 'Model name',
  'API Key（已保存，留空保留）': 'API key (saved; leave blank to keep it)',
  'API Key（免鉴权服务可留空）':
      'API key (leave blank if authentication is not required)',
  '搜索发件人或正文': 'Search senders or message text',
  '搜索发送方或正文': 'Search sender or message text',
  '同步': 'Sync',
  '诊断': 'Diagnostics',
  '收件箱': 'Inbox',
  '拦截箱': 'Quarantine',
  '设置': 'Settings',
  '跟随系统 / System default': 'System default',
  '简体中文': 'Simplified Chinese',
  '工作模式': 'Operating mode',
  '白名单（完整发件人，每行一个）': 'Allowlist (exact sender, one per line)',
  '黑名单（完整发件人，每行一个）': 'Blocklist (exact sender, one per line)',
  '取消归档': 'Unarchive',
  '归档消息': 'Archive message',
  '撤销授权': 'Revoke access',
  '已撤销': 'Revoked',
  'AI 配置已保存': 'AI settings saved',
  '已隔离': 'Quarantined',
  '正常保留': 'Kept in inbox',
  '允许': 'Allowed',
  '待分类': 'Awaiting classification',
  '配对': 'Paired',
  '本地模式': 'Local mode',
  '同步完成': 'Sync complete',
  '等待同步': 'Waiting to sync',
  '等待重试': 'Waiting to retry',
  '已授权': 'Allowed',
  '未授权': 'Not allowed',
  '未授权，已有消息仍可查看': 'Not allowed; existing messages remain available',
  '尚无确认': 'No acknowledgement yet',
  '暂无错误': 'No errors',
  '未完成验证，请重试': 'Authentication was not completed. Try again.',
  '未完成身份验证，请先为设备设置锁屏密码后重试': 'Authentication was not completed. Set a device screen lock and try again.',
  '请等待当前同步完成': 'Wait for the current sync to finish.',
  '后台同步正在进行，请稍后重试': 'Background sync is in progress. Try again shortly.',
  '请先设置至少 12 个可见 ASCII 字符的端到端加密口令': 'Set an end-to-end encryption passphrase with at least 12 visible ASCII characters first.',
  '切换服务器前请先处理待发送数据并清理本地记录': 'Process pending uploads and clear local records before switching servers.',
  '共享加密口令不匹配，未上传或迁移短信；请输入其他设备使用的相同口令': 'The shared encryption passphrase does not match. No messages were uploaded or migrated. Enter the same passphrase used on your other devices.',
  '端到端加密尚未配置': 'End-to-end encryption is not configured.',
  '请等待同步完成': 'Wait for sync to finish.',
  '请先开启后台补发': 'Enable background retry first.',
  '需要允许通知，才能启用持续显示的前台同步':
      'Allow notifications to enable persistent foreground sync.',
  '请先关闭应用锁，再关闭防截屏保护':
      'Turn off the app lock before disabling screenshot protection.',
  '请填写接口地址和模型名称': 'Enter an API address and model name.',
  '正在同步，请稍后重试绑定': 'Sync is in progress. Try pairing again shortly.',
  '操作未完成，请检查连接后重试':
      'The action did not complete. Check your connection and try again.',
  '处理暂未完成，记录已保留': 'Processing did not finish. Your messages have been kept.',
  '导入系统短信历史': 'Import SMS history',
  '仅在你点击后申请读取权限；每次最多导入最近 5,000 条，重复导入会自动去重。': 'SMS read access is requested only when you tap this option. Each import reads up to the 5,000 most recent inbox messages and safely skips duplicates.',
  '短信读取权限未授予，未导入任何数据':
      'SMS read permission was not granted. Nothing was imported.',
  '已允许接收新短信': 'Permission to receive new SMS granted',
  '允许接收新短信': 'Allow receiving new SMS',
  '正在验证…': 'Verifying…',
  '使用设备密码解锁': 'Unlock with device credentials',
  '用户恢复': 'Restored by user',
  '二维码内容过长': 'QR code content is too long',
  '请扫描 PrivRelay 设备中心生成的二维码':
      'Scan a QR code generated by the PrivRelay device center',
  '不是支持的 PrivRelay 配对二维码': 'This is not a supported PrivRelay pairing QR code',
  '配对码格式无效': 'Invalid pairing code format',
  '二维码已过期，请在设备中心重新生成':
      'QR code expired. Generate a new one in the device center.',
  '请输入 HTTPS 服务器地址（不含路径、账号或参数）': 'Enter an HTTPS server address without a path, credentials, or query parameters.',
  '需要重新配对': 'Pairing required again',
  '端到端加密口令至少 12 个字符，且只能包含可见 ASCII 字符': 'The end-to-end encryption passphrase must contain at least 12 visible ASCII characters.',
  '请输入一次性配对码': 'Enter the one-time pairing code',
  'Android 手机': 'Android phone',
  '服务器未提供加密参数': 'The server did not provide encryption parameters',
  '连接不可用': 'connection unavailable',
  '已配对': 'Paired',
  '正在同步': 'Syncing',
  '服务器仍有未迁移的旧记录，已保留；请使用保存这些记录的设备完成迁移': 'Unmigrated legacy records remain on the server and were kept. Use the device that holds those records to finish migration.',
  '网络暂不可用，消息已保存在本机': 'Network unavailable. Messages were saved on this device.',
  '删除确认身份或版本无效': 'Invalid deletion confirmation identity or version',
  '密文消息身份或版本不匹配': 'Encrypted message identity or version mismatch',
  '操作未收到逐消息确认': 'No per-message acknowledgement was received',
  '操作重放确认身份不匹配': 'Operation replay acknowledgement identity mismatch',
  '等待分类': 'Awaiting classification',
  '二维码已过期，请重新生成': 'QR code expired. Generate a new one.',
  '配对并开始同步': 'Pair and start syncing',
  '正常': 'Available',
  '暂不可用（正常保留消息）': 'Temporarily unavailable (messages are kept in the inbox)',
  '启用自动隔离？': 'Enable automatic quarantine?',
  '只隔离本应用消息，不删除短信；验证码与交易消息优先保护。当前模型未校准，单凭模型分数不会触发自动隔离，黑名单可生效。': 'Only messages in this app are quarantined; SMS are never deleted. OTP and transaction messages are protected. The current model is uncalibrated, so model scores alone will not trigger quarantine. Blocklist rules remain active.',
  '模型已返回结果': 'Model returned a result',
  '轻量分类器': 'Lightweight classifier',
  '模型建议人工复核': 'The model recommends human review',
  '扫描 Web 控制台「设备中心」的二维码，随后确认同步服务器。': 'Scan a QR code from the Web console’s Device Center, then confirm the sync server.',
  '确认 AI 处理目的地': 'Confirm AI processing destination',
  '同时允许符合条件的营销和可疑消息进入可恢复的隔离箱。': 'Also allow eligible marketing and suspicious messages into the recoverable quarantine.',
  '撤回授权': 'Withdraw authorization',
  '已撤回，后续导出将排除此样本':
      'Authorization withdrawn. Future exports will exclude this sample.',
  '短信发送尚未配置': 'SMS sending is not configured',
  '发送短信': 'Send SMS',
  '收件号码': 'Recipient phone number',
  '短信正文': 'Message text',
  '继续': 'Continue',
  '确认发送短信？': 'Confirm sending this SMS?',
  '彩信暂无可显示的附件': 'This MMS has no displayable attachments.',
  '部分彩信附件超过 2 MiB 同步上限，已保留在系统短信存储中。': 'Some MMS attachments exceed the 2 MiB sync limit and remain in Android system storage.',
  '已包含在端到端加密同步中': 'Included in end-to-end encrypted sync',
  'bytes': 'bytes',
  '请输入收件号码和短信正文': 'Enter a recipient number and message text.',
  '收件号码或短信正文超出长度限制':
      'Recipient number or message text exceeds the length limit.',
  '短信发送权限未授予': 'SMS sending permission was not granted.',
  '需单独授予短信发送权限；每次发送前会显示号码、正文和确认。运营商可能收费。': 'SMS permission is requested separately. The recipient and message are shown for confirmation before each send. Carrier charges may apply.',
  '正在配对…': 'Pairing…',
  ' · 本机': ' · This device',
  '撤销设备？': 'Revoke device access?',
  '该设备将无法继续读取或上传短信，本地历史保留。': 'This device will no longer be able to read or upload messages. Local history will remain.',
};

String localizeText(m.BuildContext context, String value) =>
    _translate(value, m.Localizations.localeOf(context).languageCode);

String _translate(String value, String language) {
  if (language != 'en') return value;
  final exact = _english[value];
  if (exact != null) return exact;
  final classifierReason = RegExp(
    r'^PrivateSMS-Classifier: (risk_category|review_required):([a-z_]+)$',
  ).firstMatch(value);
  if (classifierReason != null) {
    final category = _english[classifierReason[2]] ?? classifierReason[2];
    return classifierReason[1] == 'risk_category'
        ? 'Classified as $category with elevated risk'
        : 'Needs review: $category';
  }
  if (value.startsWith('LLM: ')) {
    return 'LLM: ${value.substring(5)}';
  }
  final confidence = RegExp(
    r'^置信度 ([0-9.]+)% · 风险 ([0-9.]+)%\n(.*)$',
    dotAll: true,
  ).firstMatch(value);
  if (confidence != null) {
    return 'Confidence ${confidence[1]}% · Risk ${confidence[2]}%\n${_english[confidence[3]] ?? confidence[3]}';
  }
  final threshold = RegExp(r'^阈值 (.+)$').firstMatch(value);
  if (threshold != null) return 'Threshold ${threshold[1]}';
  final minScore = RegExp(r'^最低置信度与风险分数：(.+)$').firstMatch(value);
  if (minScore != null) {
    return 'Minimum confidence and risk scores: ${minScore[1]}';
  }
  if (value.startsWith('服务在线 · 分类器')) {
    return value.contains('正常')
        ? 'Server online · classifier available'
        : 'Server online · classifier unavailable; messages remain in the inbox';
  }
  final requestFailure = RegExp(r'^服务请求失败（(\d+)），本地记录已保留$').firstMatch(value);
  if (requestFailure != null) {
    return 'Service request failed (${requestFailure[1]}). The local message was kept.';
  }
  final rejected = RegExp(r'^上传被服务器拒绝（(\d+)），消息仍在本机，请检查服务接口及消息长度$')
      .firstMatch(value);
  if (rejected != null) {
    return 'The server rejected the upload (${rejected[1]}). The message remains on this device; check the API and message length.';
  }
  final pairingFailed = RegExp(r'^配对失败（(.*)）$').firstMatch(value);
  if (pairingFailed != null) return 'Pairing failed (${pairingFailed[1]})';
  final imported = RegExp(r'^已处理 (\d+) 条历史短信$').firstMatch(value);
  if (imported != null) {
    return 'Processed ${imported[1]} historical messages';
  }
  final sendConfirm = RegExp(
    r'^将通过系统短信服务向 (.+) 发送以下内容，可能产生运营商费用。请确认号码和正文无误：\n\n(.*)$',
    dotAll: true,
  ).firstMatch(value);
  if (sendConfirm != null) {
    return 'Send the following message to ${sendConfirm[1]} using the system SMS service? Carrier charges may apply. Confirm the recipient and text:\n\n${sendConfirm[2]}';
  }
  final sent = RegExp(r'^已提交系统发送（(\d+) 段）；运营商送达状态不可用。$').firstMatch(value);
  if (sent != null) {
    return 'Submitted to Android for sending (${sent[1]} part(s)); carrier delivery status is unavailable.';
  }
  final spool = RegExp(r'^(\d+) 条（启动与后台任务自动消费）$').firstMatch(value);
  if (spool != null) {
    return '${spool[1]} (consumed by startup and background tasks)';
  }
  if (value.contains(' · 等待 LLM 复核')) {
    final source = value.replaceAll(' · 等待 LLM 复核', '');
    return '${_english[source] ?? source} · Awaiting LLM review';
  }
  final permission = RegExp(r'^已授权( · 本机)?$').firstMatch(value);
  if (permission != null) {
    return permission[1] == null ? 'Allowed' : 'Allowed · This device';
  }
  final pairingTarget = RegExp(
    r'^服务器：([^\n]+)\n短信正文将使用端到端加密后同步；云端不能读取或分类正文。其他设备需要输入相同的加密口令。已有服务器明文记录会先从本机加密迁移，迁移完成后删除服务器上未迁移的旧明文记录。$',
    dotAll: true,
  ).firstMatch(value);
  if (pairingTarget != null) {
    return 'Server: ${pairingTarget[1]}\nMessage text will be end-to-end encrypted before sync; the server cannot read or classify it. Other devices must use the same encryption passphrase. Existing server plaintext messages will first be encrypted from this device, then the remaining legacy plaintext will be deleted after migration completes.';
  }
  final aiDestination = RegExp(
    r'^将向 (.+) 发送短信发件人和正文用于分类。(.*)$',
    dotAll: true,
  ).firstMatch(value);
  if (aiDestination != null) {
    final extra = aiDestination[2]!.isEmpty
        ? ''
        : '\n${_english[aiDestination[2]] ?? aiDestination[2]}';
    return 'The sender and message text will be sent to ${aiDestination[1]} for classification.$extra';
  }
  final aiResult = RegExp(r'^连接成功 · (.+) · (.+)（合成测试，不保存为短信）$')
      .firstMatch(value);
  if (aiResult != null) {
    return 'Connected · ${aiResult[1]} · ${_english[aiResult[2]] ?? aiResult[2]} (synthetic sample; not saved as a message)';
  }
  final primary = RegExp(
    r'^(.+) · (.+)\n置信度 ([0-9.]+)% · 风险 ([0-9.]+)%\n(.*)$',
    dotAll: true,
  ).firstMatch(value);
  if (primary != null) {
    return '${_english[primary[1]] ?? primary[1]} · ${primary[2]}\nConfidence ${primary[3]}% · Risk ${primary[4]}%\n${_english[primary[5]] ?? primary[5]}';
  }
  final pending = RegExp(r'^(.+?) · (\d+) 条待发送$').firstMatch(value);
  if (pending != null) {
    return '${_english[pending[1]] ?? pending[1]} · ${pending[2]} pending';
  }
  return value;
}

/// Text with a translated system-language label while preserving const call sites.
class Text extends m.StatelessWidget {
  const Text(
    this.data, {
    super.key,
    this.style,
    this.strutStyle,
    this.textAlign,
    this.textDirection,
    this.locale,
    this.softWrap,
    this.overflow,
    this.textScaler,
    this.maxLines,
    this.semanticsLabel,
    this.textWidthBasis,
    this.textHeightBehavior,
    this.selectionColor,
  });

  final String data;
  final m.TextStyle? style;
  final m.StrutStyle? strutStyle;
  final m.TextAlign? textAlign;
  final m.TextDirection? textDirection;
  final m.Locale? locale;
  final bool? softWrap;
  final m.TextOverflow? overflow;
  final m.TextScaler? textScaler;
  final int? maxLines;
  final String? semanticsLabel;
  final m.TextWidthBasis? textWidthBasis;
  final m.TextHeightBehavior? textHeightBehavior;
  final m.Color? selectionColor;

  @override
  m.Widget build(m.BuildContext context) {
    return m.Text(
      localizeText(context, data),
      key: key,
      style: style,
      strutStyle: strutStyle,
      textAlign: textAlign,
      textDirection: textDirection,
      locale: locale,
      softWrap: softWrap,
      overflow: overflow,
      textScaler: textScaler,
      maxLines: maxLines,
      semanticsLabel: semanticsLabel,
      textWidthBasis: textWidthBasis,
      textHeightBehavior: textHeightBehavior,
      selectionColor: selectionColor,
    );
  }
}
