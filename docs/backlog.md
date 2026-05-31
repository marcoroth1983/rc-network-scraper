# Backlog

## Open

- **FE-CLEANUP-01: `ProfilePage` `onUserReload` prop is dead plumbing** — `App.tsx` passes `reloadUser` → `ProfilePage` `onUserReload`, but the component never destructures/uses it (leftover after TelegramPanel removal in PLAN-027). Flagged in PLAN-027 and PLAN-029 reviews. Either wire it up for a future in-profile reload action, or drop the prop + the `reloadUser` chain through `App.tsx`. Cosmetic, no breakage. _Aus PLAN_029 Review, 2026-05-31._

- **PLAN027-M1: `vite.config.ts` vitest `globals:true` widerspricht CLAUDE.md-Konvention** — CLAUDE.md schreibt explizite Vitest-Imports vor (`import { describe, it, expect, vi } from 'vitest'`), aber `vite.config.ts` setzt `globals: true`. Pre-existing deviation — nicht in PLAN-027 eingeführt. Klären: entweder `globals: false` setzen und alle Testdateien auf explizite Imports umstellen, oder CLAUDE.md-Konvention anpassen. Nicht in PLAN-027 angefasst, da Änderung bestehende Tests brechen könnte. _Aus PLAN_027 Review Cycle 1, 2026-05-31._

- ~~**PUSH-01: `send_web_push_to_user` blocks the event loop**~~ — **Fixed in PLAN-027 Review Cycle 1 (2026-05-31)**. `webpush()` now wrapped in `asyncio.to_thread(webpush, ...)` in `web_push_plugin.py`.

- **PUSH-03: N+1 sessions in fav_sweep.py** — `run_fav_status_sweep` opens one DB session per favorite row for the snapshot UPDATE (N+1 pattern). Acceptable at single-user scale; could be batched if sweep latency ever becomes a problem. _PLAN_027 Review Cycle 1, zurückgestellt: YAGNI single-user._

- **PUSH-04: 3 sessions in send_web_push_to_user helper** — `send_web_push_to_user` opens up to 3 separate DB sessions (load subs, GC stale, bump last_used_at). Could be merged into one session. Negligible overhead at single-user scale. _PLAN_027 Review Cycle 1, zurückgestellt: YAGNI single-user._

- **PUSH-02: Stacked push/install banner overlap on very short screens** — `FirstStartPushPrompt` is positioned at `bottom-[140px]` to stack above `InstallPrompt` (`bottom-[72px]`). On very short mobile viewports the two glassmorphism banners can overlap. Cosmetic only; both are `sm:hidden` and dismissable. Revisit if it becomes annoying in practice (e.g. suppress the push banner while the install banner is visible). _Aus PLAN_027 Review 2026-05-30._

- **TEST-01: Pre-existing Frontend-Test-Failure `DetailPage — case 16: lg:grid-cols-12`** — Der Test `src/pages/__tests__/DetailPage.test.tsx` (Case 16) prüft `document.querySelector('.lg\\:grid-cols-12')` und erwartet truthy, aber die aktuelle DetailPage-Implementierung hat keinen 12-Spalten-Grid-Wrapper mehr. Test war rot vor PLAN-024 und ist weiter rot nach PLAN-025. Entscheidung nötig: entweder (a) Test streichen/anpassen an die tatsächliche Layout-Implementierung oder (b) DetailPage auf `lg:grid-cols-12` zurück-refactoren, falls das Original-Layout gewünscht ist. Aktuell Rauschen in jeder Plan-Verification — darum Tracking hier statt wiederholtes "pre-existing failure" in jedem Plan-Review. _Gemeldet 2026-04-19 nach PLAN-025._

- **TEST-02: Pre-existing Frontend-Test-Failures `ScrapeLog` (5) + `ListingDetailModal` (2)** — `src/components/__tests__/ScrapeLog.test.tsx` (alle 5 Cases: `getByRole('button')` findet nichts, Body rendert leer) und `src/components/__tests__/ListingDetailModal.test.tsx` (Cases 3+4: `navigate(-1)`/direct-hit close). Verifiziert pre-existing: identische Failures auf `main` ohne jede PLAN-027-Änderung (Check 2026-05-31). Nicht durch Web-Push eingeführt. Entscheidung nötig: reparieren oder an aktuelle Implementierung anpassen. _Gemeldet 2026-05-31 bei PLAN_027 Verification._

- ~~**NOTIFY-01: Per-User Telegram Notifications**~~ — **Superseded by PLAN-027 (2026-05-31)**. Telegram wurde vollständig entfernt und durch Web-Push-Benachrichtigungen ersetzt (per-user, multi-device, inkl. SavedSearch-Treffer + Favoriten-Events). Original-Beschreibung unten zur Historie:
  Enable users to receive personal Telegram alerts for their saved searches. Dedicated Telegram bot ("RC-Scout-Bot"), one per project. Account linking via deep-link token pattern: user clicks "Telegram verbinden" on profile page → app generates one-time token → user opens `t.me/RcScoutBot?start=<token>` → bot receives `/start <token>` + Telegram Chat-ID → backend stores `user_id ↔ telegram_chat_id`. Sending is a plain HTTP POST to Telegram API, no SDK or daemon needed. Supports per-user targeting — each user gets only alerts for their own searches. 3 active users currently. See also: MFC-Bussard project memory `reference_telegram_bot_pattern.md` for full pattern documentation.

