"""LLM-as-judge scoring for groundedness and faithfulness with caching and retry."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_combine,
    wait_exception,
    wait_random,
)

from lancet_eval.client import StructuredCitation

Score5 = Annotated[int, Field(ge=1, le=5)]

JUDGE_PROMPT_VERSION = "v1"
PER_PASSAGE_CHAR_BUDGET = 1500
EVIDENCE_CHAR_BUDGET = 12000
DEFAULT_MAX_TOKENS = 400
DEFAULT_TEMPERATURE = 0.0
DEFAULT_CHAT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

JUDGE_SYSTEM_V1 = """\
You are an evaluation judge grading whether a generated answer is grounded in and \
faithful to the supplied evidence.

Your job is to grade the answer strictly against the supplied evidence and NOTHING ELSE.
Do NOT use any outside knowledge or your own priors. Even if a statement is \
factually true in the real world, if it is not supported by evidence, it is ungrounded.

Rubric:

Groundedness (1-5): Is every factual claim in the answer traceable to an excerpt?
- 5: Every factual claim is directly supported by a specific excerpt. \
Nothing requires taking the model's word for it.
- 3: The core claim is supported, but a supporting detail appears without backing.
- 1: Central claims have no support anywhere in the supplied evidence.

Faithfulness (1-5): Does the answer avoid distorting or going beyond the evidence?
- 5: No claim contradicts or overstates any excerpt; no outside knowledge is injected.
- 3: Broadly consistent with evidence but overstates certainty or drops qualifiers.
- 1: The answer contradicts the evidence, or answers from model priors.

Output Format:
You MUST reply with a valid JSON object conforming to this schema:
{
  "groundedness": <integer 1 to 5>,
  "faithfulness": <integer 1 to 5>,
  "unsupported_claims": [<string>, ...],
  "rationale": "<brief explanation, max 600 characters>"
}
"""


class JudgeVerdict(BaseModel):
    """Structured verdict from LLM-as-judge."""

    model_config = ConfigDict(extra="ignore")

    groundedness: Score5
    faithfulness: Score5
    unsupported_claims: list[str] = Field(default_factory=list, max_length=10)
    rationale: str = Field(default="", max_length=600)


class JudgeCacheEntry(BaseModel):
    """Auditable cache entry stored in plain-text JSON."""

    model_config = ConfigDict(extra="ignore")

    cache_key: str
    prompt_version: str
    judge_model: str
    question: str
    answer: str
    evidence: str
    verdict: JudgeVerdict | None = None
    error: str | None = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


def truncate_evidence(
    citations: list[StructuredCitation],
    *,
    per_passage_budget: int = PER_PASSAGE_CHAR_BUDGET,
    total_budget: int = EVIDENCE_CHAR_BUDGET,
) -> str:
    """Deterministically truncate citations in wire ranked order.

    Caps per passage before total, and appends explicit marker on overflow.
    """
    if not citations:
        return ""

    passages: list[str] = []
    current_chars = 0

    for idx, c in enumerate(citations):
        excerpt = c.excerpt.strip()
        if len(excerpt) > per_passage_budget:
            excerpt = excerpt[:per_passage_budget] + "..."

        passage_str = (
            f"[{idx + 1}] (Document: {c.document_id}, Rank: {c.rank}):\n"
            f"{excerpt}\n\n"
        )
        passage_len = len(passage_str)

        if current_chars + passage_len > total_budget:
            omitted = len(citations) - idx
            marker = f"[TRUNCATED: {omitted} further passages omitted]"
            passages.append(marker)
            break

        passages.append(passage_str)
        current_chars += passage_len

    return "".join(passages).strip()


def cache_key(
    *,
    prompt_version: str,
    judge_model: str,
    question: str,
    answer: str,
    post_truncation_evidence: str,
) -> str:
    """Compute SHA-256 cache key over fixed prompt and input fields."""
    payload = (
        f"{prompt_version}\x1f{judge_model}\x1f"
        f"{question}\x1f{answer}\x1f{post_truncation_evidence}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _strip_fences(text: str) -> str:
    """Strip markdown code fences from model response."""
    clean = text.strip()
    match = re.search(r"^```(?:json)?\s*\n(.*)\n```\s*$", clean, re.DOTALL)
    if match:
        return match.group(1).strip()
    return clean


def _extract_retry_after(exception: BaseException) -> float:
    """Extract Retry-After header seconds from HTTPStatusError."""
    if isinstance(exception, httpx.HTTPStatusError):
        if exception.response.status_code == 429:
            retry_after = exception.response.headers.get("Retry-After")
            if retry_after:
                try:
                    return float(retry_after)
                except ValueError:
                    pass
    return 1.0


def _is_retryable_judge_error(exc: BaseException) -> bool:
    """Return True if exception should trigger transport retry."""
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return False


@retry(
    retry=retry_if_exception(_is_retryable_judge_error),
    wait=wait_combine(wait_exception(_extract_retry_after), wait_random(0.0, 2.0)),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _post_judge(
    client: httpx.Client,
    *,
    endpoint: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Execute POST to judge chat completion endpoint with retry."""
    resp = client.post(endpoint, headers=headers, json=payload, timeout=60.0)
    resp.raise_for_status()
    return resp.json()


