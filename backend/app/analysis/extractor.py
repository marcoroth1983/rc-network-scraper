"""OpenRouter integration: extract structured product data from RC-model listings."""

import logging
import re

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
Du analysierst RC-Modell-Kleinanzeigen von rc-network.de.
Extrahiere aus Titel und Beschreibung die Produktdaten.
Gib nur Felder zurück die du sicher identifizieren kannst.

model_type: Grobe Kategorie — "airplane", "helicopter", "multicopter", "glider", "boat", "car"
model_subtype: Spezifische Bauform, z.B.:
  - Flugzeug: hochdecker, tiefdecker, mitteldecker, jet, delta, nurflügler, warbird, trainer, scale
  - Heli: 700, 580, 500, 450, 380, scale
  - Segler: hotliner, f3k, f3b, thermik, hangflug, dlg
  - Boot: rennboot, segelboot, schlepper
  - Auto: buggy, monstertruck, crawler, tourenwagen
drive_type: Antriebsart — "electric", "nitro", "gas", "turbine" (Segler ohne Motor = kein drive_type)
completeness: "RTF", "ARF", "BNF", "PNP", "kit", "parts", "set"
price_euros: Geforderter Preis in Euro als Zahl (nur Zahl, kein Symbol). Null wenn kein Preis erkennbar.
shipping_available: true wenn Versand angeboten wird, false wenn explizit kein Versand ("nur Abholung", "kein Versand"), null wenn unklar.

Für "attributes": extrahiere alle weiteren technischen Daten als key-value Paare
(z.B. wingspan_mm, weight_g, battery, motor, scale, channels, servos_included).
Keys immer englisch, snake_case. Werte als Strings.
"""

_MAX_DESCRIPTION_CHARS = 2000
_REQUEST_TIMEOUT = 15.0


class ListingAnalysis(BaseModel):
    manufacturer: str | None = None
    model_name: str | None = None
    drive_type: str | None = None
    model_type: str | None = None
    model_subtype: str | None = None
    completeness: str | None = None
    price_euros: float | None = None
    shipping_available: bool | None = None
    attributes: dict[str, str] = Field(default_factory=dict)


def _build_user_message(
    title: str,
    description: str,
    price: str | None,
    condition: str | None,
    category: str,
) -> str:
    truncated_desc = description[:_MAX_DESCRIPTION_CHARS]
    parts = [
        f"Titel: {title}",
        f"Kategorie: {category}",
    ]
    if price:
        parts.append(f"Preis: {price}")
    if condition:
        parts.append(f"Zustand: {condition}")
    parts.append(f"Beschreibung:\n{truncated_desc}")
    return "\n".join(parts)


def _make_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=settings.OPENROUTER_API_KEY,
        timeout=_REQUEST_TIMEOUT,
    )


async def _try_analyze(client: AsyncOpenAI, model: str, user_message: str) -> ListingAnalysis | None:
    """Try one model: structured output first, then JSON fallback. Returns None on total failure."""
    # Attempt 1: structured output via beta.chat.completions.parse
    try:
        response = await client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format=ListingAnalysis,
            temperature=0,
        )
        parsed = response.choices[0].message.parsed
        if parsed is not None:
            return parsed
        logger.warning("analyze_listing[%s]: structured output returned None, trying JSON fallback", model)
    except Exception as exc:
        logger.warning("analyze_listing[%s]: structured output failed (%s), trying JSON fallback", model, exc)

    # Attempt 2: plain completion + manual JSON parsing
    try:
        fallback_response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": user_message
                    + "\n\nAntworte ausschließlich mit einem JSON-Objekt gemäß dem Schema.",
                },
            ],
            temperature=0,
        )
        content = fallback_response.choices[0].message.content or ""
        content = content.strip()
        content = re.sub(r"^```[a-z]*\n?", "", content, flags=re.MULTILINE)
        content = re.sub(r"```$", "", content.strip()).strip()
        return ListingAnalysis.model_validate_json(content)
    except Exception as exc:
        logger.warning("analyze_listing[%s]: JSON fallback also failed (%s)", model, exc)
        return None


async def analyze_listing(
    title: str,
    description: str,
    price: str | None,
    condition: str | None,
    category: str,
    model: str | None = None,
) -> ListingAnalysis:
    """Send listing data to LLM via OpenRouter, return structured analysis.

    Returns an empty ListingAnalysis if OPENROUTER_API_KEY is not configured.
    Tries the primary model first; on failure retries with OPENROUTER_FALLBACK_MODEL.
    """
    if not settings.OPENROUTER_API_KEY:
        return ListingAnalysis()

    primary = model or settings.OPENROUTER_MODEL
    user_message = _build_user_message(title, description, price, condition, category)
    client = _make_client()

    result = await _try_analyze(client, primary, user_message)
    if result is not None:
        return result

    # Primary failed — retry with fallback model
    fallback = settings.OPENROUTER_FALLBACK_MODEL
    logger.warning("analyze_listing: primary model %s failed, retrying with fallback %s", primary, fallback)
    result = await _try_analyze(client, fallback, user_message)
    if result is not None:
        return result

    logger.error("analyze_listing: both %s and fallback %s failed, returning empty", primary, fallback)
    return ListingAnalysis()
