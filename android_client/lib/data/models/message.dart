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
      syncState;
  final int receivedAt, subscriptionId, slot;
  final double confidence, risk;
  final bool needsReview, archived;
  const SmsMessage({
    required this.id,
    required this.sender,
    required this.body,
    required this.receivedAt,
    this.subscriptionId = -1,
    this.slot = -1,
    this.category = 'uncertain',
    this.action = 'allow',
    this.reason = '等待分类',
    this.modelVersion = '',
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
    return SmsMessage(
      id: j['message_id'] as String,
      sender: j['sender'] as String,
      body: j['body'] as String,
      receivedAt: (j['received_at'] as num).toInt(),
      subscriptionId: (j['subscription_id'] as num? ?? -1).toInt(),
      slot: (j['slot'] as num? ?? -1).toInt(),
      category: category,
      action: action,
      reason: j['reason'] as String? ?? '等待分类',
      modelVersion: j['model_version'] as String? ?? '',
      syncState: j['sync_state'] as String? ?? 'pending',
      confidence: confidence,
      risk: risk,
      needsReview: j['needs_review'] as bool? ?? true,
      archived: j['archived'] as bool? ?? false,
    );
  }
  Map<String, dynamic> toJson() => {
    'message_id': id,
    'sender': sender,
    'body': body,
    'received_at': receivedAt,
    'subscription_id': subscriptionId,
    'slot': slot,
    'category': category,
    'action': action,
    'reason': reason,
    'model_version': modelVersion,
    'sync_state': syncState,
    'confidence': confidence,
    'risk': risk,
    'needs_review': needsReview,
    'archived': archived,
  };
}
