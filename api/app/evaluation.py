"""Study tooling (demo sites only).

GET /api/eval/prompts  the real-audio study script (R1, docs/AUDIO_EVAL.md):
the 96 labelled test commands, each with the Bangla text to read aloud, plus
10 free-form tasks. The app's evaluation mode shows them one by one and logs
the transcript, STT confidence and parse result (never audio).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from . import auth

ROOT = Path(__file__).resolve().parents[2]
router = APIRouter()


@lru_cache(maxsize=1)
def prompts() -> dict:
    tests = json.loads((ROOT / "data" / "test_commands.json").read_text(encoding="utf-8"))["commands"]
    script = json.loads((ROOT / "data" / "audio_eval_prompts.json").read_text(encoding="utf-8"))
    spoken = script["spoken_bn"]
    out = [{"id": f"C{t['id']}", "kind": "read",
            # Banglish/English commands are read in Bangla script: that is what bn-BD STT writes
            "text": spoken.get(str(t["id"]), t["text"]), "typed": t["text"],
            "expected": {k: t[k] for k in ("intent", "amount", "recipient")}} for t in tests]
    out += [{"id": f["id"], "kind": "free", "task_bn": f["task_bn"], "task_en": f["task_en"],
             "expected": {k: f[k] for k in ("intent", "amount", "recipient")}} for f in script["free_tasks"]]
    return {"user": script["user"], "prompts": out}


@router.get("/api/eval/prompts")
def eval_prompts(s: auth.Session = Depends(auth.current)):
    if not auth.demo_mode():
        raise HTTPException(404, "not found")
    return prompts()
