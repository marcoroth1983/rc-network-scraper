# Changelog

## [1.8.0] - 2026-04-18

### Changed

**LLM-Extraktor: kontrolliertes Vokabular für Modelltypen (PLAN-021)**
- `model_type` und `model_subtype` werden jetzt auf feste Erlaubt-Listen geclampt — unbekannte LLM-Werte landen automatisch als `null`
- LLM-Prompt listet exakte Subtypen je Kategorie auf statt offener Beispiele
- Bestandsdaten (3500+ Listings) einmalig normalisiert: `high-wing`/`highwing` → `hochdecker`, `3D` → `3d` etc.
- Suche durchsucht jetzt Titel, Hersteller, Modellname, Typ und Subtyp — nicht mehr Freitext-Beschreibung

---

## [1.7.0] - 2026-04-18

### Changed

**Preisvergleich: Similarity-Ranking statt starrer Gruppen (PLAN-020)**
- Comparables-Modal zeigt jetzt nach Ähnlichkeit sortierte Inserate statt einer fixen Typ-Gruppe
- Preisindikator (deal/fair/expensive) wird nur noch gesetzt wenn das Vergleichscluster homogen genug ist — bewusste Stille für heterogene Daten
- Pro Inserat wird die Ähnlichkeitsstufe angezeigt (sehr ähnlich / ähnlich / entfernt)
- Median-Anzeige im Modal erscheint nur bei homogenem Cluster, sonst ehrlicher leerer Zustand
- Preis-Indikator-Job läuft jetzt unabhängig von der LLM-Analyse alle 15 Minuten

---

## [1.6.0] - 2026-04-17

### Added

**Telegram-Benachrichtigungen (PLAN-019)**
- Jeder User kann seinen Telegram-Account im Profil verknüpfen (Deep-Link, ein Klick)
- Digest-Benachrichtigungen zu neuen Treffern gespeicherter Suchen — werden automatisch nach jedem Scrape-Lauf verschickt, via bestehende Notification-Plugin-Architektur
- Event-Benachrichtigungen bei Statusänderungen an Merklisten-Einträgen: verkauft / Preisänderung / gelöscht / Preisbewertung
- Per-User-Toggles im Profil für jede der 5 Benachrichtigungsarten
- Telegram-Subsystem ist komplett deaktiviert wenn `TELEGRAM_BOT_TOKEN` nicht gesetzt ist (Default)
- Blockierter Bot wird automatisch entknüpft (403-Auto-Unlink nur bei spezifischen Blocked-Fragmenten)
- Webhook-Security: Shared-Secret-Header-Prüfung, HTTPS-only Deeplink-Validierung im Client

---

## [1.5.0] - 2026-04-16

### Added

- Preisvergleich-Modal: Klick auf Price-Indicator-Badge öffnet eine sortierte Liste aller vergleichbaren Inserate mit Median-Marker, Zustand, Stadt und Preis
- Funktioniert als Desktop-Popover und mobiles Bottom-Sheet mit Swipe-to-Close
- Neuer Endpoint `GET /api/listings/{id}/comparables` mit zweistufiger Gruppierung (Modell → Typ-Fallback)

---

## [1.4.0] - 2026-04-15

### Added

**Dynamische LLM-Kaskade (PLAN-018)**
- Free-Tier-Modelle werden alle 12 Stunden automatisch von OpenRouter aktualisiert
- Pro Anfrage wird die Kaskade durchlaufen; ein Modell das 3 Mal in Folge scheitert wird für 1 Stunde automatisch deaktiviert
- Paid-Fallback `mistralai/mistral-nemo` via `.env` bleibt als letztes Sicherheitsnetz bestehen
- Admin-Panel im Profil (nur für Admin-Rolle) zeigt aktive Modelle, Aktiv-Status, Kontext-Länge, letzten Fehler und einen manuellen Refresh-Button
- Neue DB-Tabelle `llm_models` mit `is_active`, `disabled_until`, `consecutive_failures`, `last_error` und Timestamps
- Admin-Endpoints `GET /api/admin/llm-models` und `POST /api/admin/llm-models/refresh` (beide admin-only)
- Scheduler-Logging zeigt bei jedem Refresh: added / kept / removed Modelle

### Fixed

- Frontend: Listings-Seite behält beim Öffnen und Schließen des Detail-Modals Filter, Scroll-Position und Suchparameter bei
- Frontend: Kein infiniter Loop mehr beim Direkt-Öffnen von `/listings/:id` Cold-Links

### Changed

- Frontend: `window.confirm()` ersetzt durch Aurora-Glass-Confirmation-Dialog mit Focus-Trap, Escape/Enter und Scale-Animation

---

## [1.2.0] - 2026-04-14

### Added

**LLM-Analyse & Preisindikator (PLAN-014)**
- LLM-Hintergrundworker (alle 2 min, 3 Inserate/Lauf) mit OpenRouter: extrahiert Hersteller, Modell, Typ, Antrieb, Vollständigkeit, Versand-Verfügbarkeit
- Preiskorrektur: LLM-geparster Preis überschreibt `price_numeric` bei deutschen Zahlenformaten (z.B. "VB. 4.500 Euro")
- Preisindikator `deal` / `fair` / `expensive` — gespeichert in DB per SQL-Job (Median ±25%, min. 5 Vergleichsinserate)
- Filter-Chips in der Suche: "Versand möglich" und "Nur Schnäppchen"
- Neue API-Filter: `drive_type`, `completeness`, `model_subtype`, `shipping_available`, `price_indicator`
- Preisindikator-Badge (Schnäppchen/Marktüblich/Hoch) auf Detailseite
- `drive_type`, `completeness`, `shipping_available` in Listing-Karten sichtbar

