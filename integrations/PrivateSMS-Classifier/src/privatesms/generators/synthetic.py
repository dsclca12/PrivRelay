from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from privatesms.text_normalization import normalize_verification_codes


CATEGORIES = ("personal", "otp", "service", "transaction", "marketing", "suspicious", "uncertain")
PROMPT_VERSION = "synthetic-sms-v2"
GENERATOR_VERSION = "0.3.0"
MAX_PER_RUN = 10
MAX_RESPONSE_BYTES = 2_000_000
MAX_COMPLETION_TOKENS = 512

SCENARIOS = {
    "personal": ("朋友日常问候", "家庭安排", "普通约见和行程沟通"),
    "otp": ("虚构应用登录验证码", "虚构网站设备验证", "虚构账号登录提醒"),
    "service": ("快递取件通知", "航班变更提醒", "运营商套餐服务通知"),
    "transaction": ("虚构银行卡消费提醒", "支付到账通知", "账单还款提醒"),
    "marketing": ("电商促销", "贷款保险营销", "会员订阅推广"),
    "suspicious": ("含虚构链接的钓鱼诱导", "冒充客服要求联系虚构号码", "冒充退款的可疑诱导"),
    "uncertain": ("服务通知和推广混合的边界案例", "语义不足以可靠分类的短消息", "可能为服务或营销的歧义消息"),
}

_URL = re.compile(r"(?i)(?:https?://|www\.)[^\s<>\]\[(){}]+")
_EMAIL = re.compile(r"(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b")
_MOBILE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_ID_CARD = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_BANK_CARD = re.compile(r"(?<!\d)\d{13,19}(?!\d)")
_OTP_INTENT = re.compile(r"登录|登陆|注册|绑定|身份|账户安全|账号安全|修改(?:账户|账号)?密码|重置(?:账户|账号)?密码|更改(?:账户|账号)?密码|支付|付款|转账|交易|设备|验证身份|开通业务|操作确认")


class GenerationError(RuntimeError):
    pass


class TeacherResponseError(GenerationError):
    def __init__(self, message: str, usage: dict | None = None):
        super().__init__(message)
        self.usage = usage or {}


def _require_config() -> tuple[str, str, str, float, float]:
    base = os.getenv("PRIVATESMS_TEACHER_BASE_URL", "").strip().rstrip("/")
    model = os.getenv("PRIVATESMS_TEACHER_MODEL", "").strip()
    key = os.getenv("PRIVATESMS_TEACHER_API_KEY", "").strip()
    in_price = os.getenv("PRIVATESMS_INPUT_PRICE_PER_1M", "").strip()
    out_price = os.getenv("PRIVATESMS_OUTPUT_PRICE_PER_1M", "").strip()
    if not base or not model or not key or not in_price or not out_price:
        raise GenerationError("Set teacher base URL, model, API key, and both per-million token prices in environment variables")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme != "https" or not parsed.netloc:
        raise GenerationError("Teacher base URL must use HTTPS")
    try:
        input_price = float(in_price)
        output_price = float(out_price)
        if not math.isfinite(input_price) or not math.isfinite(output_price) or input_price < 0 or output_price < 0:
            raise ValueError("token prices must be finite and non-negative")
        return base, model, key, input_price, output_price
    except ValueError as exc:
        raise GenerationError("Token prices must be finite, non-negative numbers") from exc


