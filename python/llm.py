"""Tiny OpenAI-compatible LLM client (same idea as MediOps). Settings come from .env.
The key is never printed. If the call fails (quota, busy servers), ask_llm returns None.
"""
import os
import time

import requests

import db  # noqa: F401  loads .env

_PLACEHOLDERS = {"", "key", "model", "model_name", "base_url"}


def _value(name):
    value = os.environ.get(name, "").strip()
    lowered = value.lower()
    if lowered in _PLACEHOLDERS or lowered.startswith(("paste_", "your_", "the_")):
        return ""
    return value


def llm_available():
    return bool(_value("LLM_API_KEY") and _value("LLM_MODEL"))


last_failure = {"reason": None}


def ask_llm(system, user, temperature=0.1, max_tokens=2000):
    last_failure["reason"] = None
    if not llm_available():
        return None
    base = (os.environ.get("LLM_BASE_URL", "").strip() or "https://api.openai.com/v1").rstrip("/")
    try:
        body = {
            "model": _value("LLM_MODEL"),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max(max_tokens, 4000),
        }
        effort = os.environ.get("LLM_REASONING_EFFORT", "").strip()
        if effort:
            body["reasoning_effort"] = effort
        for attempt in range(3):
            response = requests.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {_value('LLM_API_KEY')}"},
                json=body,
                timeout=90,
            )
            if response.status_code not in (500, 502, 503, 504) or attempt == 2:
                break
            time.sleep(4 * (attempt + 1))
        response.raise_for_status()
        text = (response.json()["choices"][0]["message"].get("content") or "").strip()
        return text or None
    except Exception as error:
        status = getattr(getattr(error, "response", None), "status_code", None)
        last_failure["reason"] = f"HTTP {status}" if status else type(error).__name__
        print(f"[LLM call failed: {last_failure['reason']}]", flush=True)
        return None