### Changed
- LLM-Analyse: `analyzed_at`/`analysis_retries` (alter Ansatz) → `llm_analyzed` Boolean-Flag (einfacher, kein Retry-Counter)
- Preisindikator-Wert `"bargain"` → `"deal"` (konsistent mit SQL-Berechnung)
- Analyse-Interval von 2h auf 2min reduziert (3 Inserate pro Lauf, passend zum Free-Tier-Limit)

---

## [1.1.0] - 2026-04-14

### Added

**Benutzer-Merkliste (PLAN-015)**
- Jeder Benutzer hat jetzt seine eigene, unabhängige Merkliste (`user_favorites`-Tabelle mit FK auf `users` + `listings`)
- Bestehende Marco-Favoriten wurden via Email-Lookup migriert
- `is_favorite` und `favorited_at` aus `listings`-Tabelle entfernt

**LLM-Analyse Infrastruktur (Basis für PLAN-014)**
- `backend/app/analysis/` Modul: `extractor.py` (OpenRouter), `job.py` (Hintergrundworker), `backfill.py` (CLI)
- OpenRouter-Config: Primary `qwen/qwen3-30b-a3b:free`, Fallback `mistralai/mistral-nemo`
- `openai>=1.40` als Dependency
- DB-Felder für LLM-Daten: `manufacturer`, `model_name`, `model_type`, `model_subtype`, `drive_type`, `completeness`, `attributes`, `llm_analyzed`, `price_indicator`, `shipping_available`
- API-Schemas und Frontend-Types um Analyse-Felder erweitert

**Activity Tracking**
- `last_seen_at` auf `users` — wird bei jedem `/auth/me` aktualisiert
- Benutzeridentifizierung in Backend-Logs

### Fixed
- **OAuth 500**: Doppelter Callback (zweiter Request nach Button-Klick) führte zu `httpx.HTTPStatusError` vom Google-Token-Endpunkt → wird jetzt abgefangen und zu `/login?error=denied` weitergeleitet
- **OAuth 400**: Ungültiger State löst jetzt Redirect statt HTTP 400 aus
- **Login-Button**: Deaktiviert nach erstem Klick (verhindert Doppelklick-Fehler)
- **Preisparser**: `"VB. 4.500 Euro"` wurde fälschlicherweise als `0.45` geparst — führende Nicht-Ziffern werden jetzt korrekt entfernt
- `ScrapeSummary.deleted_sold` → `cleaned_sold` (korrekter Feldname des Orchestrators)

---

## [1.0.0] - 2026-04-13

### Added

**Auth & Roles**
- User role enum (`member` / `admin`) on the `users` table — default `member`
- "Als verkauft markieren" button on detail page visible to admins only
- Scrape-Log button in header visible to admins only
- Admin role auto-assigned via `init_db` migration for configured email

**Detail Page**
- Hero image (first image, full-width) above the content card
- Remaining images shown as a scrollable gallery below the description
- "Weitere von {author}" section at the bottom — 3-column grid on desktop, single column on mobile
- `GET /api/listings/by-author` endpoint for fetching listings by the same author

**Mobile UI**
- Sticky full-width search bar with PLZ status indicator (green location icon / red "!" badge)
- Filter bottom sheet modal with slide-up animation via `createPortal`, swipe-down to dismiss
- Backdrop tap to close filter modal
- X button removed from filter modal (replaced by swipe + backdrop tap)
- Mobile footer Merkliste badge replaced with a dot (count shown on Merkliste page instead)
- Unread badge on "Suchen" tab in FavoritesPage (fix: `markViewed` called only on unmount)
- Back button removed from Profile page (footer handles navigation)
- Spacing above "← Zurück zur Liste" button on detail page

**Desktop UI**
- Second sticky bar (PlzBar) with search, sort, filter popover, and person dropdown
- Filter popover: category, distance, price range
- Person dropdown: user avatar with initials, "Mein Standort" PLZ input, logout
- PLZ status indicator in search input (green chip / red "!") — opens person dropdown on click
- Merkliste button moved to main header with unread count badge

**Filters**
- Price range filter (`price_min` / `price_max`) on both desktop popover and mobile modal
- Backend validates `price_min <= price_max`, filters on `price_numeric` column

**Login Page**
- Slim footer with Datenschutzerklärung link
- Privacy policy modal (scrollable, closeable)

**PWA**
- Install prompt
- Homescreen icon

### Fixed
- Mobile search bar now truly sticky (removed `pt-4` top padding that caused pre-sticky scroll)
- Filter panel full-width on mobile via `-mx-3`
- Bottom sheet z-index issue resolved via `createPortal` (sticky parent created stacking context)
- Trash button on FavoriteCard aligned to card padding (`top-3` instead of `top-0`)
- Unread badge visible during Merkliste page visit (deferred `markViewed` to unmount)
- Input text color softened from pure white to `rgba(248,250,252,0.85)`

### Infrastructure
- CI deploys only on GitHub Release (not on every push to `main`)
- HSTS, security headers, health check on deploy
- Deploy splits into separate build and deploy jobs