class JudgeCache:
    """Atomic, auditable plain-text JSON cache for judge verdicts."""

    def __init__(self, cache_path: Path | str) -> None:
        self.path = Path(cache_path)
        self.entries: dict[str, JudgeCacheEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    try:
                        self.entries[k] = JudgeCacheEntry.model_validate(v)
                    except Exception:
                        continue
        except Exception:
            pass

    def save(self) -> None:
        """Save cache atomically to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = self.path.with_suffix(f".tmp-{os.getpid()}")
        raw_dict = {
            k: v.model_dump(mode="json")
            for k, v in sorted(self.entries.items())
        }
        with open(tmp_file, "w", encoding="utf-8", newline="\n") as f:
            json.dump(raw_dict, f, indent=2, ensure_ascii=False)
            f.write("\n")
        tmp_file.replace(self.path)

    def get(self, key: str) -> JudgeCacheEntry | None:
        return self.entries.get(key)

    def set(self, key: str, entry: JudgeCacheEntry) -> None:
        self.entries[key] = entry
        self.save()


def judge_once(
    client: httpx.Client | None = None,
    *,
    api_key: str,
    model: str,
    question: str,
    answer: str,
    evidence: str,
    prompt_version: str = JUDGE_PROMPT_VERSION,
    endpoint: str = DEFAULT_CHAT_ENDPOINT,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_reasks: int = 1,
) -> tuple[JudgeVerdict | None, str | None]:
    """Execute LLM-as-judge with single bounded re-ask on validation failure."""
    if not evidence.strip():
        return (None, "no evidence returned; groundedness undefined")

    if not api_key.strip():
        return (None, "OPENROUTER_API_KEY is not set")

    system_prompt = JUDGE_SYSTEM_V1
    user_content = (
        f"=== QUESTION ===\n{question}\n\n"
        f"=== ANSWER ===\n{answer}\n\n"
        f"=== EVIDENCE ===\n{evidence}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    http_client = client or httpx.Client()
    close_client = client is None

    try:
        for attempt in range(max_reasks + 1):
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            }

            try:
                resp_json = _post_judge(
                    http_client,
                    endpoint=endpoint,
                    headers=headers,
                    payload=payload,
                )
            except Exception as e:
                return (None, f"Judge transport failure: {e}")

            choices = resp_json.get("choices") or []
            if not choices:
                return (None, "Judge returned empty choices")

            content = choices[0].get("message", {}).get("content", "")
            cleaned = _strip_fences(content)

            try:
                verdict = JudgeVerdict.model_validate_json(cleaned)
                return (verdict, None)
            except ValidationError as exc:
                if attempt >= max_reasks:
                    return (
                        None,
                        f"Judge output validation failed after re-ask: {exc}",
                    )
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "That did not validate against the required schema:\n"
                            f"{exc.errors(include_url=False)}\n"
                            "Reply with ONLY the corrected JSON object."
                        ),
                    }
                )
        return (None, "Judge validation exhausted")
    finally:
        if close_client:
            http_client.close()