def _request(
    prompt: str,
    config: tuple[str, str, str, float, float],
    *,
    system_message: str = "你是中文短信合成数据工具。仅输出 JSON 对象，不解释，不添加其他键值。",
    max_completion_tokens: int = MAX_COMPLETION_TOKENS,
    temperature: float = 0.7,
    timeout: float = 45.0,
    retries: int = 4,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[dict, dict]:
    base, model, api_key, _, _ = config
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": temperature,
        "max_tokens": max_completion_tokens,
        "stream": False,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/chat/completions", data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    opener = urllib.request.build_opener(_NoRedirect())
    last_error = "request failed"
    for attempt in range(retries + 1):
        try:
            with opener.open(request, timeout=timeout) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            if exc.code not in {408, 425, 429, 500, 502, 503, 504} or attempt == retries:
                break
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = type(exc).__name__
            if attempt == retries:
                break
        else:
            if len(payload) > MAX_RESPONSE_BYTES:
                raise TeacherResponseError("Teacher response exceeded size limit")
            try:
                result = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise TeacherResponseError("Teacher returned an invalid response envelope") from exc
            usage = result.get("usage") if isinstance(result, dict) else None
            usage = usage if isinstance(usage, dict) else {}
            choice = None
            try:
                choice = result["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                raise TeacherResponseError("Teacher response is missing message content", usage)
            if (
                not isinstance(choice, str)
                or type(usage.get("prompt_tokens")) is not int
                or type(usage.get("completion_tokens")) is not int
                or usage["prompt_tokens"] < 0
                or usage["completion_tokens"] < 0
            ):
                raise TeacherResponseError("Teacher response is missing content or token usage; refusing to save uncosted samples", usage)
            try:
                parsed_choice = json.loads(choice)
            except json.JSONDecodeError as exc:
                raise TeacherResponseError("Teacher content is not valid JSON", usage) from exc
            return parsed_choice, usage
        sleeper(min(30.0, 0.75 * (2 ** attempt)) + random.random() * 0.15)
    raise GenerationError(f"Teacher request failed after retries: {last_error}")


def _append_usage_record(
    path: Path,
    *,
    source: str,
    task_id: str,
    model: str,
    prompt_version: str,
    usage: dict,
    cost: float,
    status: str,
    source_file_sha256: str | None = None,
) -> None:
    provenance = {
        "task_id": task_id,
        "model": model,
        "prompt_version": prompt_version,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "cost_usd": round(cost, 10),
        "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if source_file_sha256 is not None:
        provenance["source_file_sha256"] = source_file_sha256
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"record_type": "usage", "source": source, "provenance": provenance}, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o600)


def _reported_cost(usage: dict, input_price: float, output_price: float) -> float | None:
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    if type(prompt_tokens) is not int or type(completion_tokens) is not int or prompt_tokens < 0 or completion_tokens < 0:
        return None
    return (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _validate_sample(sample: object, category: str) -> str:
    if not isinstance(sample, dict) or set(sample) != {"text", "category"} or sample.get("category") != category:
        raise GenerationError("Sample has an invalid category or shape")
    text = sample.get("text")
    if not isinstance(text, str):
        raise GenerationError("Sample text must be a string")
    text = re.sub(r"\s+", " ", text).strip()
    if not 3 <= len(text) <= 240:
        raise GenerationError("Sample text must contain 3 to 240 characters")
    if category == "otp" and not _OTP_INTENT.search(normalize_verification_codes(text)):
        raise GenerationError("OTP sample must retain a specific business intent after verification-code normalization")
    for url in _URL.findall(text):
        url = url.rstrip(".,;:!?，。；：！？")
        host = urllib.parse.urlparse(url if "://" in url else "http://" + url).hostname or ""
        if not host.casefold().endswith(".invalid"):
            raise GenerationError("Only fictional .invalid links are allowed")
    emails = _EMAIL.findall(text)
    if any(not email.casefold().endswith(".invalid") for email in emails):
        raise GenerationError("Only fictional .invalid email domains are allowed")
    if _MOBILE.search(text) or _ID_CARD.search(text) or _BANK_CARD.search(text):
        raise GenerationError("Sample contains a phone, ID, or bank-card-like number")
    return text


def _existing_records(path: Path) -> tuple[set[str], float]:
    completed: set[str] = set()
    total_cost = 0.0
    if not path.exists():
        return completed, total_cost
    valid_end = 0
    with path.open("rb") as handle:
        while True:
            start = handle.tell()
            line = handle.readline()
            if not line:
                valid_end = handle.tell()
                break
            try:
                record = json.loads(line.decode("utf-8"))
                completed.add(record["provenance"]["task_id"])
                total_cost += float(record["provenance"]["cost_usd"])
                valid_end = handle.tell()
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                # A crash may leave a partial final line; discard only the invalid tail.
                with path.open("r+b") as repair:
                    repair.truncate(start)
                break
    return completed, total_cost


def _write_checkpoint(path: Path, *, completed: set[str], total_cost: float) -> None:
    target = path.with_suffix(path.suffix + ".checkpoint.json")
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps({"completed_task_ids": sorted(completed), "total_cost_usd": round(total_cost, 10)}, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def generate_synthetic(*, count: int, output: str | Path, max_cost_usd: float, allow_remote: bool, env_allow: bool, sleeper: Callable[[float], None] = time.sleep) -> dict:
    """Generate only from fixed scenario labels; there is intentionally no SMS input argument."""
    if not allow_remote or not env_allow:
        raise GenerationError("Remote generation requires --allow-remote-generation and PRIVATESMS_ALLOW_SYNTHETIC_API=1")
    if count < 1 or count > MAX_PER_RUN:
        raise GenerationError(f"count must be between 1 and {MAX_PER_RUN}")
    if max_cost_usd <= 0:
        raise GenerationError("A positive --max-cost-usd is required; zero-cost default makes no API calls")
    config = _require_config()
    base, model, _, input_price, output_price = config
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    completed, total_cost = _existing_records(target)
    if total_cost >= max_cost_usd:
        raise GenerationError("Existing output has reached the configured cost budget")

    tasks = []
    for index in range(count):
        category = CATEGORIES[index % len(CATEGORIES)]
        scenario_list = SCENARIOS[category]
        scenario = scenario_list[index % len(scenario_list)]
        task_id = hashlib.sha256(f"{PROMPT_VERSION}\0{category}\0{index}\0{scenario}".encode()).hexdigest()
        tasks.append((task_id, category, scenario, index))

    for task_id, category, scenario, index in tasks:
        if task_id in completed:
            continue
        prompt = (
            "请合成一条自然、短小、符合中国大陆短信风格的虚构示例。"
            f"目标类别只能是 {category}，场景提示：{scenario}。"
            "验证码类别必须说明具体用途（如登录、设备绑定、身份核验、修改密码或支付），不要只生成验证码数字、有效期和保密套话；验证码值仅用虚构数字且会被归一化。"
            "若需网址，只能使用 example.invalid 或其他 .invalid 域名；号码用[虚构号码]占位。"
            "不得出现真实姓名、真实电话号码、身份证号、银行卡号、真实网址或可访问诈骗内容。"
            "suspicious 仅表示疑似风险，不得声称已确认诈骗；uncertain 必须表现为无法可靠判定。"
            '仅返回 JSON：{"text":"...","category":"..."}。'
        )
        # Conservative one-character/one-token reservation plus the capped output.
        prompt_chars = len(prompt) + len(model) + len(base) + 1500
        call_cost_reserve = (prompt_chars * input_price + MAX_COMPLETION_TOKENS * output_price) / 1_000_000
        if total_cost + call_cost_reserve > max_cost_usd:
            _write_checkpoint(target, completed=completed, total_cost=total_cost)
            raise GenerationError("Cost budget reserve reached; increase budget explicitly or resume later")
        try:
            response, usage = _request(prompt, config, sleeper=sleeper)
        except TeacherResponseError as exc:
            rejected_cost = _reported_cost(exc.usage, input_price, output_price)
            if rejected_cost is not None:
                _append_usage_record(target, source="teacher_synthetic", task_id=task_id, model=model, prompt_version=PROMPT_VERSION, usage=exc.usage, cost=rejected_cost, status="invalid_response")
                completed.add(task_id)
                total_cost += rejected_cost
                _write_checkpoint(target, completed=completed, total_cost=total_cost)
            raise
        cost = _reported_cost(usage, input_price, output_price)
        if cost is None:
            raise TeacherResponseError("Teacher usage fields cannot be priced", usage)
        if total_cost + cost > max_cost_usd:
            _append_usage_record(target, source="teacher_synthetic", task_id=task_id, model=model, prompt_version=PROMPT_VERSION, usage=usage, cost=cost, status="actual_cost_over_budget")
            completed.add(task_id)
            total_cost += cost
            _write_checkpoint(target, completed=completed, total_cost=total_cost)
            raise GenerationError("Actual reported usage exceeded remaining cost budget; usage was recorded and sample was not saved")
        try:
            text = _validate_sample(response, category)
        except GenerationError:
            _append_usage_record(target, source="teacher_synthetic", task_id=task_id, model=model, prompt_version=PROMPT_VERSION, usage=usage, cost=cost, status="sample_validation_rejected")
            completed.add(task_id)
            total_cost += cost
            _write_checkpoint(target, completed=completed, total_cost=total_cost)
            raise
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "text": text,
            "label": category,
            "category": category,
            "source": "teacher_synthetic",
            "synthetic": True,
            "training_only": True,
            "human_verified": False,
            "label_status": "teacher_generated_unverified",
            "provenance": {
                "provider_base_url_sha256": hashlib.sha256(base.encode()).hexdigest(),
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "generator_version": GENERATOR_VERSION,
                "task_id": task_id,
                "seed_index": index,
                "created_at": now,
                "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "prompt_tokens": usage["prompt_tokens"],
                "completion_tokens": usage["completion_tokens"],
                "cost_usd": round(cost, 10),
            },
        }
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(target, 0o600)
        completed.add(task_id)
        total_cost += cost
        _write_checkpoint(target, completed=completed, total_cost=total_cost)
        if index < count - 1:
            sleeper(1.0)
    return {"requested": count, "completed_total": len(completed), "total_cost_usd": round(total_cost, 10), "output": str(target)}
