"""Natural server voice with Gemini TTS (optional, same key as the LLM path).

Enabled when LLM_PROVIDER=gemini and LLM_API_KEY is set. Gemini returns raw
24 kHz 16-bit mono PCM, which is wrapped as WAV so any browser can play it.
Results are cached on disk next to the database, so a sentence the app says
often ("Say who to send money to...") is generated once.

  TTS_MODEL  default gemini-2.5-flash-preview-tts
  TTS_VOICE  default Kore
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import uuid
import wave
from pathlib import Path

import httpx

MAX_CHARS = 400
# Bare text that reads like a command or a question ("Send 500 taka to
# Rahim?") often comes back with no audio (finishReason OTHER): the model
# treats it as a prompt. Framing it as something to say fixes that.
STYLE = "Say in a warm, natural, clear voice: "
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
ROOT = Path(__file__).resolve().parents[3]


def enabled() -> bool:
    return ((os.getenv("LLM_PROVIDER") or "").strip().lower() == "gemini"
            and bool(os.getenv("LLM_API_KEY")))


def _model() -> str:
    return os.getenv("TTS_MODEL") or "gemini-2.5-flash-preview-tts"


def _voice() -> str:
    return os.getenv("TTS_VOICE") or "Kore"


def _cache_dir() -> Path:
    db = os.getenv("DB_PATH", str(ROOT / "data" / "bolo.db"))
    return Path(db).parent / "tts"


def _wav(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _request(text: str) -> bytes | None:
    """One Gemini call. Returns WAV bytes, or None if no audio came back."""
    r = httpx.post(
        URL.format(model=_model()),
        headers={"x-goog-api-key": os.environ["LLM_API_KEY"]},
        json={"contents": [{"parts": [{"text": STYLE + text}]}],
              "generationConfig": {
                  "responseModalities": ["AUDIO"],
                  "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": _voice()}}}}},
        timeout=30.0,
    )
    r.raise_for_status()
    for cand in r.json().get("candidates", []):
        for part in (cand.get("content") or {}).get("parts", []):
            inline = part.get("inlineData") or {}
            if inline.get("data"):
                m = re.search(r"rate=(\d+)", inline.get("mimeType", ""))
                return _wav(base64.b64decode(inline["data"]), int(m.group(1)) if m else 24000)
    return None


def synthesize(text: str) -> bytes:
    """WAV audio for ``text`` (cached). Raises if Gemini fails twice."""
    text = " ".join(text.split())[:MAX_CHARS]
    key = hashlib.sha256(f"{_model()}|{_voice()}|{STYLE}|{text}".encode()).hexdigest()
    path = _cache_dir() / f"{key}.wav"
    if path.exists():
        return path.read_bytes()
    wav, error = None, None
    for _ in range(2):  # retry once: the preview model sometimes returns no audio
        try:
            wav = _request(text)
        except (httpx.HTTPError, KeyError, ValueError) as e:
            error = e
        if wav:
            break
    if not wav:
        raise RuntimeError(f"no audio from {_model()}: {error or 'empty response'}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{key}.{uuid.uuid4().hex}.tmp")  # unique: two requests may race
    tmp.write_bytes(wav)
    tmp.replace(path)
    return wav
