from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from typing import Optional

log = logging.getLogger(__name__)

# Default free model — smallest/fastest available on free tier
DEFAULT_MODEL = "gemini-2.5-flash-lite"
DEFAULT_PROVIDER = "gemini"

# Supported premium models and their providers
MODEL_PROVIDERS: dict[str, str] = {
    # Gemini
    "gemini-2.5-flash":      "gemini",
    "gemini-2.5-pro":        "gemini",
    "gemini-2.0-flash":      "gemini",
    "gemini-2.0-flash-lite": "gemini",
    # Anthropic
    "claude-sonnet-4-6":     "anthropic",
    "claude-opus-4-6":       "anthropic",
    # OpenAI
    "gpt-4o":                "openai",
    "gpt-4o-mini":           "openai",
    # Groq (free tier — very generous quota)
    "llama-3.3-70b-versatile":     "groq",
    "llama-3.1-8b-instant":        "groq",
    "llama3-70b-8192":             "groq",
    "mixtral-8x7b-32768":          "groq",
    "gemma2-9b-it":                "groq",
    # DeepSeek (very cheap, excellent quality)
    "deepseek-chat":               "deepseek",
    "deepseek-reasoner":           "deepseek",
    # Mistral (free tier available)
    "mistral-small-latest":        "mistral",
    "mistral-medium-latest":       "mistral",
    "mistral-large-latest":        "mistral",
    # Cerebras (extremely fast inference, free tier)
    "llama-4-scout-17b-16e-instruct": "cerebras",
    "llama-3.3-70b":               "cerebras",
    # OpenRouter (unified gateway — 300+ models, many free)
    "openrouter/auto":                          "openrouter",
    "meta-llama/llama-3.3-70b-instruct:free":  "openrouter",
    "google/gemini-2.0-flash-exp:free":         "openrouter",
    "deepseek/deepseek-r1:free":                "openrouter",
    "mistralai/mistral-7b-instruct:free":       "openrouter",
    # GitHub Models (free with GitHub token)
    "github/gpt-4o":               "github",
    "github/gpt-4o-mini":          "github",
    "github/meta-llama-3.3-70b":   "github",
}

_OPENAI_COMPAT_URLS: dict[str, str] = {
    "groq":       "https://api.groq.com/openai/v1",
    "deepseek":   "https://api.deepseek.com/v1",
    "mistral":    "https://api.mistral.ai/v1",
    "cerebras":   "https://api.cerebras.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "github":     "https://models.inference.ai.azure.com",
}

# ── Response cache ────────────────────────────────────────────────────────────
# Caches identical requests for 60 s to avoid burning quota on repeated messages.
_CACHE_TTL = 60  # seconds
_response_cache: dict[str, tuple[str, float]] = {}  # key → (response, expires_at)

