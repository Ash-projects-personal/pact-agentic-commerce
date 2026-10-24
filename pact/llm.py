"""Optional language model layer.

When LLM_API_KEY is set, Pact calls an OpenAI compatible chat endpoint to
write negotiation rationales and verification reason text. When no key is set,
or when the call fails for any reason, callers fall back to the deterministic
text they already produced. The app is fully functional with no key at all.
The model never decides outcomes. Negotiation math and verification verdicts
are always computed by the rule based engine so results stay reproducible.
"""

import httpx

from .config import SETTINGS


async def polish(text: str, context: str) -> str:
    """Rewrite a short rationale in a natural voice. Returns input on failure."""
    if not SETTINGS.llm_enabled:
        return text
    prompt = (
        "Rewrite the following short business rationale in a plain, direct "
        "voice. Keep it under 45 words. Keep every number exactly as written. "
        "Do not add claims that are not in the original.\n\n"
        f"Context: {context}\n"
        f"Original: {text}"
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{SETTINGS.llm_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {SETTINGS.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": SETTINGS.llm_model,
                    "messages": [
                        {"role": "system", "content": "You rewrite short texts."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.4,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            out = data["choices"][0]["message"]["content"].strip()
            return out if out else text
    except Exception:
        return text
