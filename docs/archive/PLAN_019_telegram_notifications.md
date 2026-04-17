# PLAN 019 — Telegram Notifications per User

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Jeder User kann seinen Telegram-Account via Profil verknüpfen und erhält per User konfigurierbare Benachrichtigungen zu (a) neuen Treffern seiner aktiven gespeicherten Suchen und (b) Statusänderungen an Inseraten in seiner Merkliste — strikt pro User isoliert.

**Architecture:** Das Projekt hat bereits eine Notification-Plugin-Architektur: `app/notifications/registry.py` mit `NotificationPlugin`-ABC, `MatchResult`-Dataclass, und `search_matcher.check_new_matches()` wird bereits nach jedem Scrape in `scrape_runner.py:141` aufgerufen und dispatched an alle registrierten Plugins. `LogPlugin` ist bereits registriert. Wir bauen (1) einen **`TelegramPlugin`** der in die Registry eingeklinkt wird — dann fließen neue Such-Treffer automatisch; (2) einen **separaten APScheduler-Job für Favoriten-Statusänderungen** (kein existierendes Äquivalent); (3) den Linking-Flow per Webhook + Deep-Link; (4) Per-User-Prefs in eigener Tabelle; (5) ein kleines Frontend-Panel im Profil.

**Tech Stack:** Python 3.12 + FastAPI + httpx (Telegram API) + SQLAlchemy async + APScheduler + React/TypeScript.

**Breaking Changes:** No — neue Tabellen/Spalten sind alle idempotent (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ADD COLUMN IF NOT EXISTS`). Bestehende Notification-Plugin-Architektur wird erweitert, nicht ersetzt. `LogPlugin` bleibt registriert.

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved (after revise) | 2026-04-15 |
| Human | approved | 2026-04-16 |

---

## Context & Requirements (confirmed with Human)

1. **Linking-Flow:** Deep-Link. User klickt „Mit Telegram verbinden" → Backend generiert Einmal-Token (15 min gültig) → Frontend öffnet `https://t.me/<BOT_USERNAME>?start=<token>` → User drückt „Start" → Telegram POSTet `/start <token>` an unseren Webhook → Backend mapped `chat_id` auf `user_id`.

2. **Favoriten-Status-Trigger (4, pro User togglebar):**
   - `fav_sold` — Verkauft-Flag `false → true`
   - `fav_price` — `price_numeric` geändert
   - `fav_deleted` — Inserat vom Original nicht mehr auffindbar (detected via `scraped_at` älter als 3 Tage)
   - `fav_indicator` — `price_indicator` geändert

3. **Noise-Control Suchergebnisse:** Digest je Suche. Trigger fällt automatisch nach jedem Scrape-Lauf (Post-Scrape-Hook ruft `check_new_matches` auf → Plugin-Dispatch). LLM-Wait-Logik nicht nötig — die Listings sind zum Matching-Zeitpunkt noch nicht zwingend LLM-analysiert, aber das Matching nutzt ohnehin keine LLM-Felder (`build_text_filter` + `filter_by_distance` arbeiten auf Titel/Beschreibung/Tags/Geo).

4. **Transport:** Webhook-only. `POST /api/telegram/webhook` mit `X-Telegram-Bot-Api-Secret-Token`. Lokal kein Telegram-Betrieb (User lehnt Polling ab — falls benötigt, tunneln via ngrok).

## Existing Infrastructure to Reuse

Verified by grep before writing this plan:

- `backend/app/notifications/base.py` — `NotificationPlugin(ABC)` mit `is_configured()` + `send(match: MatchResult) -> bool`
- `backend/app/notifications/registry.py` — `notification_registry` Singleton, `register(plugin)` + `dispatch(match)`; iteriert alle Plugins, ruft `is_configured()` und `send()`, fängt Exceptions pro Plugin
- `backend/app/notifications/log_plugin.py` — existierendes Referenz-Plugin, wird in `main.py:44` registriert
- `backend/app/services/search_matcher.py` — `check_new_matches(session, new_ids)` lädt aktive Searches, matched gegen neue Listings, dedupliziert via `search_notifications` Tabelle, ruft `notification_registry.dispatch(match_result)` pro neuer Match-Gruppe. Ausnahme-Isolation pro Search via `session.begin_nested()` + try/except — bereits vorbildlich
- `backend/app/services/listing_filter.py` — `build_text_filter(search)` + `filter_by_distance(listings, plz, max_distance, session)` für Reuse
- `backend/app/scrape_runner.py:141` — ruft `check_new_matches` automatisch nach jedem Scrape-Update-Job (alle 30 min)
- `backend/app/models.py:110` — `SearchNotification` Tabelle + UniqueConstraint `(saved_search_id, listing_id)` → verhindert Doppel-Benachrichtigung des gleichen Listings für die gleiche Suche. Eigener `last_notified_at`-Cursor ist daher nicht nötig
- `backend/app/api/admin.py:14` — korrektes Pattern für nested router (`APIRouter(prefix="/admin")`, gemountet via `router.include_router(admin_router)` in `routes.py`)

Das spart ~150 LOC und eliminiert Reviewer-Blocker #2 und #5.

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────────┐
│ User Web-UI (Profil)                                               │
│  ┌─ "Mit Telegram verbinden" ────┐  ┌─ Notification Toggles ─────┐ │
│  │ POST /api/telegram/link        │  │  [x] Neue Suchtreffer     │ │
│  │  → {deeplink, expires_at}      │  │  [x] Verkauft              │ │
│  └────────────────────────────────┘  │  [x] Preis                 │ │
│                                      │  [ ] Gelöscht              │ │
│                                      │  [x] Preisindikator        │ │
│                                      └────────────────────────────┘ │
└──────────────────┬─────────────────────────────────────────────────┘
                   │
                   ▼
  ┌────────────────────────────────────────────────────────────────┐
  │ Backend FastAPI                                                │
  │  /api/telegram/link, /unlink, /prefs  (via api/routes.py)      │
  │  /api/telegram/webhook                (mounted on app)         │
  └──────────────────┬──────────────────────────────────────────────┘
                     │
     ┌───────────────┼────────────────┐
     ▼               ▼                ▼
  ┌─────────┐  ┌─────────────────┐  ┌──────────────────────────┐
  │ bot.py  │  │ link.py         │  │ plugin.py  ← NEW          │
  │ httpx → │  │ create_token    │  │  class TelegramPlugin     │
  │ telegram│  │ redeem_token    │  │    extends                │
  │ api     │  │ unlink_user     │  │    NotificationPlugin     │
  └─────────┘  └─────────────────┘  └─────────┬────────────────┘
                                              │
                              ┌───────────────┼────────────────┐
                              ▼                                ▼
                  ┌────────────────────┐          ┌───────────────────────┐
                  │ NEW-RESULTS path:  │          │ FAV-STATUS path:      │
                  │ - plugin.send()    │          │ - APScheduler job     │
                  │   auto-called from │          │   every 60 min        │
                  │   check_new_matches│          │ - scans user_favorites│
                  │   via registry     │          │ - diffs vs last_known │
                  │   (existing flow)  │          │ - calls bot.send      │
                  └────────────────────┘          └───────────────────────┘
```

## Data Model

All migrations go into `backend/app/db.py` inside `init_db()`, following existing idempotent-ALTER pattern. **No new column on `listings`** — we use existing `scraped_at` as the "last-seen" timestamp (the scraper already writes it on every observation). **No `last_notified_at` on `saved_searches`** — the existing `search_notifications` table handles dedup.

```sql
-- 1) Telegram link on users
ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_chat_id BIGINT;
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_telegram_chat_id
  ON users (telegram_chat_id) WHERE telegram_chat_id IS NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_linked_at TIMESTAMPTZ;

-- 2) Single-use linking tokens (self-cleanup: DELETE WHERE expires_at < now() - '7 days')
CREATE TABLE IF NOT EXISTS telegram_link_tokens (
    token       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_telegram_link_tokens_user ON telegram_link_tokens (user_id);

-- 3) Per-user notification preferences (5 booleans, defaults TRUE)
CREATE TABLE IF NOT EXISTS user_notification_prefs (
    user_id            INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    new_search_results BOOLEAN NOT NULL DEFAULT TRUE,
    fav_sold           BOOLEAN NOT NULL DEFAULT TRUE,
    fav_price          BOOLEAN NOT NULL DEFAULT TRUE,
    fav_deleted        BOOLEAN NOT NULL DEFAULT TRUE,
    fav_indicator      BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 4) Favorite snapshot columns (to diff status changes between sweeps)
ALTER TABLE user_favorites ADD COLUMN IF NOT EXISTS last_known_is_sold BOOLEAN;
ALTER TABLE user_favorites ADD COLUMN IF NOT EXISTS last_known_price_numeric NUMERIC(10,2);
ALTER TABLE user_favorites ADD COLUMN IF NOT EXISTS last_known_price_indicator VARCHAR(20);
ALTER TABLE user_favorites ADD COLUMN IF NOT EXISTS last_known_scraped_at TIMESTAMPTZ;
```

Rationale:
- `BIGINT` — Telegram chat IDs can exceed INT range
- Partial unique index (not UNIQUE constraint) — allows multiple NULLs, one linked chat per user
- `last_known_scraped_at` — snapshot of the listing's `scraped_at` at notification time; if the current `scraped_at` is >3 days old AND the snapshot was within 3 days, we classify as "deleted"
- Token table cleanup is a one-line DELETE tacked onto the fav-status sweep (see Task 10)

## Configuration (env)

```
# Required — entire Telegram subsystem disabled if any of these are empty
TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_USERNAME=          # e.g. rcn_scout_bot (without @, used for deep link)
TELEGRAM_WEBHOOK_SECRET=        # random ≥32 chars

