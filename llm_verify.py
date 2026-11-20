"""LLM-powered match verification — optional fallback.

Only called when the strict regex matcher gave up but a platform's search
returned candidates. We hand the source product + candidate titles to Gemini
and ask which (if any) is the same product.

Enable by exporting `GEMINI_API_KEY`. Falls through silently when absent.
"""
import json
import os
import re
from pathlib import Path
from typing import Optional


def _load_env():
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_env()


_PROMPT = """You are verifying product matches for a price comparison tool.

SOURCE PRODUCT (from Amazon India):
  brand: {brand}
  model: {model}
  model_code: {model_code}
  category: {category}
  key attributes: {attrs}
  full title: {title}

CANDIDATES from {platform}:
{candidates}

Task: which candidate (if any) is the SAME product as the source?

Rules:
- Match is strict: same brand, same model, same key attributes (RAM+storage for phones, screen size and model code for TVs, colour and model for apparel/sneakers).
- A different colour, different storage size, a different generation, or a different variant = NOT the same product.
- Return ONLY a JSON object: {{"match_index": N}} where N is 0-based index of the matching candidate, or -1 if none matches.

Examples:
  Source "Samsung Galaxy S24 Ultra 256GB" vs candidate "Samsung Galaxy S24 Ultra 512GB" → NOT same (storage differs).
  Source "Samsung Galaxy S24 Ultra 256GB" vs candidate "Samsung Galaxy S24 Ultra 5G (256 GB Storage, 12 GB RAM)" → SAME.
  Source "Sony BRAVIA 2M2 K-55S25BM2 55 inch" vs candidate "Sony BRAVIA 2 II 55 inch K-55S25M2" → SAME (same product, code variant).
  Source "Nike Revolution 8" vs candidate "Nike Revolution 7" → NOT same (different generation)."""


def _format_candidates(candidates: list[dict]) -> str:
    lines = []
    for i, c in enumerate(candidates):
        title = (c.get("title") or "").strip()
        snippet = (c.get("snippet") or "").strip()
        bits = [f"  [{i}] {title[:200]}"]
        if snippet:
            bits.append(f"       snippet: {snippet[:200]}")
        lines.append("\n".join(bits))
    return "\n".join(lines)


def verify_match(
    product: dict, candidates: list[dict], platform: str
) -> Optional[int]:
    """Return the index of the matching candidate, or None if no match / LLM unavailable."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or not candidates:
        return None

    try:
        from google import genai
    except ImportError:
        return None

    attrs_parts = []
    for k in ("ram", "storage", "screen_size", "colour"):
        v = product.get(k)
        if v:
            attrs_parts.append(f"{k}={v}")
    attrs = ", ".join(attrs_parts) or "(none)"

    prompt = _PROMPT.format(
        brand=product.get("brand", ""),
        model=product.get("model", ""),
        model_code=product.get("model_code") or "(none)",
        category=product.get("category", ""),
        attrs=attrs,
        title=product.get("title", "")[:300],
        platform=platform,
        candidates=_format_candidates(candidates),
    )

    try:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        text = (resp.text or "").strip()
        m = re.search(r'"match_index"\s*:\s*(-?\d+)', text)
        if not m:
            m = re.search(r'\b(-?\d+)\b', text)
        if m:
            idx = int(m.group(1))
            if 0 <= idx < len(candidates):
                return idx
    except Exception:
        return None
    return None
