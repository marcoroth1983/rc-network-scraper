# Web-Push TTL + Urgency Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use dglabs.executing-plans to implement this plan task-by-task.

**Goal:** Stop Web Push notifications from being silently dropped while the user's Android device is asleep, by setting a non-zero TTL (and high urgency) on the single `webpush()` call.

**Architecture:** Both notification paths — saved-search hits (`WebPushPlugin.send`) and favorites-status events (`fav_sweep.run_fav_status_sweep`) — funnel through the one helper `send_web_push_to_user` in `web_push_plugin.py`, which calls `webpush()` exactly once (line 56-65). `pywebpush.webpush()` defaults to `ttl=0`, which tells the push service (FCM) to deliver immediately or discard. A dozing Android phone is not connected at that instant, so FCM accepts the request (HTTP 201, `last_used_at` bumped) but drops the message — the device never shows it. Setting `ttl=86400` makes FCM queue the message up to 24 h and deliver on wake; `Urgency: high` asks FCM to wake the device promptly. One callsite fixes both paths.

**Tech Stack:** Python 3.12, pywebpush, asyncio, pytest/pytest-asyncio.

**Breaking Changes:** No. Additive arguments to an existing call; no schema, API, or behavior change beyond delivery reliability.

**Verified on prod (2026-06-10):** a manual `webpush()` to the user's subscription with `ttl=86400` + `Urgency: high` arrived on the sleeping device; the production `ttl=0` push fired at 05:27 (device asleep) never arrived despite FCM returning 201. Root cause confirmed, subscription healthy.

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-06-10 |
| Human | pending | — |

---

## Context

**Single callsite (verified):** `grep webpush( backend/app` → only `backend/app/notifications/web_push_plugin.py` (import at line 10, call at 56-65). `fav_sweep.py` does not call `webpush()` directly — it imports and calls `send_web_push_to_user` (`fav_sweep.py:18,106`). Fixing the one call covers both notification types.

**Current call (`web_push_plugin.py:56-65`):**
```python
            await asyncio.to_thread(
                webpush,
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=data,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_SUBJECT},
            )
```

**`webpush()` signature (verified in prod container):** `... content_encoding='aes128gcm', curl=False, timeout=None, ttl=0, verbose=False, headers=None, ...`. `ttl` and `headers` are accepted kwargs; default `ttl=0`.

**Value choice:** `ttl=86400` (24 h) — a personal hobby app scrapes a few times/hour; a day of buffering is ample and well within FCM limits (max 28 days). `Urgency: "high"` is the standard Web Push header value for time-sensitive user notifications. Both are kept as module-level constants for clarity (no config knob — YAGNI, single-user app).

**Test convention (canonical reference):** `backend/tests/test_web_push_plugin.py:58-68` (`test_send_calls_webpush_for_each_subscription`) already monkeypatches `mod.webpush` with `lambda **kw: calls.append(kw)` and asserts on the captured kwargs. Mirror this to assert the new `ttl` / `headers` kwargs. The `seeded_user_with_subs` fixture and `from app.notifications import web_push_plugin as mod` import are established in the same file — reuse as-is.

---

### Task 1: Set TTL + Urgency on the webpush() call [ ]

**Files:**
- Modify: `backend/app/notifications/web_push_plugin.py` (add two constants near the top after line 18; extend the call at 56-65)
- Test: `backend/tests/test_web_push_plugin.py` (add one test, mirror `:58-68`)

**Step 1: Add constants**

Insert after the `logger = logging.getLogger(__name__)` line (`web_push_plugin.py:18`):

```python
# Web Push delivery tuning. ttl=0 (pywebpush default) tells the push service to
# deliver instantly or discard — a sleeping device (Android Doze) never receives
# it. A 24h TTL lets FCM buffer and deliver on wake; high urgency asks FCM to
# wake the device promptly for these user-facing notifications.
_PUSH_TTL_SECONDS = 86400
_PUSH_HEADERS = {"Urgency": "high"}
```

**Step 2: Pass them to webpush()**

Extend the call (`web_push_plugin.py:56-65`) by adding the two kwargs:

```python
            await asyncio.to_thread(
                webpush,
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=data,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_SUBJECT},
                ttl=_PUSH_TTL_SECONDS,
                headers=_PUSH_HEADERS,
            )
```

**Step 3: Write test**

Add to `backend/tests/test_web_push_plugin.py` (mirror the kwargs-capture pattern at `:58-68`):

```python
@pytest.mark.asyncio
async def test_send_passes_ttl_and_urgency_to_webpush(monkeypatch, seeded_user_with_subs):
    """Pushes must carry a non-zero TTL + high urgency so a sleeping device
    receives them on wake (ttl=0 → FCM drops while the device is in Doze)."""
    from app.notifications import web_push_plugin as mod
    monkeypatch.setattr(
        mod.prefs_module, "get_prefs",
        AsyncMock(return_value=MagicMock(web_push_enabled=True, new_search_results=True)),
    )
    calls: list[dict] = []
    monkeypatch.setattr(mod, "webpush", lambda **kw: calls.append(kw))
    await WebPushPlugin().send(_match(seeded_user_with_subs.user_id))
    assert calls, "webpush was not called"
    for kw in calls:
        assert kw["ttl"] == 86400
        assert kw["headers"] == {"Urgency": "high"}
```

**Step 4: Commit**

```bash
git add backend/app/notifications/web_push_plugin.py backend/tests/test_web_push_plugin.py
git commit -m "fix: set TTL + high urgency on web push so sleeping devices receive notifications (PLAN-032)"
```

---

## Verification

### A. Automated (run once, after the task)

From the backend container:

