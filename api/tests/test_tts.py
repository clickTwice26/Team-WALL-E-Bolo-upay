import base64
import io
import os
import tempfile
import wave

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("HOLD_SECONDS", "0")
os.environ.pop("LLM_PROVIDER", None)

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import tts  # noqa: E402
from app.main import app  # noqa: E402

c = TestClient(app)


class _Resp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def _audio(pcm=b"\x01\x00" * 2400):
    return _Resp({"candidates": [{"content": {"parts": [{"inlineData": {
        "mimeType": "audio/L16;codec=pcm;rate=24000", "data": base64.b64encode(pcm).decode()}}]}}]})


@pytest.fixture
def gemini(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "bolo.db"))
    calls = []

    def install(*responses):
        queue = list(responses)

        def fake_post(url, headers=None, json=None, timeout=None):
            calls.append({"url": url, "headers": headers, "json": json})
            return queue.pop(0)
        monkeypatch.setattr(httpx, "post", fake_post)
        return calls
    return install


def test_disabled_without_gemini_key():
    assert c.get("/api/health").json()["tts"] is False
    assert c.post("/api/tts", json={"text": "hello"}).status_code == 503


def test_wav_from_pcm_with_retry_and_cache(gemini, tmp_path):
    calls = gemini(_Resp({"candidates": [{"finishReason": "OTHER", "content": {}}]}), _audio())
    assert c.get("/api/health").json()["tts"] is True
    r = c.post("/api/tts", json={"text": "Send 500 taka to Rahim?"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    w = wave.open(io.BytesIO(r.content))
    assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 24000, 2400)
    # first answer had no audio -> retried once; the text is framed as something to say
    assert len(calls) == 2
    assert calls[0]["headers"] == {"x-goog-api-key": "test-key"}
    assert calls[0]["json"]["contents"][0]["parts"][0]["text"].startswith(tts.STYLE)
    assert calls[0]["json"]["generationConfig"]["responseModalities"] == ["AUDIO"]
    # cached on disk next to the database: no third call
    assert c.post("/api/tts", json={"text": "Send 500 taka to Rahim?"}).content == r.content
    assert len(calls) == 2 and len(list((tmp_path / "tts").glob("*.wav"))) == 1


def test_failure_is_502_and_long_text_rejected(gemini):
    gemini(_Resp({"candidates": []}), _Resp({"candidates": []}))
    assert c.post("/api/tts", json={"text": "no audio twice"}).status_code == 502
    assert c.post("/api/tts", json={"text": "x" * (tts.MAX_CHARS + 1)}).status_code == 422
