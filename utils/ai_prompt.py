from __future__ import annotations

from typing import Optional

# Rough token budget — trim oldest messages when exceeded
TOKEN_BUDGET = 4000
AVG_CHARS_PER_TOKEN = 4

RESPONSE_LENGTH_INSTRUCTIONS = {
    "short":  "Keep all responses very concise — aim for 1–3 sentences. Never exceed ~80 tokens.",
    "medium": "Keep responses moderate — aim for a short paragraph. Stay under ~200 tokens.",
    "long":   "Responses can be detailed and thorough. Use up to ~500 tokens when appropriate.",
}


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // AVG_CHARS_PER_TOKEN)


def build_system_prompt(
    base_prompt: str,
    *,
    language: str = "auto",
    tone: str = "casual",
    long_term_memory: Optional[str] = None,
    response_length: str = "medium",
    markdown_enabled: int = 1,
    markdown_frequency: str = "sometimes",
    emojis_enabled: int = 1,
) -> str:
    """
    Assemble the full system prompt from config + long-term memory.
    """
    # Language is prepended as a hard rule so it overrides character persona instructions
    lang_prefix = ""
    if language and language.strip() and language.strip().lower() != "auto":
        lang_prefix = (
            f"LANGUAGE RULE (highest priority): You MUST always reply in {language.strip()}. "
            f"This applies to every single message, no exceptions, regardless of what language the user writes in.\n\n"
        )

    parts = [lang_prefix + base_prompt.strip()]

    if tone and tone != "casual":
        parts.append(f"Respond in a {tone} tone.")

    # Response length
    length_instruction = RESPONSE_LENGTH_INSTRUCTIONS.get(response_length, RESPONSE_LENGTH_INSTRUCTIONS["medium"])
    parts.append(length_instruction)

    # Markdown
    if not markdown_enabled:
        parts.append("Do not use any Markdown formatting. Plain text only.")
    elif markdown_frequency == "often":
        parts.append("Use rich Markdown formatting freely — bold, italics, headers, lists, code blocks.")
    else:
        parts.append("Use Markdown formatting sparingly — only for code blocks or key emphasis.")

    # Emojis
    if emojis_enabled:
        parts.append("You may use emojis naturally.")
    else:
        parts.append("Do not use any emojis.")

    if long_term_memory:
        parts.append(
            f"\n### What you know about this user:\n{long_term_memory.strip()}"
        )

    return "\n\n".join(parts)


def trim_history(messages: list[dict], budget: int = TOKEN_BUDGET) -> list[dict]:
    """
    Trim the oldest messages from history so the total estimated token count
    stays within `budget`. Always keeps the last message.
    """
    if not messages:
        return messages

    # Count from newest to oldest, keeping as many as fit
    kept = []
    used = 0
    for msg in reversed(messages):
        tokens = _estimate_tokens(msg.get("content", ""))
        if used + tokens > budget and kept:
            break
        kept.append(msg)
        used += tokens

    kept.reverse()
    return kept