```bash
docker compose exec backend pytest tests/test_web_push_plugin.py -v
docker compose exec backend pytest tests/ -q
```
Expect: the new `test_send_passes_ttl_and_urgency_to_webpush` passes; existing web-push tests still pass; full suite green.

### B. Operational — deploy to the VPS (Human-authorized)

Ship as release **v2.7.2** (deploy is release-triggered, not push-triggered).

1. Bump `frontend/package.json` version to `2.7.2`; add a `CHANGELOG.md` `[2.7.2]` section (web-push TTL/urgency fix).
2. Cut the release: `gh release create v2.7.2 --title v2.7.2 --notes "..."`.
3. After deploy, trigger a real notification (or wait for the next saved-search hit / favorite event) **with the target device asleep/locked** and confirm it arrives on wake. This is the behavior the unit test cannot cover (FCM buffering is server-side).

---

## Plan Review
<!-- dglabs.agent.review-plan — 2026-06-10 -->

### Self-Review Gate (Pass 0)
- [x] 1. Placeholder scan — no TODO/FIXME/TBD/XXX/placeholder in plan body.
- [x] 2. Dropped-field orphan scan — no renamed/dropped identifiers; constants `_PUSH_TTL_SECONDS` / `_PUSH_HEADERS` introduced once and used consistently.
- [x] 3. Line-anchor freshness — all anchors verified against live code:
  - `web_push_plugin.py:18` → `logger = logging.getLogger(__name__)` ✓
  - `web_push_plugin.py:56-65` → `await asyncio.to_thread(webpush, ...)` call ✓
  - `fav_sweep.py:18` → `from app.notifications.web_push_plugin import send_web_push_to_user` ✓
  - `fav_sweep.py:106` → `if await send_web_push_to_user(user_id, payload):` ✓
  - `test_web_push_plugin.py:58-68` → `test_send_calls_webpush_for_each_subscription`, monkeypatch pattern ✓
- [x] 4. Test-count consistency — one new test added; all mentions of it use the same name `test_send_passes_ttl_and_urgency_to_webpush`. Consistent throughout.
- [x] 5. Deleted-class caller check — no deletions; additive only.
- [x] 6. Mirror-reference verification — `test_web_push_plugin.py:58-68` confirmed: `calls: list[dict] = []`, `monkeypatch.setattr(mod, "webpush", lambda **kw: calls.append(kw))`, asserts on `calls`. New test mirrors this exactly.
- [x] 7. Convention contradictions across tasks — single task, no cross-task contract drift possible.

### Structural Checklist (Pass 1.A)
- [x] Required sections present (Context & Goal, Breaking Changes, Steps, Verification)
- [x] Step status marker present (`[ ]` on Task 1)
- [x] Step granularity suitable for a fresh AI instance (1 file to modify, 1 test to add, 1 commit)
- [x] Test file named explicitly (`backend/tests/test_web_push_plugin.py`)
- [x] Breaking changes marked (No — additive kwargs only)
- [x] BREAK markers: zero BREAKs — appropriate for a single-task thin plan

### Pass 1: Content & Correctness

**Single callsite verified:** `grep -rn "webpush\b" backend/` hits `web_push_plugin.py` for the import (line 10) and the one call (line 57). No other file under `backend/app` calls `webpush()` directly. `fav_sweep.py` imports and calls `send_web_push_to_user` (lines 18, 106) — confirming the plan's architecture claim is accurate.

**webpush() signature claim:** The plan states `ttl` and `headers` are accepted kwargs with `ttl=0` as default. This is consistent with pywebpush's published API and the production-container verification the plan documents. No contradiction found.

**Test correctness:** The proposed test mirrors the canonical pattern at `:58-68` faithfully. `AsyncMock` and `MagicMock` are already imported in the test file (line 5). `_match` helper is defined at line 15 — re-used correctly. The `from app.notifications import web_push_plugin as mod` import is done inside the test body, consistent with the existing tests. The `calls` list approach captures all kwargs including positional-passed ones (pywebpush uses keyword args throughout) — no gap.

**One non-blocking observation:** The new test's monkeypatch for `mod.webpush` replaces it with a synchronous lambda. The production code wraps the call in `asyncio.to_thread(webpush, ...)`, which means the monkeypatched lambda will be passed as the *callable* argument to `to_thread`. `asyncio.to_thread` accepts any callable, so this works, but the lambda signature must accept `**kw`. The production call passes all arguments as keyword arguments (verified at lines 57-65 of the source), and the lambda `lambda **kw: calls.append(kw)` matches that. Pattern already established by the existing tests (lines 65, 77, 92, 110, 125) — no issue.

**AI-Review Pass 2:** Skipped per thin-plan UI-only rule (orchestrator: ai_review_parallel=off).

### 🔴 Blocking
_None._

### 🟡 Non-Blocking
1. [Agent] — `web_push_plugin.py` — Consider whether `_PUSH_HEADERS` should be a plain `dict` constant (mutable, could theoretically be modified by a caller passing it by reference). For a single-user hobby app with no concurrent mutation this is not a real risk, but `frozenset` or a `types.MappingProxyType` wrapper would make the immutability intent match the frozen-dataclass pattern already used in the same file. YAGNI applies here — flagging only for awareness.
2. [Agent] — Verification section B (deploy steps) instructs bumping `frontend/package.json` to `2.7.2`. This is correct per the release convention, but the plan does not mention updating `CHANGELOG.md` with the backend-side root cause detail. Minor omission given the single-user context.

### Verdict
APPROVED — all Pass-0 anchors verified against live code, single callsite confirmed, test mirrors established convention correctly, no blocking issues.
