from privatesms.text_normalization import normalize_verification_codes


def test_verification_code_value_is_ignored():
    assert normalize_verification_codes("您的验证码为 123456，请勿泄露") == normalize_verification_codes(
        "您的验证码为 998877，请勿泄露"
    )
    assert normalize_verification_codes("登录码: AB12CD") == "登录码内容"
    assert normalize_verification_codes("校验码 123 456") == "校验码内容"
    assert normalize_verification_codes("您的动态口令为 940217") == "您的动态口令内容"


def test_unlabeled_numbers_and_context_are_preserved():
    message = "尾号1234消费288.00元，明天12:30联系我"
    assert normalize_verification_codes(message) == message
    assert normalize_verification_codes("短信验证码获取失败，请重试") == "短信验证码获取失败，请重试"


def test_only_code_token_is_replaced():
    assert normalize_verification_codes("验证码 123456，订单金额 88 元") == "验证码内容，订单金额 88 元"


def test_common_code_punctuation_and_instruction_forms_are_normalized():
    variants = [
        "验证码为：123456",
        "您的验证码是：123456",
        "验证码请填写：123456",
        "验证码请填写123456",
        "验证码：１２３４５６",
        "验证码，123456",
        "验证码为:123456",
        "验证码是：123456",
    ]
    assert all("123456" not in normalize_verification_codes(text) for text in variants)
    assert all("验证码内容" in normalize_verification_codes(text) for text in variants)


def test_full_width_normalization_preserves_non_otp_numbers():
    assert normalize_verification_codes("尾号１２３４消费２８８元，明天１２:３０联系") == "尾号1234消费288元，明天12:30联系"
    assert normalize_verification_codes("验证码获取失败，账单金额８８元") == "验证码获取失败，账单金额88元"


def test_code_match_does_not_cross_sms_line_breaks():
    message = "验证码\n123456"
    assert normalize_verification_codes(message) == message
