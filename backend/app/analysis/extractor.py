"""OpenRouter integration: extract structured product data from RC-model listings."""

import logging
import re

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.analysis import model_cascade
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


async def _try_analyze(client: AsyncOpenAI, model: str, user_message: str) -> tuple[ListingAnalysis | None, str | None]:
    """Try one model: structured output first, then JSON fallback.

    Returns (result, None) on success, (None, error_msg) on total failure.
    The error_msg is used by the caller to update the DB failure tracking.
    """
    last_error: str | None = None

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
            logger.info("LLM [%s] structured-output: OK", model)
            return parsed, None
        last_error = "structured-output returned None"
        logger.warning("LLM [%s] %s — trying JSON fallback", model, last_error)
    except Exception as exc:
        last_error = f"structured-output: {exc}"
        logger.warning("LLM [%s] %s — trying JSON fallback", model, last_error)

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
        result = ListingAnalysis.model_validate_json(content)
        logger.info("LLM [%s] json-fallback: OK", model)
        return result, None
    except Exception as exc:
        last_error = f"json-fallback: {exc}"
        logger.warning("LLM [%s] %s", model, last_error)
        return None, last_error


async def analyze_listing(
    title: str,
    description: str,
    price: str | None,
    condition: str | None,
    category: str,
    listing_id: int | None = None,
    model: str | None = None,
) -> ListingAnalysis:
    """Send listing data to LLM via OpenRouter, return structured analysis.

    Strategy per call:
      1. Iterate through the free-tier cascade loaded from the DB (llm_models).
         First model that returns valid JSON wins; per-model success/failure is
         recorded so repeatedly-broken models auto-disable for 1h.
      2. If ALL free models fail (or cascade empty), fall back to
         OPENROUTER_FALLBACK_MODEL (paid, from env — never tracked in DB).
      3. If that also fails, return an empty ListingAnalysis.

    When `model` is passed explicitly (e.g. from the backfill script), the
    cascade is bypassed — that single model is tried, then the paid fallback.

    Returns an empty ListingAnalysis if OPENROUTER_API_KEY is not configured.
    """
    if not settings.OPENROUTER_API_KEY:
        return ListingAnalysis()

    id_tag = f"id={listing_id} " if listing_id is not None else ""
    title_short = title[:60]
    user_message = _build_user_message(title, description, price, condition, category)
    client = _make_client()

    # Build the ordered model list: explicit override OR DB cascade.
    if model is not None:
        candidates = [model]
        track_in_db = False
    else:
        candidates = await model_cascade.load_cascade()
        track_in_db = True
        if not candidates:
            logger.warning("LLM: cascade empty — jumping straight to paid fallback")

    logger.info("LLM analyze: %s\"%s\" — cascade=%s", id_tag, title_short, candidates)
    for candidate in candidates:
        result, err = await _try_analyze(client, candidate, user_message)
        if result is not None:
            if track_in_db:
                await model_cascade.record_success(candidate)
            logger.info("LLM SUCCESS [%s]: %s\"%s\"", candidate, id_tag, title_short)
            return result
        if track_in_db and err is not None:
            await model_cascade.record_failure(candidate, err)
        logger.warning("LLM [%s] exhausted — next in cascade", candidate)

    # Paid safety-net (never tracked in DB; it's the escape hatch)
    fallback = settings.OPENROUTER_FALLBACK_MODEL
    if fallback:
        logger.warning(
            "LLM: free cascade exhausted (%d models) — trying paid fallback [%s] for %s\"%s\"",
            len(candidates), fallback, id_tag, title_short,
        )
        result, _ = await _try_analyze(client, fallback, user_message)
        if result is not None:
            logger.info("LLM SUCCESS [%s] (paid fallback): %s\"%s\"", fallback, id_tag, title_short)
            return result

    logger.error(
        "LLM FAIL: %d free + fallback [%s] all failed for %s\"%s\" — returning empty",
        len(candidates), fallback, id_tag, title_short,
    )
    return ListingAnalysis()