def _cache_key(model: str, system_prompt: str, messages: list[dict]) -> str:
    payload = json.dumps({"model": model, "system": system_prompt, "messages": messages}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()

def _cache_get(key: str) -> Optional[str]:
    entry = _response_cache.get(key)
    if entry and time.monotonic() < entry[1]:
        return entry[0]
    if entry:
        del _response_cache[key]
    return None

def _cache_set(key: str, value: str) -> None:
    # Evict expired entries when cache grows large
    if len(_response_cache) > 500:
        now = time.monotonic()
        expired = [k for k, (_, exp) in _response_cache.items() if now >= exp]
        for k in expired:
            del _response_cache[k]
    _response_cache[key] = (value, time.monotonic() + _CACHE_TTL)


def get_provider(model: str) -> str:
    """Return the provider name for a model string."""
    return MODEL_PROVIDERS.get(model, "gemini")


def _decrypt_key(encrypted: str) -> Optional[str]:
    enc_key = os.getenv("ENCRYPTION_KEY")
    if not enc_key:
        return None
    try:
        from cryptography.fernet import Fernet
        f = Fernet(enc_key.encode())
        return f.decrypt(encrypted.encode()).decode()
    except Exception as e:
        log.warning("Failed to decrypt API key: %s", e)
        return None


def encrypt_key(plaintext: str) -> Optional[str]:
    enc_key = os.getenv("ENCRYPTION_KEY")
    if not enc_key:
        return None
    try:
        from cryptography.fernet import Fernet
        f = Fernet(enc_key.encode())
        return f.encrypt(plaintext.encode()).decode()
    except Exception as e:
        log.warning("Failed to encrypt API key: %s", e)
        return None


# ── Retry with exponential backoff ───────────────────────────────────────────

async def _with_backoff(coro_fn, max_retries: int = 3):
    """
    Call coro_fn() up to max_retries times.
    Retries on RateLimitError / HTTP 429 with exponential backoff (1s, 2s, 4s).
    All other exceptions are re-raised immediately.
    """
    delay = 1.0
    for attempt in range(max_retries):
        try:
            return await coro_fn()
        except Exception as e:
            err = str(e).lower()
            is_rate_limit = (
                "ratelimit" in err
                or "rate limit" in err
                or "rate_limit" in err
                or "429" in err
                or "too many requests" in err
            )
            if is_rate_limit and attempt < max_retries - 1:
                log.warning("Rate limit hit — retrying in %.0fs (attempt %d/%d)", delay, attempt + 1, max_retries)
                await asyncio.sleep(delay)
                delay *= 2
            else:
                raise


async def call_ai(
    model: Optional[str],
    encrypted_api_key: Optional[str],
    system_prompt: str,
    messages: list[dict],
    *,
    thinking: bool = False,
) -> Optional[str]:
    """
    Route the request to the correct AI provider and return the response text.
    Falls back to the free Groq/Gemini default if no custom key is configured.
    Applies response caching (60 s) and exponential backoff on rate limits.

    messages: list of {"role": "user"|"assistant", "content": str}
    """
    # Resolve model + key
    if model and encrypted_api_key:
        api_key = _decrypt_key(encrypted_api_key)
        if not api_key:
            log.warning("Could not decrypt stored API key — falling back to free default")
            model, api_key, provider = _free_default()
        else:
            provider = get_provider(model)
    else:
        model, api_key, provider = _free_default()

    if not api_key:
        return None

    # Check cache
    cache_key = _cache_key(model, system_prompt, messages)
    cached = _cache_get(cache_key)
    if cached:
        log.debug("AI cache hit | model=%s", model)
        return cached

    _start = time.monotonic()
    try:
        async def _call():
            if provider == "gemini":
                return await _call_gemini(api_key, model, system_prompt, messages, thinking=thinking)
            elif provider == "anthropic":
                return await _call_anthropic(api_key, model, system_prompt, messages)
            elif provider == "openai":
                return await _call_openai(api_key, model, system_prompt, messages)
            elif provider in ("groq", "deepseek", "mistral", "cerebras", "openrouter", "github"):
                return await _call_openai_compat(api_key, model, system_prompt, messages, provider=provider)
            else:
                log.warning("Unknown provider %s", provider)
                return None

        result = await _with_backoff(_call)
        latency_ms = int((time.monotonic() - _start) * 1000)
        log.info(
            "AI request | model=%s provider=%s latency=%dms tokens_est=%d",
            model, provider, latency_ms,
            len(result) // 4 if result else 0,
        )
        if result:
            _cache_set(cache_key, result)
        return result
    except Exception as e:
        latency_ms = int((time.monotonic() - _start) * 1000)
        log.warning("AI call failed (%s/%s) after %dms: %s", provider, model, latency_ms, e)
        return None


def _free_default() -> tuple[str, Optional[str], str]:
    """Return (model, api_key, provider) for the free default tier."""
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        return "llama-3.3-70b-versatile", groq_key, "groq"
    return DEFAULT_MODEL, os.getenv("GEMINI_API_KEY"), DEFAULT_PROVIDER


async def _call_gemini(
    api_key: str,
    model: str,
    system_prompt: str,
    messages: list[dict],
    *,
    thinking: bool = False,
) -> Optional[str]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    if not messages:
        return None

    history = []
    for msg in messages[:-1]:
        role = "user" if msg["role"] == "user" else "model"
        history.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))

    config_kwargs: dict = {"system_instruction": system_prompt}
    if thinking:
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=8192)

    config = types.GenerateContentConfig(**config_kwargs)
    chat = client.aio.chats.create(model=model, history=history, config=config)
    response = await chat.send_message(messages[-1]["content"])
    return response.text


async def _call_anthropic(
    api_key: str,
    model: str,
    system_prompt: str,
    messages: list[dict],
) -> Optional[str]:
    try:
        import anthropic as _anthropic
    except ImportError:
        log.error("anthropic package not installed. Run: pip install anthropic")
        return None

    client = _anthropic.AsyncAnthropic(api_key=api_key)
    converted = [{"role": m["role"], "content": m["content"]} for m in messages]
    response = await client.messages.create(
        model=model,
        max_tokens=2048,
        system=system_prompt,
        messages=converted,
    )
    return response.content[0].text if response.content else None


async def _call_openai(
    api_key: str,
    model: str,
    system_prompt: str,
    messages: list[dict],
) -> Optional[str]:
    try:
        from openai import AsyncOpenAI
    except ImportError:
        log.error("openai package not installed. Run: pip install openai")
        return None

    client = AsyncOpenAI(api_key=api_key)
    converted = [{"role": "system", "content": system_prompt}]
    converted += [{"role": m["role"], "content": m["content"]} for m in messages]
    response = await client.chat.completions.create(model=model, messages=converted, max_tokens=2048)
    return response.choices[0].message.content if response.choices else None


async def _call_openai_compat(
    api_key: str,
    model: str,
    system_prompt: str,
    messages: list[dict],
    *,
    provider: str,
) -> Optional[str]:
    """Generic handler for any OpenAI-compatible provider."""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        log.error("openai package not installed.")
        return None

    base_url = _OPENAI_COMPAT_URLS.get(provider)
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    # Strip provider prefix for namespaced model IDs
    effective_model = model
    if provider == "openrouter" and model.startswith("openrouter/"):
        effective_model = model[len("openrouter/"):]
    elif provider == "github" and model.startswith("github/"):
        effective_model = model[len("github/"):]

    converted = [{"role": "system", "content": system_prompt}]
    converted += [{"role": m["role"], "content": m["content"]} for m in messages]
    response = await client.chat.completions.create(model=effective_model, messages=converted, max_tokens=2048)
    return response.choices[0].message.content if response.choices else None
