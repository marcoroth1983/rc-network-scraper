"""OpenRouter integration: extract structured product data from RC-model listings."""

import logging
import re

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, model_validator

from app.analysis import model_cascade
from app.analysis.vocabulary import clamp_model_subtype, clamp_model_type
from app.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
Du analysierst RC-Modell-Kleinanzeigen von rc-network.de.
Extrahiere aus Titel und Beschreibung die Produktdaten.
Gib nur Felder zurück die du sicher identifizieren kannst.
Verwende EXAKT die aufgelisteten Werte — keine Varianten, keine Übersetzungen.
Wenn kein passender Wert existiert: null.

model_type — NUR wenn es sich um ein RC-Modell handelt:
  "airplane", "helicopter", "multicopter", "glider", "boat", "car"
  Elektronik, Akkus, Sender, Regler, Motoren, Ersatzteile → model_type = null

model_subtype — wähle EXAKT einen der erlaubten Werte für den jeweiligen model_type:
  airplane:    jet | warbird | trainer | scale | 3d | nurflügler | hochdecker | tiefdecker | mitteldecker | delta | biplane | aerobatic | kit | hotliner | funflyer | speed | pylon
  helicopter:  700 | 580 | 600 | 550 | 500 | 450 | 420 | 380 | scale
  glider:      thermik | hotliner | f3b | f3k | f3j | f5j | f5b | f5k | f3f | f3l | hangflug | dlg | scale | motorglider
  multicopter: quadcopter | hexacopter | fpv
  boat:        rennboot | segelboot | schlepper | submarine | yacht
  car:         buggy | monstertruck | crawler | tourenwagen | truggy | drift

drive_type — EXAKT einen dieser Werte oder null:
  "electric" | "nitro" | "gas" | "turbine"
  (Segler ohne Motor = null)

completeness — EXAKT einen dieser Werte oder null:
  "RTF" | "ARF" | "BNF" | "PNP" | "kit" | "parts" | "set"

price_euros: Geforderter Preis in Euro als Zahl (nur Zahl, kein Symbol). null wenn kein Preis erkennbar.
shipping_available: true wenn Versand angeboten wird, false wenn explizit kein Versand ("nur Abholung", "kein Versand"), null wenn unklar.

Für "attributes": extrahiere alle weiteren technischen Daten als key-value Paare
(z.B. wingspan_mm, weight_g, battery, motor, scale, channels, servos_included).
Keys immer englisch, snake_case. Werte als Strings.
"""

_MAX_DESCRIPTION_CHARS = 2000
_REQUEST_TIMEOUT = 15.0


_DRIVE_TYPES = {"electric", "nitro", "gas", "turbine"}


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

    @model_validator(mode="after")
    def clamp_to_vocabulary(self) -> "ListingAnalysis":
        self.model_type = clamp_model_type(self.model_type)
        self.model_subtype = clamp_model_subtype(self.model_type, self.model_subtype)
        if self.drive_type is not None:
            v = self.drive_type.strip().lower()
            self.drive_type = v if v in _DRIVE_TYPES else None
        return self


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
