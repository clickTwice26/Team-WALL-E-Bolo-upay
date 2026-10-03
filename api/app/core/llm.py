"""Optional LLM intent extraction (path A of the parser).

The app works without any key: the rule parser alone is used and the
response says ``llm_used: false``. With a key, the LLM result is compared
with the rule parser and any disagreement makes the app ask the user.

Configure with environment variables:
  LLM_PROVIDER = anthropic | openai | gemini   (empty = disabled)
  LLM_API_KEY  = the provider key
  LLM_MODEL    = optional model override
"""
from __future__ import annotations

import json
import logging
import os
from typing import Literal, Optional

import httpx
from pydantic import BaseModel, ValidationError

log = logging.getLogger("bolo.llm")

SYSTEM_PROMPT = """You extract a mobile-wallet command from a Bangladeshi user's speech.
The text may be Bangla, Banglish (Bangla written in English letters) or English.
Return only the fields asked for. Rules:
- intent: send_money, mobile_recharge, check_balance, unsupported or unknown.
- amount: the taka amount as a whole number, or null if no amount was said.
  Convert Bangla number words: দেড় হাজার = 1500, আড়াইশো = 250, সাড়ে তিন হাজার = 3500.
  Never invent an amount.
- recipient_text: the name or relation exactly as the user said it
  (for example "Ammu", "Rahim bhai", "রহিম"), or null.
- phone: an 11-digit number starting with 01 if one was said, else null.
- confidence: 0.0 to 1.0, how sure you are about intent and amount together."""

DEFAULT_MODELS = {
    "anthropic": "claude-opus-5-5",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.5-flash",
}


class LLMCommand(BaseModel):
    intent: Literal["send_money", "mobile_recharge", "check_balance",
                    "unsupported", "unknown"]
    amount: Optional[int] = None
    recipient_text: Optional[str] = None
    phone: Optional[str] = None
    confidence: float = 0.0


def provider() -> str:
    return (os.getenv("LLM_PROVIDER") or "").strip().lower()


def enabled() -> bool:
    return provider() in DEFAULT_MODELS and bool(os.getenv("LLM_API_KEY"))


def _model() -> str:
    return os.getenv("LLM_MODEL") or DEFAULT_MODELS[provider()]


def _anthropic(text: str) -> LLMCommand:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["LLM_API_KEY"], timeout=20.0)
    resp = client.messages.parse(
        model=_model(),
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
        output_format=LLMCommand,
        output_config={"effort": "low"},
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise ValueError("no structured output")
    return resp.parsed_output


def _schema_prompt(text: str) -> str:
    return (SYSTEM_PROMPT + "\nRespond with a JSON object with keys intent, amount, "
            "recipient_text, phone, confidence.\n\nUser said: " + text)


def _openai(text: str) -> LLMCommand:
    r = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['LLM_API_KEY']}"},
        json={"model": _model(), "temperature": 0,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "user", "content": _schema_prompt(text)}]},
        timeout=20.0,
    )
    r.raise_for_status()
    return LLMCommand.model_validate_json(r.json()["choices"][0]["message"]["content"])


def _gemini(text: str) -> LLMCommand:
    r = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{_model()}:generateContent",
        params={"key": os.environ["LLM_API_KEY"]},
        json={"contents": [{"parts": [{"text": _schema_prompt(text)}]}],
              "generationConfig": {"temperature": 0,
                                   "responseMimeType": "application/json"}},
        timeout=20.0,
    )
    r.raise_for_status()
    raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return LLMCommand.model_validate(json.loads(raw))


def extract(text: str) -> Optional[LLMCommand]:
    """Return the LLM's reading of the command, or None (disabled / failed).

    Failures never break the app: the rule parser still runs.
    """
    if not enabled():
        return None
    try:
        return {"anthropic": _anthropic, "openai": _openai, "gemini": _gemini}[provider()](text)
    except (httpx.HTTPError, ValidationError, ValueError, KeyError, json.JSONDecodeError) as e:
        log.warning("LLM extraction failed (%s): %s", provider(), e)
    except Exception as e:  # provider SDK errors (rate limit, auth, network)
        log.warning("LLM provider error (%s): %s", provider(), e)
    return None
