"""
gemini_client.py — Single Gemini API wrapper for all LLM calls.

All calls go through this module so usage_logger sees every call.
API key is read exclusively from the GEMINI_API_KEY environment variable.
Never pass the key in code or config files (see guardrails.md).
"""

import os
import json
import hashlib
import time
import logging
from pathlib import Path

import google.generativeai as genai

# ---------------------------------------------------------------------------
# Configuration — all magic numbers live here, nowhere else (style.md)
# ---------------------------------------------------------------------------
CACHE_DIR   = Path(__file__).parent.parent / "cache"
FLASH_MODEL = "gemini-3.8-flash"      # primary: high-speed, native multimodal, strict JSON
FALLBACK_FLASH_MODEL = "gemini-flash-latest"
PRO_MODEL   = "gemini-3.1-pro-preview"  # reserve: complex edge cases if quota permits

# ---------------------------------------------------------------------------
# Initialise API key
# ---------------------------------------------------------------------------
# Auto-load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

_api_key = os.environ.get("GEMINI_API_KEY")
if not _api_key:
    raise EnvironmentError(
        "GEMINI_API_KEY environment variable is not set.\n"
        "Set it in .env or before running:\n"
        "  PowerShell:  $env:GEMINI_API_KEY = 'your-key-here'\n"
        "  bash/zsh:    export GEMINI_API_KEY=your-key-here\n"
        "Never put the key in code or commit it to the repo (guardrails.md)."
    )

genai.configure(api_key=_api_key)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Usage tracking — feeds evaluation/usage_report.md
# ---------------------------------------------------------------------------
_usage_records: list[dict] = []


def get_usage_records() -> list[dict]:
    """Return all recorded LLM calls for usage_report.md generation."""
    return list(_usage_records)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _cache_key(model: str, payload: dict) -> str:
    raw = json.dumps({"model": model, "payload": payload}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Core call — cached by input hash (see harness.md)
# ---------------------------------------------------------------------------
def call_gemini(
    *,
    model: str = FLASH_MODEL,
    system_prompt: str,
    user_content,           # str for text-only; list[Part] for multimodal
    response_schema: dict,  # strict JSON schema for structured output
    cache_key_extra: str = "",
) -> dict:
    """
    Make one Gemini structured-output call, cached on disk by input hash.

    Returns: parsed dict conforming to response_schema.
    Raises:  ValueError on schema violation or unparseable response.

    Rules enforced here (main.md non-negotiables):
    - temperature=0 always — same input -> same output
    - structured JSON output only — no free-form text returned
    - every call recorded in _usage_records for usage_report.md
    """
    payload = {
        "system": system_prompt,
        "user": user_content if isinstance(user_content, str) else "<multipart>",
        "schema": response_schema,
        "extra": cache_key_extra,
    }
    ck = _cache_key(model, payload)
    cache_file = CACHE_DIR / f"{ck}.json"

    # --- Cache hit ---
    if cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        _usage_records.append({**cached["usage"], "cache_hit": True})
        logger.debug("Cache hit: %s", ck[:12])
        return cached["result"]

    # --- Cache miss: call the API ---
    t0 = time.monotonic()
    gen_model = genai.GenerativeModel(
        model_name=model,
        system_instruction=system_prompt,
        generation_config=genai.GenerationConfig(
            temperature=0,                    # non-negotiable (main.md)
            response_mime_type="application/json",
            response_schema=response_schema,
        ),
    )

    response = gen_model.generate_content(user_content)
    latency_ms = int((time.monotonic() - t0) * 1000)

    usage = {
        "model": model,
        "input_tokens": response.usage_metadata.prompt_token_count,
        "output_tokens": response.usage_metadata.candidates_token_count,
        "latency_ms": latency_ms,
        "cache_hit": False,
    }

    result = json.loads(response.text)

    # Persist to cache
    cache_file.write_text(
        json.dumps({"result": result, "usage": usage}, ensure_ascii=False),
        encoding="utf-8",
    )

    _usage_records.append(usage)
    logger.info(
        "Gemini call: model=%s in=%d out=%d latency=%dms",
        model,
        usage["input_tokens"],
        usage["output_tokens"],
        latency_ms,
    )
    return result