- ~~**PRICE-01: Pivot from price indicator to similarity ranking**~~ — **Reverted by PLAN-025 (2026-04-19)**. Das Similarity-Ranking + Median-Indikator-System (PLAN-020) wurde vollständig entfernt und durch eine reine Hart-Attribut-Filterung im `/comparables`-Endpoint ersetzt. Begründung: Median-Mechanik war für den Hobby-Scope zu ungenau; User bevorzugt eine deterministische Filterung (Kategorie + Modelltyp + Antrieb + Spannweite ±25 %).

- **PRICE-02: RC product graph — models + components + "installed vs. included" relations** — Long-term vision, not committed. Build a structured product catalogue that separates **models** (e.g. "Align T-Rex 700X", "E-flite P-51 Mustang 1.5m") from **components** (motors, ESCs, servos, gyros, blades, batteries, receivers), with a per-listing relation tagging each component as `installed`, `spare`, or `unrelated`. Unlocks analytics that no public RC source provides: "which motors are most commonly installed in 700-class helis?", "price spread for T-Rex 700 with Scorpion+Edge vs. Hobbywing", "is this Yak 54 under-equipped for its price?". A price indicator built on top of this graph becomes genuinely meaningful because comparison is "same model + similar component set", not "same words in the title".

  **Why helis first**: heli class system is de-facto standardised (450/550/600/700/800), component slots are strict (motor, ESC, 3× cyclic servo + tail servo, gyro/FBL, main rotor, tail rotor, RX, battery), and hobby community documents builds exhaustively in listings. Non-custom airplanes are a reasonable second pass; custom builds and park fliers are hard and should be deprioritised.

  **Hidden complexities that kill naive approaches**:
  - Entity resolution is the actual hard problem. "Castle Edge 160" vs. "Castle Phoenix Edge HV 160" vs. "Edge 160" may or may not be the same SKU. Amazon/Walmart have 20-person teams on this; in a hobby scope it will only ever be "good enough via manual dedup".
  - Extraction is N× harder than the current flat-attribute extractor: one listing yields 1 model ref + up to ~15 component refs, each with a role. Pydantic strict schema is mandatory.
  - Schema drift: new component categories keep appearing (vario sensor, torque-tube kit, gain setter). Schema must allow controlled extension without every new string becoming a new category.
  - LLM extraction cost scales ~2–4× vs. today (longer structured output, occasional re-extraction on schema changes).

  **Incremental path, each phase abortable**:

  1. **Phase 0 — a weekend, cheap exploration**: Design Pydantic schema for `models`, `components`, `listing_model_ref`, `listing_component_ref`. Build a heli-only extractor POC. Run over 50 hand-picked heli listings, measure extraction quality. **Stop-signal**: abort if useful extraction rate < 70%.
  2. **Phase 1**: Backfill all existing heli listings, one-pass manual dedup (1–2 hours), minimal UI showing "verbaute Komponenten" on the heli detail page.
  3. **Phase 2**: Analytics feature — "What are others installing?" module. Project shifts from scraper to market-observation tool.
  4. **Phase 3**: Extend to non-custom airplanes. Optional: build a price indicator on top of the graph (similarity across model + component set). _Note 2026-04-19: an earlier indicator implementation (PLAN-020) was reverted by PLAN-025; a future revival would need a fresh plan._

  **Data coverage measured on staging 2026-04-18** (3555 active listings, all LLM-analysed):
  - `manufacturer` set: 59%
  - `model_name` set: 80%
  - `wingspan_mm` set: 24% (and 50 garbage values like `"weight_g"`, `"unbekannt"` — schema-validation bug in current extractor)
  - Manufacturer normalisation missing: `CARF`/`Carf`, `JetCat`/`Jetcat` are separate groups today.

  **Alternatives evaluated and not chosen as primary path**:
  - *Sharpen the LLM extractor only*: realistic uplift 24% → ~35–40% for wingspan. Coverage limit is data-bound (text doesn't contain the info), not prompt-bound. Helps, but doesn't solve the matching problem. Still worth doing: strict-schema fix to eliminate the 50 garbage values is cheap.
  - *Per-listing web search* (Perplexity etc.): ~$10 one-off backfill + ~$5/month ongoing for lookups. Works for commercial models (E-flite, Freewing), weak for hobby models ("Kranz Corsair 2,10m"). Consider only as a cache-fill fallback *inside* Phase 0+1, not as primary mechanism.
  - *Embedding-based clustering/canonicalisation* (Google-Shopping-style): self-healing and elegant, but non-trivial infra (sentence-transformers + HDBSCAN/FAISS, merge-split management) for what is still a single-user hobby project.
  - *LLM as label generator + small classifier*: professional pattern, but overkill at current scale.

  **Recommendation as of 2026-04-18**: Do PRICE-01 (similarity ranking) first — gets 80% of user value at 10% of the effort. Treat PRICE-02 Phase 0 as a separate, future exploration that needs explicit go-ahead. Do not commit to full PRICE-02 vision up-front.
