from __future__ import annotations

import os
import logging
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
}


def get_provider(model: str) -> str:
    """Return the provider name for a model string."""
    return MODEL_PROVIDERS.get(model, "gemini")


def _decrypt_key(encrypted: str) -> Optional[str]:
    """Decrypt an API key stored at rest. Returns None if ENCRYPTION_KEY is not set."""
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
    """Encrypt an API key for storage. Returns None if ENCRYPTION_KEY is not set."""
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
    Falls back to the free Gemini default if no custom key is configured.

    messages: list of {"role": "user"|"assistant", "content": str}
    """
    # Resolve model + key
    if model and encrypted_api_key:
        api_key = _decrypt_key(encrypted_api_key)
        if not api_key:
            log.warning("Could not decrypt stored API key — falling back to free Gemini")
            model = DEFAULT_MODEL
            api_key = os.getenv("GEMINI_API_KEY")
            provider = DEFAULT_PROVIDER
        else:
            provider = get_provider(model)
    else:
        # No custom key — try Groq free tier first, fall back to Gemini
        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key:
            model = "llama-3.3-70b-versatile"
            api_key = groq_key
            provider = "groq"
        else:
            model = DEFAULT_MODEL
            api_key = os.getenv("GEMINI_API_KEY")
            provider = DEFAULT_PROVIDER

    if not api_key:
        return None

    import time
    _start = time.monotonic()
    try:
        if provider == "gemini":
            result = await _call_gemini(api_key, model, system_prompt, messages, thinking=thinking)
        elif provider == "anthropic":
            result = await _call_anthropic(api_key, model, system_prompt, messages)
        elif provider == "openai":
            result = await _call_openai(api_key, model, system_prompt, messages)
        elif provider == "groq":
            result = await _call_groq(api_key, model, system_prompt, messages)
        else:
            log.warning("Unknown provider %s", provider)
            return None
        latency_ms = int((time.monotonic() - _start) * 1000)
        log.info(
            "AI request | model=%s provider=%s latency=%dms tokens_est=%d",
            model,
            provider,
            latency_ms,
            len(result) // 4 if result else 0,
        )
        return result
    except Exception as e:
        latency_ms = int((time.monotonic() - _start) * 1000)
        log.warning("AI call failed (%s/%s) after %dms: %s", provider, model, latency_ms, e)
        return None


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
    # Convert role names: "assistant" stays, "user" stays
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


async def _call_groq(
    api_key: str,
    model: str,
    system_prompt: str,
    messages: list[dict],
) -> Optional[str]:
    # Groq uses an OpenAI-compatible API — reuse the openai client with a custom base URL
    try:
        from openai import AsyncOpenAI
    except ImportError:
        log.error("openai package not installed (required for Groq). Run: pip install openai")
        return None

    client = AsyncOpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
    converted = [{"role": "system", "content": system_prompt}]
    converted += [{"role": m["role"], "content": m["content"]} for m in messages]
    response = await client.chat.completions.create(model=model, messages=converted, max_tokens=2048)
    return response.choices[0].message.content if response.choices else None