# Optional tuning
TELEGRAM_LINK_TOKEN_TTL_MIN=15
TELEGRAM_DIGEST_TOP_N=5
TELEGRAM_FAV_SWEEP_INTERVAL_MIN=60
TELEGRAM_FAV_DELETED_DAYS=3
```

`settings.telegram_enabled` property returns True only when all three required values are non-empty. Every endpoint, job registration, and the `setWebhook` startup call gates on this. When disabled: zero HTTPS calls, zero DB access from telegram module, all `/api/telegram/*` endpoints return 404.

## Logging / Observability

Named loggers per submodule at INFO level. Expected events:

- Startup enabled: `telegram: bot configured, webhook registered at <url>`
- Startup disabled: `telegram: disabled (missing TELEGRAM_BOT_TOKEN or username or webhook_secret)`
- Link created: `telegram.link: token=abc... for user_id=42 expires_at=...`
- Link redeemed: `telegram.link: redeemed token=abc... user_id=42 chat_id=12345`
- Link invalid: `telegram.link: invalid/expired token chat_id=12345`
- Webhook bad secret: `telegram.webhook: bad/missing secret header`
- Outbound sent: `telegram.bot: sent chat_id=12345 bytes=234`
- Outbound failed 403 (blocked): `telegram.bot: chat_id=12345 blocked by user — clearing telegram_chat_id`
- Plugin match sent: `telegram.plugin: search_id=12 user_id=42 listings=3 sent ok`
- Plugin match skipped (pref disabled): `telegram.plugin: search_id=12 user_id=42 skipped (new_search_results=false)`
- Plugin match skipped (no chat): `telegram.plugin: search_id=12 user_id=42 skipped (no telegram_chat_id)`
- Fav-sweep per event: `telegram.sweep.fav: user_id=42 listing_id=123 triggers=[sold,price]`
- Fav-sweep errors: `telegram.sweep.fav: user_id=42 listing_id=123 FAILED: <exc>`

## Security

1. **Webhook secret:** Telegram supports `setWebhook(secret_token=...)` that forwards the value in `X-Telegram-Bot-Api-Secret-Token`. We verify each inbound — mismatch → 401.
2. **Link tokens:** `secrets.token_urlsafe(24)` (~32 chars), single-use via `used_at`, 15 min TTL in DB.
3. **Per-user isolation:** Every SQL query in sweep/plugin/API joins on `user_id`. `telegram_chat_id` partial-unique-index prevents one chat linked to multiple users. Webhook handler never resolves chat → user by chat_id alone — only via valid token.
4. **Blocked-by-user handling:** `bot.send_message` detects 403 "blocked by user" / "user is deactivated" and clears `telegram_chat_id` automatically (no manual cleanup needed).
5. **No admin override:** Telegram endpoints are strictly self-service per user.

## Files to Create / Modify

**Create:**
- `backend/app/telegram/__init__.py`
- `backend/app/telegram/bot.py` — outbound `send_message(chat_id, text)`, returns ok-bool + auto-unlinks on 403
- `backend/app/telegram/link.py` — `create_token(user_id)`, `redeem_token(token, chat_id)`, `unlink_user(user_id)`
- `backend/app/telegram/prefs.py` — `get_prefs(user_id)`, `set_prefs(user_id, **partial)` with upsert
- `backend/app/telegram/plugin.py` — `TelegramPlugin(NotificationPlugin)` for new-results
- `backend/app/telegram/fav_sweep.py` — APScheduler job `run_fav_status_sweep()`
- `backend/app/telegram/webhook.py` — `POST /api/telegram/webhook` (direct mount on app)
- `backend/app/api/telegram.py` — user-facing `/api/telegram/{link,unlink,prefs}` (mounted via routes.py)
- `backend/tests/test_telegram_bot.py`
- `backend/tests/test_telegram_link.py`
- `backend/tests/test_telegram_prefs.py`
- `backend/tests/test_telegram_webhook.py`
- `backend/tests/test_telegram_api.py`
- `backend/tests/test_telegram_plugin.py`
- `backend/tests/test_telegram_fav_sweep.py`
- `frontend/src/components/TelegramPanel.tsx`
- `frontend/src/components/__tests__/TelegramPanel.test.tsx`

**Modify:**
- `backend/app/db.py` — add migrations in `init_db()`
- `backend/app/config.py` — add `TELEGRAM_*` settings + `telegram_enabled` property
- `backend/app/main.py` — register `TelegramPlugin`, add fav-sweep scheduler job, call `setWebhook` on startup (all gated on `telegram_enabled`)
- `backend/app/api/auth.py` — include `telegram_chat_id` + `telegram_linked_at` in `/auth/me` response
- `backend/app/api/routes.py` — mount user-facing telegram router
- `frontend/src/api/client.ts` — `linkTelegram`, `unlinkTelegram`, `getNotificationPrefs`, `updateNotificationPrefs`
- `frontend/src/types/api.ts` — `NotificationPrefs`, `TelegramLinkResponse`; extend `User` interface
- `frontend/src/hooks/useAuth.ts` — pick up new fields from `/auth/me`
- `frontend/src/pages/ProfilePage.tsx` — mount `<TelegramPanel />`

## Steps

Each step has a status field. Allowed values: `open | implemented | reviewed | approved`. Implementer updates the field in-place as work progresses.

---

### Task 1: DB migrations — `status: approved`

**Files:**
- Modify: `backend/app/db.py` — append inside `init_db()` after existing migrations

**Step 1: Add migrations**

```python
# PLAN-019: Telegram notifications
await conn.execute(text(
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_chat_id BIGINT"
))
await conn.execute(text("""
    CREATE UNIQUE INDEX IF NOT EXISTS ux_users_telegram_chat_id
    ON users (telegram_chat_id) WHERE telegram_chat_id IS NOT NULL
"""))
await conn.execute(text(
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_linked_at TIMESTAMPTZ"
))
await conn.execute(text("""
    CREATE TABLE IF NOT EXISTS telegram_link_tokens (
        token       TEXT PRIMARY KEY,
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at  TIMESTAMPTZ NOT NULL,
        used_at     TIMESTAMPTZ
    )
"""))
await conn.execute(text(
    "CREATE INDEX IF NOT EXISTS ix_telegram_link_tokens_user ON telegram_link_tokens (user_id)"
))
await conn.execute(text("""
    CREATE TABLE IF NOT EXISTS user_notification_prefs (
        user_id            INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        new_search_results BOOLEAN NOT NULL DEFAULT TRUE,
        fav_sold           BOOLEAN NOT NULL DEFAULT TRUE,
        fav_price          BOOLEAN NOT NULL DEFAULT TRUE,
        fav_deleted        BOOLEAN NOT NULL DEFAULT TRUE,
        fav_indicator      BOOLEAN NOT NULL DEFAULT TRUE,
        updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
    )
"""))
await conn.execute(text(
    "ALTER TABLE user_favorites ADD COLUMN IF NOT EXISTS last_known_is_sold BOOLEAN"
))
await conn.execute(text(
    "ALTER TABLE user_favorites ADD COLUMN IF NOT EXISTS last_known_price_numeric NUMERIC(10,2)"
))
await conn.execute(text(
    "ALTER TABLE user_favorites ADD COLUMN IF NOT EXISTS last_known_price_indicator VARCHAR(20)"
))
await conn.execute(text(
    "ALTER TABLE user_favorites ADD COLUMN IF NOT EXISTS last_known_scraped_at TIMESTAMPTZ"
))
```

**Step 2: Verify**

Run: `docker compose restart backend && sleep 5 && docker compose exec -T db psql -U rcscout -d rcscout -c "\d user_notification_prefs; \d telegram_link_tokens"`
Expected: both tables present with all columns.

**Step 3: Commit**

```bash
git add backend/app/db.py
git commit -m "feat(db): Telegram notification schema (PLAN-019 task 1)"
```

---

### Task 2: Config & settings — `status: approved`

**Depends on:** Task 1

**Files:**
- Modify: `backend/app/config.py`

**Step 1: Add settings**

Append inside the `Settings` class after existing `LLM_CASCADE_*` block:

```python
# Telegram notifications — disabled entirely when any required field is empty
TELEGRAM_BOT_TOKEN: str = ""
TELEGRAM_BOT_USERNAME: str = ""
TELEGRAM_WEBHOOK_SECRET: str = ""
TELEGRAM_LINK_TOKEN_TTL_MIN: int = 15
TELEGRAM_DIGEST_TOP_N: int = 5
TELEGRAM_FAV_SWEEP_INTERVAL_MIN: int = 60
TELEGRAM_FAV_DELETED_DAYS: int = 3

@property
def telegram_enabled(self) -> bool:
    return bool(
        self.TELEGRAM_BOT_TOKEN
        and self.TELEGRAM_BOT_USERNAME
        and self.TELEGRAM_WEBHOOK_SECRET
    )
```

**Step 2: Commit**

```bash
git add backend/app/config.py
git commit -m "feat(config): Telegram settings (PLAN-019 task 2)"
```

---

### Task 3: Outbound bot client — `status: approved`

**Depends on:** Task 2

**Files:**
- Create: `backend/app/telegram/__init__.py` (empty)
- Create: `backend/app/telegram/bot.py`
- Test: `backend/tests/test_telegram_bot.py`

**Step 1: Write failing tests**

Pattern note: use `monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "TEST")` rather than env reload — consistent with PLAN-018 test patterns.

```python
import pytest
import respx
from app.config import settings
from app.telegram import bot


@pytest.mark.asyncio
async def test_send_message_returns_true_on_200(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "TESTTOKEN")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "bot")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    with respx.mock(base_url="https://api.telegram.org") as mock:
        route = mock.post("/botTESTTOKEN/sendMessage").respond(200, json={"ok": True})
        ok = await bot.send_message(chat_id=12345, text="hi")
        assert ok is True
        assert route.called


@pytest.mark.asyncio
async def test_send_message_403_blocked_clears_chat_id(monkeypatch, db_user_linked):
    """403 blocked should auto-clear user.telegram_chat_id."""
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "TESTTOKEN")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "bot")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    with respx.mock(base_url="https://api.telegram.org") as mock:
        mock.post("/botTESTTOKEN/sendMessage").respond(
            403, json={"ok": False, "description": "Forbidden: bot was blocked by the user"}
        )
        ok = await bot.send_message(chat_id=db_user_linked.chat_id, text="hi")
        assert ok is False
    # Assert chat_id was cleared in DB
    from app.db import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as s:
        row = await s.execute(text("SELECT telegram_chat_id FROM users WHERE id = :u"), {"u": db_user_linked.user_id})
        assert row.scalar() is None


@pytest.mark.asyncio
async def test_send_message_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    ok = await bot.send_message(chat_id=12345, text="hi")
    assert ok is False


@pytest.mark.asyncio
async def test_send_message_other_errors_do_not_clear_chat_id(monkeypatch, db_user_linked):
    """Non-403 errors (500, network) must NOT clear chat_id — transient."""
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "TESTTOKEN")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "bot")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    with respx.mock(base_url="https://api.telegram.org") as mock:
        mock.post("/botTESTTOKEN/sendMessage").respond(500, json={"ok": False})
        ok = await bot.send_message(chat_id=db_user_linked.chat_id, text="hi")
        assert ok is False
    from app.db import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as s:
        row = await s.execute(text("SELECT telegram_chat_id FROM users WHERE id = :u"), {"u": db_user_linked.user_id})
        assert row.scalar() == db_user_linked.chat_id  # unchanged
```

Fixture `db_user_linked` creates a user with a linked `telegram_chat_id=12345` (in conftest.py).

**Step 2: Implement**

`backend/app/telegram/bot.py`:

```python
"""Outbound Telegram Bot API client."""

from __future__ import annotations
import logging
import httpx
from sqlalchemy import text

from app.config import settings
from app.db import AsyncSessionLocal

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0
_BLOCKED_FRAGMENTS = ("blocked by the user", "bot was blocked", "user is deactivated")


async def send_message(
    chat_id: int,
    text_body: str,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = False,
) -> bool:
    """Send a message. Returns True on 200. On 403-blocked, clears user.telegram_chat_id."""
    if not settings.telegram_enabled:
        return False

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text_body,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        logger.warning("telegram.bot: network error chat_id=%d err=%s", chat_id, exc)
        return False

    if resp.status_code == 200:
        logger.info("telegram.bot: sent chat_id=%d bytes=%d", chat_id, len(text_body))
        return True

    body = resp.text[:300]
    if resp.status_code == 403 and any(frag in body.lower() for frag in _BLOCKED_FRAGMENTS):
        logger.info("telegram.bot: chat_id=%d blocked by user — clearing telegram_chat_id", chat_id)
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("UPDATE users SET telegram_chat_id = NULL, telegram_linked_at = NULL WHERE telegram_chat_id = :cid"),
                {"cid": chat_id},
            )
            await session.commit()
    else:
        logger.warning("telegram.bot: send FAILED chat_id=%d status=%d body=%s", chat_id, resp.status_code, body)
    return False
```

**Step 3: Verify**

Run: `docker compose exec backend pytest tests/test_telegram_bot.py -v`
Expected: 4 passed.

**Step 4: Commit**

```bash
git add backend/app/telegram/__init__.py backend/app/telegram/bot.py backend/tests/test_telegram_bot.py
git commit -m "feat(telegram): outbound bot client with blocked-auto-unlink (PLAN-019 task 3)"
```

---

### Task 4: Link token module — `status: approved`

**Depends on:** Task 1, Task 2

**Files:**
- Create: `backend/app/telegram/link.py`
- Test: `backend/tests/test_telegram_link.py`

**Step 1: Write failing tests**

```python
import pytest
from datetime import datetime, timezone
from app.telegram import link
from app.db import AsyncSessionLocal
from sqlalchemy import text


@pytest.mark.asyncio
async def test_create_token_distinct(db_user):
    t1 = await link.create_token(user_id=db_user.id)
    t2 = await link.create_token(user_id=db_user.id)
    assert t1.token != t2.token
    assert len(t1.token) >= 32


@pytest.mark.asyncio
async def test_redeem_valid_token_sets_chat_id(db_user):
    t = await link.create_token(user_id=db_user.id)
    uid = await link.redeem_token(t.token, chat_id=999)
    assert uid == db_user.id
    # Second redemption fails (single-use)
    assert await link.redeem_token(t.token, chat_id=999) is None


@pytest.mark.asyncio
async def test_redeem_expired_token_returns_none(db_user):
    t = await link.create_token(user_id=db_user.id)
    async with AsyncSessionLocal() as s:
        await s.execute(
            text("UPDATE telegram_link_tokens SET expires_at = now() - interval '1 minute' WHERE token = :t"),
            {"t": t.token},
        )
        await s.commit()
    assert await link.redeem_token(t.token, chat_id=999) is None


@pytest.mark.asyncio
async def test_redeem_unknown_token(db_user):
    assert await link.redeem_token("does-not-exist", chat_id=1) is None


@pytest.mark.asyncio
async def test_unlink_clears_chat_id(db_user_linked):
    await link.unlink_user(db_user_linked.user_id)
    async with AsyncSessionLocal() as s:
        row = await s.execute(text("SELECT telegram_chat_id FROM users WHERE id = :u"), {"u": db_user_linked.user_id})
        assert row.scalar() is None
```

**Step 2: Implement**

`backend/app/telegram/link.py`:

```python
"""Telegram deep-link token lifecycle: create, redeem, unlink."""

from __future__ import annotations
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from app.config import settings
from app.db import AsyncSessionLocal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LinkToken:
    token: str
    expires_at: datetime


async def create_token(user_id: int) -> LinkToken:
    token = secrets.token_urlsafe(24)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.TELEGRAM_LINK_TOKEN_TTL_MIN)
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                INSERT INTO telegram_link_tokens (token, user_id, expires_at)
                VALUES (:t, :uid, :exp)
            """),
            {"t": token, "uid": user_id, "exp": expires_at},
        )
        await session.commit()
    logger.info("telegram.link: token=%s... for user_id=%d expires_at=%s", token[:6], user_id, expires_at.isoformat())
    return LinkToken(token=token, expires_at=expires_at)


async def redeem_token(token: str, chat_id: int) -> int | None:
    """Single-use redemption. Returns user_id on success, None otherwise."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        row = await session.execute(
            text("SELECT user_id, used_at, expires_at FROM telegram_link_tokens WHERE token = :t"),
            {"t": token},
        )
        r = row.one_or_none()
        if r is None:
            logger.info("telegram.link: unknown token chat_id=%d", chat_id)
            return None
        user_id, used_at, expires_at = r
        if used_at is not None or expires_at < now:
            logger.info("telegram.link: invalid/expired token user_id=%d chat_id=%d", user_id, chat_id)
            return None

        await session.execute(
            text("UPDATE telegram_link_tokens SET used_at = :now WHERE token = :t"),
            {"now": now, "t": token},
        )
        await session.execute(
            text("UPDATE users SET telegram_chat_id = :cid, telegram_linked_at = :now WHERE id = :uid"),
            {"cid": chat_id, "now": now, "uid": user_id},
        )
        await session.commit()
    logger.info("telegram.link: redeemed token=%s... user_id=%d chat_id=%d", token[:6], user_id, chat_id)
    return user_id


async def unlink_user(user_id: int) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("UPDATE users SET telegram_chat_id = NULL, telegram_linked_at = NULL WHERE id = :uid"),
            {"uid": user_id},
        )
        await session.commit()
    logger.info("telegram.link: unlinked user_id=%d", user_id)


async def cleanup_expired_tokens(older_than_days: int = 7) -> int:
    """Delete tokens whose expires_at is older than the threshold. Called from fav sweep."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("DELETE FROM telegram_link_tokens WHERE expires_at < now() - (:d || ' days')::interval"),
            {"d": str(older_than_days)},
        )
        await session.commit()
    return result.rowcount or 0
```

**Step 3: Verify + commit**

Run: `docker compose exec backend pytest tests/test_telegram_link.py -v`
Expected: 5 passed.

```bash
git add backend/app/telegram/link.py backend/tests/test_telegram_link.py
git commit -m "feat(telegram): link token lifecycle (PLAN-019 task 4)"
```

---

### Task 5: Preferences module — `status: approved`

**Depends on:** Task 1

**Files:**
- Create: `backend/app/telegram/prefs.py`
- Test: `backend/tests/test_telegram_prefs.py`

**Step 1: Write failing tests**

```python
import pytest
from app.telegram import prefs


@pytest.mark.asyncio
async def test_get_defaults_all_true(db_user):
    p = await prefs.get_prefs(db_user.id)
    assert all([p.new_search_results, p.fav_sold, p.fav_price, p.fav_deleted, p.fav_indicator])


@pytest.mark.asyncio
async def test_partial_update_keeps_unspecified_fields(db_user):
    await prefs.set_prefs(db_user.id, fav_sold=False)
    p = await prefs.get_prefs(db_user.id)
    assert p.fav_sold is False
    assert p.fav_price is True  # unchanged
    assert p.new_search_results is True


@pytest.mark.asyncio
async def test_idempotent_upsert(db_user):
    await prefs.set_prefs(db_user.id, fav_sold=False)
    await prefs.set_prefs(db_user.id, fav_sold=True)
    p = await prefs.get_prefs(db_user.id)
    assert p.fav_sold is True


@pytest.mark.asyncio
async def test_set_empty_partial_returns_current(db_user):
    p1 = await prefs.get_prefs(db_user.id)
    p2 = await prefs.set_prefs(db_user.id)
    assert p1 == p2
```

**Step 2: Implement**

`backend/app/telegram/prefs.py`:

```python
"""Per-user notification prefs — 5 booleans, defaults TRUE."""

from __future__ import annotations
from dataclasses import dataclass
from sqlalchemy import text
from app.db import AsyncSessionLocal


@dataclass(frozen=True)
class NotificationPrefs:
    user_id: int
    new_search_results: bool
    fav_sold: bool
    fav_price: bool
    fav_deleted: bool
    fav_indicator: bool


async def get_prefs(user_id: int) -> NotificationPrefs:
    """Return prefs; creates default row if missing (upsert no-op then SELECT)."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("INSERT INTO user_notification_prefs (user_id) VALUES (:uid) ON CONFLICT DO NOTHING"),
            {"uid": user_id},
        )
        result = await session.execute(
            text("""
                SELECT new_search_results, fav_sold, fav_price, fav_deleted, fav_indicator
                FROM user_notification_prefs WHERE user_id = :uid
            """),
            {"uid": user_id},
        )
        r = result.one()
        await session.commit()
    return NotificationPrefs(user_id, r[0], r[1], r[2], r[3], r[4])


async def set_prefs(user_id: int, **partial: bool | None) -> NotificationPrefs:
    """Partial update: only fields passed as non-None are written."""
    updates = []
    params: dict = {"uid": user_id}
    for field in ("new_search_results", "fav_sold", "fav_price", "fav_deleted", "fav_indicator"):
        val = partial.get(field)
        if val is not None:
            updates.append(f"{field} = :{field}")
            params[field] = val
    if not updates:
        return await get_prefs(user_id)

    set_clause = ", ".join(updates + ["updated_at = now()"])
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("INSERT INTO user_notification_prefs (user_id) VALUES (:uid) ON CONFLICT DO NOTHING"),
            {"uid": user_id},
        )
        await session.execute(
            text(f"UPDATE user_notification_prefs SET {set_clause} WHERE user_id = :uid"),
            params,
        )
        await session.commit()
    return await get_prefs(user_id)
```

**Step 3: Verify + commit**

Run: `docker compose exec backend pytest tests/test_telegram_prefs.py -v`
Expected: 4 passed.

```bash
git add backend/app/telegram/prefs.py backend/tests/test_telegram_prefs.py
git commit -m "feat(telegram): notification prefs (PLAN-019 task 5)"
```

---

### Task 6: Webhook router — `status: approved`

**Depends on:** Task 3, Task 4

**Files:**
- Create: `backend/app/telegram/webhook.py`
- Test: `backend/tests/test_telegram_webhook.py`

**Router-prefix strategy:** The webhook is mounted **directly on the FastAPI app** in `main.py` (same pattern as `auth_router`). Uses absolute prefix `/api/telegram`. The user-facing router in Task 7 uses relative prefix `/telegram` and is mounted via `api/routes.py` (whose parent prefix is `/api`) — same pattern as `admin_router`. This avoids the `/api/api/...` double-prefix issue.

**Step 1: Write failing tests**

```python
import pytest
from httpx import AsyncClient
from app.main import app
from app.config import settings

WEBHOOK_SECRET = "test-secret"


@pytest.mark.asyncio
async def test_webhook_rejects_missing_secret(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)
    async with AsyncClient(app=app, base_url="http://test") as c:
        resp = await c.post("/api/telegram/webhook", json={})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_rejects_wrong_secret(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)
    async with AsyncClient(app=app, base_url="http://test") as c:
        resp = await c.post(
            "/api/telegram/webhook",
            json={},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_accepts_correct_secret(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)
    async with AsyncClient(app=app, base_url="http://test") as c:
        resp = await c.post(
            "/api/telegram/webhook",
            json={"update_id": 1, "message": {"chat": {"id": 999}, "text": "hello"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_start_token_links_user(monkeypatch, db_user):
    """/start <valid_token> sets user.telegram_chat_id."""
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)
    from app.telegram import link
    t = await link.create_token(user_id=db_user.id)
    async with AsyncClient(app=app, base_url="http://test") as c:
        resp = await c.post(
            "/api/telegram/webhook",
            json={"update_id": 1, "message": {"chat": {"id": 12345}, "text": f"/start {t.token}"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
        )
    assert resp.status_code == 200
    from app.db import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as s:
        row = await s.execute(text("SELECT telegram_chat_id FROM users WHERE id = :u"), {"u": db_user.id})
        assert row.scalar() == 12345


@pytest.mark.asyncio
async def test_webhook_malformed_payload_returns_200(monkeypatch):
    """Unexpected shapes (no message, no text) must not 500."""
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)
    async with AsyncClient(app=app, base_url="http://test") as c:
        for payload in ({}, {"update_id": 1}, {"update_id": 1, "message": {}}, {"update_id": 1, "message": {"chat": {}}}):
            resp = await c.post(
                "/api/telegram/webhook",
                json=payload,
                headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
            )
            assert resp.status_code == 200
```

**Step 2: Implement**

`backend/app/telegram/webhook.py`:

```python
"""Inbound Telegram webhook — handles /start <token> for account linking."""

from __future__ import annotations
import logging
from fastapi import APIRouter, Header, HTTPException, Request
from app.config import settings
from app.telegram import bot, link

logger = logging.getLogger(__name__)

# Absolute prefix — this router is mounted directly on the FastAPI app
router = APIRouter(prefix="/api/telegram", tags=["telegram"])


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(None),
) -> dict:
    if not settings.telegram_enabled:
        raise HTTPException(status_code=404, detail="Telegram subsystem disabled")
    if x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
        logger.warning("telegram.webhook: bad/missing secret header")
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        payload = await request.json()
    except Exception:
        logger.warning("telegram.webhook: unparseable body")
        return {"ok": True}

    message = payload.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text_body = (message.get("text") or "").strip()

    if not chat_id or not text_body:
        return {"ok": True}
    chat_id = int(chat_id)

    if text_body.startswith("/start "):
        token = text_body[len("/start "):].strip()
        user_id = await link.redeem_token(token, chat_id=chat_id)
        if user_id is not None:
            await bot.send_message(
                chat_id=chat_id,
                text_body=(
                    "✅ <b>Verbunden!</b>\n\n"
                    "Du erhältst jetzt Benachrichtigungen zu deinen gespeicherten Suchen und "
                    "Statusänderungen in deiner Merkliste.\n\n"
                    "Einstellungen: im Profil unter <i>Benachrichtigungen</i>."
                ),
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text_body="❌ Ungültiger oder abgelaufener Verbindungslink. Erzeuge einen neuen in deinem Profil.",
            )
        return {"ok": True}

    await bot.send_message(
        chat_id=chat_id,
        text_body="Ich verstehe nur <code>/start &lt;token&gt;</code>. Bitte verbinde deinen Account im Profil.",
    )
    return {"ok": True}
```

**Step 3: Mount in `main.py`**

Add import + include in lifespan or module-level (mirror existing `auth_router` pattern — whichever is used):

```python
from app.telegram.webhook import router as telegram_webhook_router
app.include_router(telegram_webhook_router)
```

**Step 4: Verify**

Run: `docker compose exec backend pytest tests/test_telegram_webhook.py -v`
Expected: 5 passed.

**Step 5: Commit**

```bash
git add backend/app/telegram/webhook.py backend/app/main.py backend/tests/test_telegram_webhook.py
git commit -m "feat(telegram): webhook router with secret check (PLAN-019 task 6)"
```

---

### Task 7: User-facing API endpoints — `status: approved`

**Depends on:** Task 4, Task 5

**Files:**
- Create: `backend/app/api/telegram.py`
- Modify: `backend/app/api/auth.py` — expose `telegram_chat_id` + `telegram_linked_at` in `/auth/me`
- Modify: `backend/app/api/routes.py` — mount the telegram api router
- Test: `backend/tests/test_telegram_api.py`

**Router-prefix strategy:** Uses relative `/telegram` prefix, parent `routes.router` has `/api`, final path `/api/telegram/*`. Same pattern as `admin_router`.

**Step 1: Write failing tests**

```python
import pytest
from httpx import AsyncClient
from app.main import app
from app.config import settings


@pytest.mark.asyncio
async def test_link_returns_deeplink(authenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "rcn_scout_bot")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    r = await authenticated_client.post("/api/telegram/link")
    assert r.status_code == 200
    body = r.json()
    assert body["deeplink"].startswith("https://t.me/rcn_scout_bot?start=")
    assert "expires_at" in body


@pytest.mark.asyncio
async def test_link_503_when_disabled(authenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    r = await authenticated_client.post("/api/telegram/link")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_unlink_clears_chat_id(authenticated_client_linked):
    r = await authenticated_client_linked.post("/api/telegram/unlink")
    assert r.status_code == 200
    me = await authenticated_client_linked.get("/api/auth/me")
    assert me.json().get("telegram_chat_id") is None


@pytest.mark.asyncio
async def test_get_prefs_returns_defaults(authenticated_client):
    r = await authenticated_client.get("/api/telegram/prefs")
    assert r.status_code == 200
    assert r.json()["fav_sold"] is True


@pytest.mark.asyncio
async def test_put_prefs_partial_update(authenticated_client):
    r = await authenticated_client.put("/api/telegram/prefs", json={"fav_sold": False})
    assert r.status_code == 200
    assert r.json()["fav_sold"] is False
    assert r.json()["fav_price"] is True


@pytest.mark.asyncio
async def test_auth_me_includes_telegram_fields(authenticated_client_linked):
    r = await authenticated_client_linked.get("/api/auth/me")
    body = r.json()
    assert "telegram_chat_id" in body
    assert "telegram_linked_at" in body


@pytest.mark.asyncio
async def test_unauthenticated_endpoints_401():
    async with AsyncClient(app=app, base_url="http://test") as c:
        assert (await c.post("/api/telegram/link")).status_code == 401
        assert (await c.get("/api/telegram/prefs")).status_code == 401
        assert (await c.put("/api/telegram/prefs", json={})).status_code == 401
        assert (await c.post("/api/telegram/unlink")).status_code == 401
```

**Step 2: Implement router**

`backend/app/api/telegram.py`:

```python
"""User-facing Telegram endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.api.deps import get_current_user
from app.config import settings
from app.models import User
from app.telegram import link, prefs

# Relative prefix — mounted under parent /api
router = APIRouter(prefix="/telegram", tags=["telegram"])


class LinkResponse(BaseModel):
    deeplink: str
    expires_at: str


class PrefsBody(BaseModel):
    new_search_results: bool | None = None
    fav_sold: bool | None = None
    fav_price: bool | None = None
    fav_deleted: bool | None = None
    fav_indicator: bool | None = None


class PrefsResponse(BaseModel):
    new_search_results: bool
    fav_sold: bool
    fav_price: bool
    fav_deleted: bool
    fav_indicator: bool


def _prefs_to_response(p) -> PrefsResponse:
    return PrefsResponse(
        new_search_results=p.new_search_results,
        fav_sold=p.fav_sold,
        fav_price=p.fav_price,
        fav_deleted=p.fav_deleted,
        fav_indicator=p.fav_indicator,
    )


@router.post("/link", response_model=LinkResponse)
async def create_link(user: User = Depends(get_current_user)) -> LinkResponse:
    if not settings.telegram_enabled:
        raise HTTPException(status_code=503, detail="Telegram subsystem not configured")
    t = await link.create_token(user.id)
    return LinkResponse(
        deeplink=f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={t.token}",
        expires_at=t.expires_at.isoformat(),
    )


@router.post("/unlink")
async def unlink(user: User = Depends(get_current_user)) -> dict:
    await link.unlink_user(user.id)
    return {"ok": True}


@router.get("/prefs", response_model=PrefsResponse)
async def get_prefs_endpoint(user: User = Depends(get_current_user)) -> PrefsResponse:
    return _prefs_to_response(await prefs.get_prefs(user.id))


@router.put("/prefs", response_model=PrefsResponse)
async def put_prefs(body: PrefsBody, user: User = Depends(get_current_user)) -> PrefsResponse:
    return _prefs_to_response(await prefs.set_prefs(user.id, **body.model_dump(exclude_unset=False)))
```

**Step 3: Mount in `routes.py`**

```python
from app.api.telegram import router as telegram_api_router
router.include_router(telegram_api_router)
```

**Step 4: Extend `/auth/me` response**

In `backend/app/api/auth.py`, update the pydantic model returned by `/auth/me` to include:

```python
telegram_chat_id: int | None = None
telegram_linked_at: datetime | None = None
```

…and populate from the user instance. Also extend the existing test for `/auth/me` to assert the new fields are present (nullable).

**Step 5: Verify**

Run: `docker compose exec backend pytest tests/test_telegram_api.py tests/test_auth.py -v`
Expected: all passed.

**Step 6: Commit**

```bash
git add backend/app/api/telegram.py backend/app/api/auth.py backend/app/api/routes.py backend/tests/test_telegram_api.py backend/tests/test_auth.py
git commit -m "feat(api): Telegram endpoints + /auth/me telegram fields (PLAN-019 task 7)"
```

---

### Task 8: TelegramPlugin — new-search-results via existing registry — `status: approved`

**Depends on:** Task 3, Task 5

**Files:**
- Create: `backend/app/telegram/plugin.py`
- Test: `backend/tests/test_telegram_plugin.py`

Scope is bounded: ~80 LOC plugin class + formatter helper. Well under the 150-LOC/4-behaviors budget.

**Step 1: Write failing tests**

```python
import pytest
from unittest.mock import AsyncMock, patch
from app.notifications.base import MatchResult
from app.telegram.plugin import TelegramPlugin
from app.config import settings
from app.db import AsyncSessionLocal
from sqlalchemy import text


def _match(user_id=1, search_id=12, titles=None, ids=None, name="Seglerr") -> MatchResult:
    titles = titles or ["Easy Glider", "Multiplex Cular"]
    ids = ids or [101, 102]
    return MatchResult(
        saved_search_id=search_id, search_name=name, user_id=user_id,
        new_listing_ids=ids, new_listing_titles=titles, total_new=len(ids),
    )


@pytest.mark.asyncio
async def test_is_configured_true_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    p = TelegramPlugin()
    assert await p.is_configured() is True


@pytest.mark.asyncio
async def test_is_configured_false_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    assert await TelegramPlugin().is_configured() is False


@pytest.mark.asyncio
async def test_send_skipped_when_user_not_linked(db_user, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    # db_user has no telegram_chat_id
    with patch("app.telegram.plugin.bot.send_message", new=AsyncMock(return_value=True)) as mock:
        ok = await TelegramPlugin().send(_match(user_id=db_user.id))
        mock.assert_not_called()
    assert ok is False


@pytest.mark.asyncio
async def test_send_skipped_when_pref_off(db_user_linked, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    from app.telegram import prefs
    await prefs.set_prefs(db_user_linked.user_id, new_search_results=False)
    with patch("app.telegram.plugin.bot.send_message", new=AsyncMock(return_value=True)) as mock:
        ok = await TelegramPlugin().send(_match(user_id=db_user_linked.user_id))
        mock.assert_not_called()
    assert ok is False


@pytest.mark.asyncio
async def test_send_sends_digest_when_enabled(db_user_linked, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    with patch("app.telegram.plugin.bot.send_message", new=AsyncMock(return_value=True)) as mock:
        ok = await TelegramPlugin().send(_match(user_id=db_user_linked.user_id, name="Seglerr"))
        mock.assert_called_once()
        _, kwargs = mock.call_args
        assert kwargs["chat_id"] == db_user_linked.chat_id
        assert "Seglerr" in kwargs["text_body"]
        assert "Easy Glider" in kwargs["text_body"]
    assert ok is True


@pytest.mark.asyncio
async def test_send_truncates_to_digest_top_n(db_user_linked, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    monkeypatch.setattr(settings, "TELEGRAM_DIGEST_TOP_N", 2)
    titles = ["A", "B", "C", "D", "E"]
    ids = [1, 2, 3, 4, 5]
    with patch("app.telegram.plugin.bot.send_message", new=AsyncMock(return_value=True)) as mock:
        await TelegramPlugin().send(_match(user_id=db_user_linked.user_id, titles=titles, ids=ids))
    body = mock.call_args.kwargs["text_body"]
    assert "A" in body and "B" in body
    assert "C" not in body  # top-2 only
    assert "5" in body  # "5 insgesamt" summary
```

**Step 2: Implement**

`backend/app/telegram/plugin.py`:

```python
"""TelegramPlugin: delivers new-search-results digests via the notification registry."""

from __future__ import annotations
import logging
from sqlalchemy import text

from app.config import settings
from app.db import AsyncSessionLocal
from app.notifications.base import MatchResult, NotificationPlugin
from app.telegram import bot, prefs as prefs_module

logger = logging.getLogger(__name__)


def _escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_digest(search_name: str, titles: list[str], ids: list[int], total: int, top_n: int) -> str:
    shown = list(zip(ids[:top_n], titles[:top_n]))
    lines = [
        f'• <a href="{settings.PUBLIC_BASE_URL}/listings/{i}">{_escape_html(t)}</a>'
        for i, t in shown
    ]
    header = f"🔔 <b>Neue Treffer: {_escape_html(search_name)}</b>\n"
    count_line = f"{total} neue Treffer" + (f" (Top {top_n}):" if total > top_n else ":")
    return header + count_line + "\n\n" + "\n".join(lines)


class TelegramPlugin(NotificationPlugin):
    """Sends a digest message to a user's linked Telegram chat."""

    async def is_configured(self) -> bool:
        return settings.telegram_enabled

    async def send(self, match: MatchResult) -> bool:
        # 1. Fetch chat_id
        async with AsyncSessionLocal() as session:
            row = await session.execute(
                text("SELECT telegram_chat_id FROM users WHERE id = :uid"),
                {"uid": match.user_id},
            )
            chat_id = row.scalar()

        if chat_id is None:
            logger.info("telegram.plugin: search_id=%d user_id=%d skipped (no telegram_chat_id)", match.saved_search_id, match.user_id)
            return False

        # 2. Check pref
        p = await prefs_module.get_prefs(match.user_id)
        if not p.new_search_results:
            logger.info("telegram.plugin: search_id=%d user_id=%d skipped (new_search_results=false)", match.saved_search_id, match.user_id)
            return False

        # 3. Format + send
        message = _format_digest(
            search_name=match.search_name,
            titles=match.new_listing_titles,
            ids=match.new_listing_ids,
            total=match.total_new,
            top_n=settings.TELEGRAM_DIGEST_TOP_N,
        )
        ok = await bot.send_message(chat_id=chat_id, text_body=message)
        if ok:
            logger.info("telegram.plugin: search_id=%d user_id=%d listings=%d sent ok", match.saved_search_id, match.user_id, match.total_new)
        else:
            logger.warning("telegram.plugin: search_id=%d user_id=%d listings=%d send FAILED", match.saved_search_id, match.user_id, match.total_new)
        return ok
```

**Step 3: Register plugin in `main.py`**

Modify `backend/app/main.py` lifespan:

```python
from app.telegram.plugin import TelegramPlugin

# Inside the existing plugin-registration block:
if settings.telegram_enabled and not any(isinstance(p, TelegramPlugin) for p in notification_registry._plugins):
    notification_registry.register(TelegramPlugin())
    logger.info("telegram.plugin: registered in notification_registry")
```

**Step 4: Verify**

Run: `docker compose exec backend pytest tests/test_telegram_plugin.py -v`
Expected: 6 passed.

**Step 5: Commit**

```bash
git add backend/app/telegram/plugin.py backend/app/main.py backend/tests/test_telegram_plugin.py
git commit -m "feat(telegram): plugin for new-results digest (PLAN-019 task 8)"
```

---

### Task 9: Favorites-status sweep — `status: approved`

**Depends on:** Task 3, Task 5

**Files:**
- Create: `backend/app/telegram/fav_sweep.py`
- Test: `backend/tests/test_telegram_fav_sweep.py`

Scope: one function (`run_fav_status_sweep`) + one helper to detect per-favorite deltas + one formatter. ~120 LOC; under budget.

**Step 1: Write failing tests**

```python
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from app.telegram import fav_sweep
from app.telegram import prefs
from app.config import settings
from app.db import AsyncSessionLocal
from sqlalchemy import text


async def _insert_favorite(user_id, listing_id, snapshot=None):
    async with AsyncSessionLocal() as s:
        await s.execute(text("INSERT INTO user_favorites (user_id, listing_id) VALUES (:u, :l) ON CONFLICT DO NOTHING"), {"u": user_id, "l": listing_id})
        if snapshot:
            await s.execute(text("""
                UPDATE user_favorites SET
                  last_known_is_sold = :sold, last_known_price_numeric = :price,
                  last_known_price_indicator = :ind, last_known_scraped_at = :scr
                WHERE user_id = :u AND listing_id = :l
            """), {**snapshot, "u": user_id, "l": listing_id})
        await s.commit()


@pytest.mark.asyncio
async def test_sold_transition_triggers_message(db_user_linked, db_listing, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "b")
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s")
    # Listing now is_sold=true, snapshot was false
    await _insert_favorite(db_user_linked.user_id, db_listing.id, snapshot={"sold": False, "price": 100, "ind": "fair", "scr": datetime.now(timezone.utc)})
    async with AsyncSessionLocal() as s:
        await s.execute(text("UPDATE listings SET is_sold = TRUE WHERE id = :i"), {"i": db_listing.id})
        await s.commit()
    with patch("app.telegram.fav_sweep.bot.send_message", new=AsyncMock(return_value=True)) as mock:
        sent = await fav_sweep.run_fav_status_sweep()
    assert sent == 1
    assert "Verkauft" in mock.call_args.kwargs["text_body"]


@pytest.mark.asyncio
async def test_price_change_triggers(db_user_linked, db_listing, monkeypatch):
    # ... similar
    ...


@pytest.mark.asyncio
async def test_deleted_triggers_when_scraped_at_stale(db_user_linked, db_listing, monkeypatch):
    # listing.scraped_at = 4 days ago, snapshot was 1 day ago (was alive)
    ...


@pytest.mark.asyncio
async def test_indicator_change_triggers(db_user_linked, db_listing, monkeypatch):
    ...


@pytest.mark.asyncio
async def test_pref_disabled_still_updates_snapshot_no_message(db_user_linked, db_listing, monkeypatch):
    await prefs.set_prefs(db_user_linked.user_id, fav_sold=False)
    # Sold transition but pref off
    ...
    with patch("app.telegram.fav_sweep.bot.send_message", new=AsyncMock(return_value=True)) as mock:
        await fav_sweep.run_fav_status_sweep()
        mock.assert_not_called()
    # But snapshot updated
    async with AsyncSessionLocal() as s:
        row = await s.execute(text("SELECT last_known_is_sold FROM user_favorites WHERE user_id=:u AND listing_id=:l"),
                              {"u": db_user_linked.user_id, "l": db_listing.id})
        assert row.scalar() is True


@pytest.mark.asyncio
async def test_per_favorite_exception_does_not_abort_sweep(db_user_linked, monkeypatch):
    # Seed 3 favorites, make the middle one raise via corrupted data
    # Assert first + third are processed despite middle failure
    ...


@pytest.mark.asyncio
async def test_no_change_no_message(db_user_linked, db_listing, monkeypatch):
    await _insert_favorite(db_user_linked.user_id, db_listing.id, snapshot={"sold": False, "price": None, "ind": None, "scr": datetime.now(timezone.utc)})
    with patch("app.telegram.fav_sweep.bot.send_message", new=AsyncMock(return_value=True)) as mock:
        sent = await fav_sweep.run_fav_status_sweep()
    assert sent == 0
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_sweep_noop_when_telegram_disabled(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    sent = await fav_sweep.run_fav_status_sweep()
    assert sent == 0
```

**Step 2: Implement**

`backend/app/telegram/fav_sweep.py`:

```python
"""Favorites-status sweep: detect sold/price/deleted/indicator changes.

Runs every TELEGRAM_FAV_SWEEP_INTERVAL_MIN minutes via APScheduler (registered in main.py).
"""

from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text
from app.config import settings
from app.db import AsyncSessionLocal
from app.telegram import bot, link, prefs as prefs_module

logger = logging.getLogger(__name__)


def _escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _decimal_eq(a, b) -> bool:
    """Compare two NUMERIC values for equality, tolerating None."""
    if a is None or b is None:
        return a is b  # both must be None
    return Decimal(str(a)) == Decimal(str(b))


def _detect_events(row, deleted_cutoff: datetime, user_prefs) -> list[str]:
    """Return list of formatted event lines based on diffs + per-user prefs."""
    events = []
    (_, _, lk_sold, lk_price, lk_ind, lk_scr,
     title, _, is_sold, price, ind, scraped_at, _) = row

    if lk_sold is not None and lk_sold is False and is_sold is True and user_prefs.fav_sold:
        events.append(f"🏷️ <b>Verkauft:</b> {_escape_html(title)}")

    if lk_price is not None and price is not None and not _decimal_eq(lk_price, price) and user_prefs.fav_price:
        events.append(f"💶 <b>Preis geändert:</b> {_escape_html(title)} — {float(lk_price):.0f}€ → {float(price):.0f}€")

    # Deleted: listing hasn't been re-scraped for TELEGRAM_FAV_DELETED_DAYS days
    # AND snapshot was still "alive" (scraped_at within the cutoff) at last sweep
    listing_gone = scraped_at is not None and scraped_at < deleted_cutoff
    snapshot_alive = lk_scr is not None and lk_scr >= deleted_cutoff
    if listing_gone and snapshot_alive and user_prefs.fav_deleted:
        events.append(f"🗑️ <b>Gelöscht:</b> {_escape_html(title)}")

    if lk_ind is not None and ind is not None and lk_ind != ind and user_prefs.fav_indicator:
        events.append(f"📊 <b>Preisbewertung:</b> {_escape_html(title)} — {lk_ind} → {ind}")

    return events


async def run_fav_status_sweep() -> int:
    """Scan user_favorites, diff against snapshots, send per-favorite event messages.

    Returns number of Telegram messages successfully sent.
    Always updates snapshots (even when no message was sent / pref disabled).
    """
    if not settings.telegram_enabled:
        return 0

    deleted_cutoff = datetime.now(timezone.utc) - timedelta(days=settings.TELEGRAM_FAV_DELETED_DAYS)
    sent_count = 0

    try:
        async with AsyncSessionLocal() as session:
            rows = await session.execute(
                text("""
                    SELECT uf.user_id, uf.listing_id,
                           uf.last_known_is_sold, uf.last_known_price_numeric,
                           uf.last_known_price_indicator, uf.last_known_scraped_at,
                           l.title, l.url,
                           l.is_sold, l.price_numeric, l.price_indicator, l.scraped_at,
                           u.telegram_chat_id
                    FROM user_favorites uf
                    JOIN listings l ON l.id = uf.listing_id
                    JOIN users u ON u.id = uf.user_id
                    WHERE u.telegram_chat_id IS NOT NULL
                """)
            )
            favorites = rows.all()
    except Exception:
        logger.exception("telegram.sweep.fav: load FAILED — aborting sweep")
        return 0

    for fav in favorites:
        user_id, listing_id = fav[0], fav[1]
        try:
            user_prefs = await prefs_module.get_prefs(user_id)
            events = _detect_events(fav, deleted_cutoff, user_prefs)

            if events:
                chat_id = fav[-1]
                msg = "\n\n".join(events) + f'\n\n<a href="{settings.PUBLIC_BASE_URL}/listings/{listing_id}">Zum Inserat</a>'
                if await bot.send_message(chat_id=chat_id, text_body=msg):
                    sent_count += 1
                    logger.info("telegram.sweep.fav: user_id=%d listing_id=%d triggers=%d sent", user_id, listing_id, len(events))

            # Always update snapshot
            async with AsyncSessionLocal() as session:
                await session.execute(
                    text("""
                        UPDATE user_favorites
                        SET last_known_is_sold = :sold,
                            last_known_price_numeric = :price,
                            last_known_price_indicator = :ind,
                            last_known_scraped_at = :scr
                        WHERE user_id = :u AND listing_id = :l
                    """),
                    {
                        "sold": fav[8], "price": fav[9], "ind": fav[10], "scr": fav[11],
                        "u": user_id, "l": listing_id,
                    },
                )
                await session.commit()
        except Exception:
            logger.exception("telegram.sweep.fav: user_id=%d listing_id=%d FAILED — skipping", user_id, listing_id)
            continue

    # Housekeeping: prune old link tokens
    try:
        deleted = await link.cleanup_expired_tokens(older_than_days=7)
        if deleted:
            logger.info("telegram.sweep.fav: pruned %d expired link tokens", deleted)
    except Exception:
        logger.exception("telegram.sweep.fav: token cleanup failed")

    return sent_count
```

**Step 3: Verify**

Run: `docker compose exec backend pytest tests/test_telegram_fav_sweep.py -v`
Expected: 8 passed.

**Step 4: Commit**

```bash
git add backend/app/telegram/fav_sweep.py backend/tests/test_telegram_fav_sweep.py
git commit -m "feat(telegram): favorites-status sweep (PLAN-019 task 9)"
```

---

### Task 10: Scheduler registration + setWebhook on startup — `status: approved`

**Depends on:** Task 6, Task 8, Task 9

**Files:**
- Modify: `backend/app/main.py`

**Step 1: Add scheduler + setWebhook**

In `main.py` lifespan, after existing scheduler setup:

```python
import httpx  # at module top

# inside lifespan, after plugin registration:
if settings.telegram_enabled:
    from app.telegram import fav_sweep
    scheduler.add_job(
        fav_sweep.run_fav_status_sweep,
        trigger="interval",
        minutes=settings.TELEGRAM_FAV_SWEEP_INTERVAL_MIN,
        id="telegram_fav_status_sweep",
        replace_existing=True,
    )
    # Register webhook with Telegram (idempotent — setWebhook no-ops on same URL+secret)
    webhook_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/telegram/webhook"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/setWebhook",
                json={
                    "url": webhook_url,
                    "secret_token": settings.TELEGRAM_WEBHOOK_SECRET,
                    "allowed_updates": ["message"],
                },
            )
        if r.status_code == 200 and r.json().get("ok"):
            logger.info("telegram: webhook registered at %s", webhook_url)
        else:
            logger.warning("telegram: setWebhook returned %d %s", r.status_code, r.text[:200])
    except httpx.HTTPError as exc:
        logger.warning("telegram: setWebhook failed: %s", exc)
else:
    logger.info("telegram: disabled (missing TELEGRAM_BOT_TOKEN or username or webhook_secret)")
```

**Step 2: Verify**

Run: `docker compose restart backend && sleep 8 && docker compose logs --tail=30 backend | grep -i telegram`

Expected with unset token: `telegram: disabled (missing ...)`.
Expected with all three vars: `telegram: webhook registered at ...` + plugin registration log from Task 8.

**Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(telegram): schedule fav sweep + register webhook on boot (PLAN-019 task 10)"
```

---

### Task 11: Frontend API client + types — `status: approved`

**Depends on:** Task 7

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/hooks/useAuth.ts` — pick up new telegram fields from `/auth/me`

**Step 1: Add types**

```typescript
export interface NotificationPrefs {
  new_search_results: boolean;
  fav_sold: boolean;
  fav_price: boolean;
  fav_deleted: boolean;
  fav_indicator: boolean;
}

export interface TelegramLinkResponse {
  deeplink: string;
  expires_at: string;
}

// Extend existing User interface:
// telegram_chat_id?: number | null;
// telegram_linked_at?: string | null;
```

**Step 2: Add client functions**

```typescript
export async function linkTelegram(): Promise<TelegramLinkResponse> {
  return handleResponse<TelegramLinkResponse>(
    await fetch("/api/telegram/link", { method: "POST", credentials: "include" })
  );
}

export async function unlinkTelegram(): Promise<void> {
  await handleResponse(
    await fetch("/api/telegram/unlink", { method: "POST", credentials: "include" })
  );
}

export async function getNotificationPrefs(): Promise<NotificationPrefs> {
  return handleResponse<NotificationPrefs>(
    await fetch("/api/telegram/prefs", { credentials: "include" })
  );
}

export async function updateNotificationPrefs(partial: Partial<NotificationPrefs>): Promise<NotificationPrefs> {
  return handleResponse<NotificationPrefs>(
    await fetch("/api/telegram/prefs", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(partial),
    })
  );
}
```

**Step 3: Verify typecheck + commit**

Run: `docker compose exec -T frontend sh -c "cd /app && npx tsc -b --noEmit"`

```bash
git add frontend/src/types/api.ts frontend/src/api/client.ts frontend/src/hooks/useAuth.ts
git commit -m "feat(frontend): Telegram API client + types (PLAN-019 task 11)"
```

---

### Task 12: TelegramPanel component — `status: approved`

**Depends on:** Task 11

**Files:**
- Create: `frontend/src/components/TelegramPanel.tsx`
- Test: `frontend/src/components/__tests__/TelegramPanel.test.tsx`

**Reuse check:** No existing pattern for this type of linking panel. Design props-driven. Reuses `ConfirmDialog` from `frontend/src/components/ConfirmDialog.tsx` for unlink confirmation.

**Step 1: Component**

~150 LOC JSX + handlers. Aurora-glass styling consistent with existing `LLMAdminPanel`. Single card with:
- Header "Benachrichtigungen (Telegram)"
- Status line: "✅ Verbunden seit {relative}" + Trennen button OR "Nicht verbunden" + Verbinden button
- Toggle section (only when linked): 5 labeled toggle rows, optimistic update via PUT on change
- Link button: calls `linkTelegram()`, opens `response.deeplink` via `window.open(url, '_blank')`
- Unlink: uses `useConfirm()` hook → on confirm calls `unlinkTelegram()` + `onUserReload()`
- Loading + error states
- Toggle row loses disabled state after server response, revert on error

**Step 2: Tests**

`frontend/src/components/__tests__/TelegramPanel.test.tsx` with explicit imports (`import { describe, it, expect, vi } from 'vitest'`):
- Renders "Nicht verbunden" + link button when `user.telegram_chat_id` is null
- Clicking link button calls `linkTelegram` and opens `deeplink` in new tab (mock `window.open`)
- Renders toggle section + "Verbunden"-badge when linked
- Clicking toggle calls `updateNotificationPrefs` with `{field: newValue}`
- Failed `updateNotificationPrefs` reverts the toggle UI
- Unlink button triggers confirm dialog, then `unlinkTelegram` on OK

**Step 3: Verify**

Run: `docker compose exec -T frontend sh -c "cd /app && npx vitest run src/components/__tests__/TelegramPanel.test.tsx && npx tsc -b --noEmit"`

**Step 4: Commit**

```bash
git add frontend/src/components/TelegramPanel.tsx frontend/src/components/__tests__/TelegramPanel.test.tsx
git commit -m "feat(frontend): TelegramPanel with link/toggle/unlink (PLAN-019 task 12)"
```

---

### Task 13: Mount in ProfilePage — `status: approved`

**Depends on:** Task 12

**Files:**
- Modify: `frontend/src/pages/ProfilePage.tsx`

**Step 1: Mount the panel**

Below the existing sections in ProfilePage (for non-admin users) AND above the `LLMAdminPanel` section (for admin users):

```tsx
{user && <TelegramPanel user={user} onUserReload={reloadUser} />}
```

Ensure `useAuth` exposes `reloadUser()` or a similar refresh callback. If not, add one that re-fetches `/auth/me`.

**Step 2: Playwright smoke test (manual, not automated yet)**

With `TELEGRAM_BOT_TOKEN` unset: panel renders but "Verbinden" button returns 503 on click (show error). With all three env vars set: link button works, deeplink opens.

Smoke script:
```python
# tmp_telegram.py — seed cookie, navigate to /profile, assert panel + buttons
```

**Step 3: Commit**

```bash
git add frontend/src/pages/ProfilePage.tsx frontend/src/hooks/useAuth.ts
git commit -m "feat(frontend): mount TelegramPanel in profile (PLAN-019 task 13)"
```

---

### Task 14: CHANGELOG + version bump — `status: approved`

**Depends on:** Task 13

**Step 1: Entry in `CHANGELOG.md` at top**

Current version at plan-approval time is `1.4.0` (check `frontend/package.json` and confirm). Bump to `1.5.0`.

```markdown
## [1.5.0] - YYYY-MM-DD

### Added

**Telegram-Benachrichtigungen (PLAN-019)**
- Jeder User kann seinen Telegram-Account im Profil verknüpfen (Deep-Link, ein Klick)
- Digest-Benachrichtigungen zu neuen Treffern gespeicherter Suchen (automatisch nach jedem Scrape-Lauf)
- Event-Benachrichtigungen bei Statusänderungen an Merklisten-Einträgen: verkauft / Preisänderung / gelöscht / Preisbewertung
- Per-User-Toggles im Profil für jede der 5 Benachrichtigungsarten
- Telegram-Subsystem ist komplett deaktiviert wenn `TELEGRAM_BOT_TOKEN` nicht gesetzt ist (Default)
- Blockierter Bot wird automatisch entknüpft (403-Auto-Unlink)
```

**Step 2: Bump version**

`frontend/package.json`: `"version": "1.5.0"`

**Step 3: Commit**

```bash
git add CHANGELOG.md frontend/package.json
git commit -m "docs: v1.5.0 changelog (PLAN-019 task 14)"
```

---

## Verification

Run AFTER all tasks DONE:

```bash
# 1. Backend test suite (only PLAN-019 files)
docker compose exec -T backend pytest \
  tests/test_telegram_bot.py \
  tests/test_telegram_link.py \
  tests/test_telegram_prefs.py \
  tests/test_telegram_webhook.py \
  tests/test_telegram_api.py \
  tests/test_telegram_plugin.py \
  tests/test_telegram_fav_sweep.py \
  -v
# Expected: all green

# 2. Frontend test + typecheck
docker compose exec -T frontend sh -c "cd /app && \
  npx vitest run src/components/__tests__/TelegramPanel.test.tsx && \
  npx tsc -b --noEmit"
# Expected: green

# 3. DB schema
docker compose exec -T db psql -U rcscout -d rcscout -c "\d users" | grep telegram
docker compose exec -T db psql -U rcscout -d rcscout -c "\d telegram_link_tokens"
docker compose exec -T db psql -U rcscout -d rcscout -c "\d user_notification_prefs"
docker compose exec -T db psql -U rcscout -d rcscout -c "\d user_favorites" | grep last_known
# Expected: all new columns/tables present

# 4. Startup logs — both modes
# A) Unset TELEGRAM_BOT_TOKEN in dev .env, restart
docker compose restart backend && sleep 8
docker compose logs --tail=20 backend | grep -i telegram
# Expected: "telegram: disabled (missing ...)"

# B) Set all three TELEGRAM_* vars, restart
docker compose restart backend && sleep 8
docker compose logs --tail=20 backend | grep -i telegram
# Expected: "telegram: webhook registered at ..." + "telegram.plugin: registered ..."

# 5. Production build
docker compose exec -T frontend sh -c "cd /app && npm run build"
# Expected: clean

# 6. Manual E2E on prod (after release)
#  a. Open /profile, click "Mit Telegram verbinden"
#  b. Verify deep link opens Telegram
#  c. Press Start in Telegram
#  d. Bot replies "Verbunden!"
#  e. SELECT telegram_chat_id FROM users WHERE id=<me>;  → chat_id populated
#  f. Trigger a new scrape; verify digest arrives if new matches
#  g. Toggle fav_sold=false in UI; verify marking a favorite as sold does NOT trigger message
#  h. Re-toggle on; next sold transition triggers.
```

## Assumptions & Risks

- **Assumption:** `PUBLIC_BASE_URL` is HTTPS on prod (required for Telegram webhooks). Verified in `docker-compose.prod.yml`.
- **Assumption:** `user_favorites` has composite PK `(user_id, listing_id)`. Verified in `models.py`.
- **Assumption:** `listings.scraped_at` is updated on every observation of the listing (not only insert). Implementer must verify this in `app/scraper/orchestrator.py` before depending on the "deleted" detection in Task 9. If the scraper only writes `scraped_at` on initial insert and never updates it, the deleted-detection is broken — in that case add scraper-side update, or switch to a separate `last_observed_at` column. Check and adjust Task 1 accordingly.
- **Risk:** All 4 free LLM models rate-limited → new listings land without `llm_analyzed=true`. The plugin doesn't depend on LLM fields; the digest goes out anyway. Acceptable.
- **Risk:** User blocks the bot → 403 response → `bot.send_message` auto-clears `telegram_chat_id`. No further messages attempted until user re-links.
- **Risk:** Same `saved_searches` row matches 500 new listings in one scrape → digest shows top 5 + "500 insgesamt". `search_notifications` still prevents duplicate-listing entries across runs. Noise ceiling acceptable.
- **Risk:** Webhook secret leaks via logs. Mitigation: the bot token and secret are never logged in full. Link tokens truncated to 6 chars in logs.
- **Risk:** Telegram Bot API rate limit (30 msg/sec global, 1 msg/sec per chat). At single-user scale irrelevant; with many users the fav-sweep could queue up — but still well under 30/sec.
- **Risk:** Fav-sweep per-iteration try/except may silently swallow logic bugs. Mitigation: `logger.exception(...)` writes full stack trace on any catch.
- **Note (by design):** Link tokens older than 7 days are pruned by the fav-sweep's trailing cleanup. No separate cleanup job needed.

## Out of Scope

- Multi-rcn-scout-user per Telegram chat (one Telegram account → multiple app accounts). Partial-unique-index prevents this; we don't support it.
- Rich media (listing photos in notification messages). Follow-up.
- User-initiated commands beyond `/start <token>` (e.g., `/list` to query favorites).
- Signal/Discord/Matrix parallel channels. `TelegramPanel` designed to be swappable later.
- User-configurable digest frequency / top-N customization.
- Dedup across sweep runs for favorites that flip sold-true → sold-false → sold-true between two sweeps. Accepted edge case.
- Admin override / manual unlink of another user's telegram account.

## Reviewer Notes

**Reviewer (plan-reviewer agent + Codex cross-check, 2026-04-15):**

Initial verdict ⚠️ REVISE → all five blockers addressed. Summary of changes applied:

1. ✅ **Plugin architecture reuse (Codex major finding)** — The project already has `NotificationPlugin` + `notification_registry` + `search_matcher.check_new_matches()` hooked into `scrape_runner.py:141`. Old plan's `run_new_results_sweep` was reinventing that. Rewritten: Task 8 is now a `TelegramPlugin` that gets registered; all match-finding + dedup reuses existing code.

2. ✅ **`listings.last_seen_at` missing** — Switched to using existing `listings.scraped_at` as the "last observed" timestamp. No scraper write-path changes required (scraper already writes `scraped_at`). Snapshot column renamed to `last_known_scraped_at` for clarity.

3. ✅ **`saved_searches` filter columns don't exist** — The hand-written `_find_new_matches` SQL was the broken artifact. Now entirely deleted; `search_matcher` handles all filtering via `build_text_filter` + `filter_by_distance`.

4. ✅ **Router prefix collision** — Webhook router uses absolute `/api/telegram` prefix, mounted directly on app (pattern from `auth_router`). User-facing router uses relative `/telegram` prefix, mounted via `routes.py` (pattern from `admin_router`). Both documented in Task 6 and Task 7.

5. ✅ **Scheduler exception handling** — `run_fav_status_sweep` now has per-iteration try/except with `logger.exception(...)`. Outer sweep also try/except-wrapped. Load-phase failure aborts cleanly.

6. ✅ **Task 8 oversize** — Old Task 8 split away: plugin is now Task 8 (~80 LOC, 4 tests), fav-sweep Task 9 (~120 LOC, 8 tests). Neither exceeds context budget.

Non-blocking refinements all integrated:
- Status vocabulary aligned to `open/implemented/reviewed/approved`
- `httpx` import noted in Task 10
- LLM-disabled path clarified: plugin doesn't depend on LLM fields
- Link token 7-day cleanup tacked onto fav-sweep
- Pricing zero-check comparison uses `Decimal` (Task 9)
- `_detect_events` isolated in helper function (testable)
- Test coverage extended: malformed webhook payload, empty partial prefs, per-iteration exception isolation, snapshot-updated-even-when-pref-disabled, concurrent-sweep handled by `max_instances=1` APScheduler default
- `/auth/me` expansion explicitly listed in Task 7 with its own test
- `monkeypatch.setattr(settings, ...)` pattern documented (aligned with PLAN-018 convention)
- Version bump verification in Task 14
