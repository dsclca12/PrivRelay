from __future__ import annotations

import re


# Replace only a short value explicitly introduced as a verification code. In
# particular, generic numbers (amounts, dates, phone suffixes) are preserved.
_OTP_VALUE = re.compile(
    r"(?P<label>(?:短信)?(?:验证码|校验码|动态码|登录码|安全码|短信码|动态口令|动态密码|一次性密码))"
    r"(?P<join>[^\S\r\n]*(?:(?:为|是)[^\S\r\n]*)?(?:(?:请)?(?:输入|填写|填入|使用)[^\S\r\n]*)?[:：=,，、]?[^\S\r\n]*)"
    r"(?P<value>(?:[A-Za-z0-9]{4,8}|[A-Za-z0-9]{2,4}[ -][A-Za-z0-9]{2,4}))(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_FULLWIDTH_ALNUM = str.maketrans({
    **{chr(codepoint): chr(codepoint - 0xFEE0) for codepoint in range(0xFF10, 0xFF1A)},
    **{chr(codepoint): chr(codepoint - 0xFEE0) for codepoint in range(0xFF21, 0xFF3B)},
    **{chr(codepoint): chr(codepoint - 0xFEE0) for codepoint in range(0xFF41, 0xFF5B)},
})


def normalize_verification_codes(text: str) -> str:
    """Hide explicitly labeled OTP values while retaining all other context."""
    canonical = text.translate(_FULLWIDTH_ALNUM)
    return _OTP_VALUE.sub(lambda match: match.group("label") + "内容", canonical)


def normalize_texts(texts):
    """Scikit-learn compatible batch transform."""
    return [normalize_verification_codes(text) for text in texts]
