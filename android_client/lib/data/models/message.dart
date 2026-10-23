const categories = <String, String>{
  'personal': '个人短信',
  'otp': '验证码',
  'service': '服务通知',
  'transaction': '交易通知',
  'marketing': '营销短信',
  'suspicious': '可疑短信',
  'uncertain': '待确认',
};

class SmsMessage {
  final String id,
      sender,
      body,
      category,
      action,
      reason,
      modelVersion,
      classificationSource,
      correctedCategory,
      syncState;
  final int receivedAt, subscriptionId, slot, serverRevision;
  final double confidence, risk;
  final bool needsReview, llmPending, archived;
  final Map<String, dynamic>? primaryClassification;
  final List<Map<String, dynamic>> attachments;
  final String contentKind;
  final bool attachmentsTruncated;
  const SmsMessage({
    required this.id,
    required this.sender,
    required this.body,
    required this.receivedAt,
    this.subscriptionId = -1,
    this.slot = -1,
    this.serverRevision = 0,
    this.category = 'uncertain',
    this.action = 'allow',
    this.reason = '等待分类',
    this.modelVersion = '',
    this.classificationSource = '',
    this.correctedCategory = '',
    this.llmPending = false,
    this.primaryClassification,
    this.attachments = const [],
    this.contentKind = 'sms',
    this.attachmentsTruncated = false,
    this.syncState = 'pending',
    this.confidence = 0,
    this.risk = 0,
    this.needsReview = true,
    this.archived = false,
  });

  factory SmsMessage.fromJson(Map<String, dynamic> j) {
    final category = j['category'] as String? ?? 'uncertain';
    final action = j['action'] as String? ?? 'allow';
    final confidence = (j['confidence'] as num? ?? 0).toDouble();
    final risk = (j['risk'] as num? ?? 0).toDouble();
    if (!categories.containsKey(category) ||
        !['allow', 'quarantine'].contains(action) ||
        !confidence.isFinite ||
        confidence < 0 ||
        confidence > 1 ||
        !risk.isFinite ||
        risk < 0 ||
        risk > 1) {
      throw const FormatException('Invalid message contract');
    }
    final primary = j['primary_classification'];
    if (primary != null) {
      if (primary is! Map ||
          !categories.containsKey(primary['category']) ||
          primary['model_version'] is! String ||
          primary['confidence'] is! num ||
          primary['spam_score'] is! num ||
          !(primary['confidence'] as num).isFinite ||
          !(primary['spam_score'] as num).isFinite ||
          (primary['confidence'] as num) < 0 ||
          (primary['confidence'] as num) > 1 ||
          (primary['spam_score'] as num) < 0 ||
          (primary['spam_score'] as num) > 1) {
        throw const FormatException('Invalid primary classification');
      }
    }
    final rawAttachments = j['attachments'] ?? const [];
    if (rawAttachments is! List || rawAttachments.length > 100) {
      throw const FormatException('Invalid message attachments');
    }
    var attachmentBytes = 0;
    final attachments = <Map<String, dynamic>>[];
    for (final item in rawAttachments) {
      if (item is! Map ||
          item['filename'] is! String ||
          (item['filename'] as String).length > 160 ||
          item['mime_type'] is! String ||
          (item['mime_type'] as String).length > 100 ||
          item['data_base64'] is! String ||
          item['size'] is! int ||
          (item['size'] as int) < 0) {
        throw const FormatException('Invalid message attachment');
      }
      final data = item['data_base64'] as String;
      final size = item['size'] as int;
      if (data.length > 2 * 1024 * 1024 * 4 ~/ 3 + 4 ||
          !RegExp(r'^[A-Za-z0-9+/]*={0,2}$').hasMatch(data) ||
          ((data.length * 3) ~/ 4) -
                  (data.endsWith('==')
                      ? 2
                      : data.endsWith('=')
                      ? 1
                      : 0) !=
              size) {
        throw const FormatException('Invalid message attachment encoding');
      }
      attachmentBytes += size;
      if (attachmentBytes > 2 * 1024 * 1024) {
        throw const FormatException('Message attachments exceed size limit');
      }
      attachments.add(
        Map<String, dynamic>.unmodifiable(Map<String, dynamic>.from(item)),
      );
    }
    return SmsMessage(
      id: j['message_id'] as String,
      sender: j['sender'] as String,
      body: j['body'] as String,
      receivedAt: (j['received_at'] as num).toInt(),
      subscriptionId: (j['subscription_id'] as num? ?? -1).toInt(),
      slot: (j['slot'] as num? ?? -1).toInt(),
      serverRevision: (j['server_revision'] as num? ?? 0).toInt(),
      category: category,
      action: action,
      reason: j['reason'] as String? ?? '等待分类',
      modelVersion: j['model_version'] as String? ?? '',
      classificationSource: j['classification_source'] as String? ?? '',
      correctedCategory: j['corrected_category'] as String? ?? '',
      llmPending: j['llm_pending'] as bool? ?? false,
      primaryClassification: j['primary_classification'] == null
          ? null
          : Map<String, dynamic>.unmodifiable(
              j['primary_classification'] as Map,
            ),
      syncState: j['sync_state'] as String? ?? 'pending',
      confidence: confidence,
      risk: risk,
      needsReview: j['needs_review'] as bool? ?? true,
      archived: j['archived'] as bool? ?? false,
      contentKind: j['content_kind'] as String? ?? 'sms',
      attachments: List.unmodifiable(attachments),
      attachmentsTruncated: j['attachments_truncated'] as bool? ?? false,
    );
  }
  Map<String, dynamic> toJson() => {
    'message_id': id,
    'sender': sender,
    'body': body,
    'received_at': receivedAt,
    'subscription_id': subscriptionId,
    'slot': slot,
    'server_revision': serverRevision,
    'category': category,
    'action': action,
    'reason': reason,
    'model_version': modelVersion,
    'classification_source': classificationSource,
    if (correctedCategory.isNotEmpty) 'corrected_category': correctedCategory,
    'llm_pending': llmPending,
    if (primaryClassification != null)
      'primary_classification': primaryClassification,
    'sync_state': syncState,
    'confidence': confidence,
    'risk': risk,
    'needs_review': needsReview,
    'archived': archived,
    if (contentKind != 'sms') 'content_kind': contentKind,
    if (attachments.isNotEmpty) 'attachments': attachments,
    if (attachmentsTruncated) 'attachments_truncated': true,
  };
}
