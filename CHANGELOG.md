# Changelog

## [2.3.0] - 2026-04-19

### Removed

**Preisbewertung (Median-System) entfernt (PLAN-025)**
- Badge „Günstig / Fair / Teuer" auf Listing-Karten entfernt
- Filter-Chip „Nur Günstige" entfernt (Mobile + Desktop)
- DB-Spalten `price_indicator`, `price_indicator_median`, `price_indicator_count` gelöscht
- Hintergrund-Job `recalculate_price_indicators` entfernt
- Telegram-Benachrichtigung „Preisbewertung geändert" + Preference `fav_indicator` entfernt
- `similarity.py` + Homogeneity-Bewertung entfernt — wurde nur vom Preis-Job gebraucht

### Changed

**Vergleichs-Popup („Ähnliche Inserate") vereinfacht**
- Nur noch auf der Detailseite aufrufbar, nicht mehr aus der Karten-Übersicht
- Harte Filter statt Similarity-Score: gleiche Kategorie + (falls am Inserat gesetzt) Modelltyp, Subtyp, Antrieb, Spannweite ±25 %
- Sold + Outdated Inserate werden jetzt mit angezeigt (Preisvergleich)
- Zeigt pro Treffer nur Titel + Preis + Link zur Original-Annonce
- Max. 30 Treffer, nach Datum absteigend sortiert
- Count wird beim Öffnen der Detailseite geladen und als Badge am Button angezeigt; Button ist disabled bei 0 Treffern

### Fixed

- Filter „Nur Verkaufte" und „Ältere anzeigen" wirken jetzt tatsächlich auf die Haupt-Liste. Der `useInfiniteListings`-Hook hat die beiden Flags aus der URL gelesen, aber nicht an die API weitergereicht — URL-Pill aktiv, aber Backend bekam den Default-Feed. Zusätzlich Filter-Dimensionen dedupliziert (`FilterDimensions` + `filterDimensionsEqual`), damit diese Drift-Klasse künftig typ-gesichert auffällt. Regressionstest deckt Pill → Netzwerkaufruf ab.

### Breaking

- `GET /api/listings?price_indicator=…` wird ignoriert (Param entfernt)
- `GET /api/listings/{id}/comparables` liefert neues Response-Schema (`count` + `listings[]` mit `id/title/url/price/price_numeric/posted_at`). Keine `match_quality`, `median`, `similarity_score` mehr.
- `ListingSummary` / `ListingDetail` haben `price_indicator*` nicht mehr

---

## [2.2.0] - 2026-04-19

### Added

**Filter-Toggles „Ältere anzeigen" und „Nur Verkaufte" (PLAN-024)**
- Beide Filter in Mobile-Sheet (FilterPanel) und Desktop-Dropdown (PlzBar) unter „Ansicht"
- „Ältere anzeigen" wird deaktiviert, sobald „Nur Verkaufte" aktiv ist
- URL-Parameter `show_outdated` und `only_sold` für teilbare Filter-Links
- ALT-Badge auf ListingCard für veraltete, nicht verkaufte Inserate

### Changed

**Phase 3: veraltete Inserate werden markiert statt gelöscht**
- Inserate älter als 8 Wochen erhalten `is_outdated = TRUE` statt DB-Delete → Historie bleibt erhalten
- Default-Feed (`GET /api/listings`) blendet verkaufte **und** veraltete Inserate aus; Favoriten bleiben unverändert vollständig sichtbar
- ScrapeLog zeigt „X veraltet" statt „X gelöscht" (Feld `ScrapeSummary.marked_outdated` ersetzt `deleted_stale`)

### Breaking

- `GET /api/listings` filtert jetzt Default `is_sold = FALSE AND is_outdated = FALSE` (vorher: alle). Opt-in via `show_outdated=true` bzw. `only_sold=true`.
- `ScrapeSummary.deleted_stale` → `marked_outdated` (Backend + Frontend)

---

## [2.1.1] - 2026-04-19

### Fixed

**Doppelte Suchleiste auf Desktop entfernt**
- v2.1.0 hatte im FilterPanel eine eigene Desktop-Filterleiste hinzugefügt, die parallel zur bestehenden PlzBar angezeigt wurde — zwei Suchfelder übereinander
- FilterPanel ist jetzt wieder mobile-only (Sticky-Suchleiste + Bottom-Sheet)
- PlzBar ist auf Desktop die einzige Suchleiste und wurde um die fehlenden Filter erweitert: Versand, Preis-Bewertung, Modelltyp, Subtyp — damit volle Filter-Parität Desktop ↔ Mobile
- Active-Filter-Badge im Desktop-Filter-Button berücksichtigt jetzt alle Filter

---

## [2.1.0] - 2026-04-18

### Added

**Desktop-Filterleiste mit Dropdown (FilterPanel)**
- Desktop-Ansicht zeigt jetzt eine dedizierte Filterleiste mit Suche, Entfernung und Sortierung direkt sichtbar
- Weitere Filter (Kategorie, Preis, Versand, Preis-Bewertung, Modelltyp, Subtyp) sind über ein Dropdown erreichbar
- Aktive Filter werden im Dropdown-Button durch einen lila Punkt signalisiert
- Klick außerhalb schließt das Dropdown automatisch

**Lifecycle-Timestamps für Inserate (PLAN-007)**
- Neue DB-Spalte `created_at`: Zeitpunkt der Ersterfassung eines Inserats (wird nie überschrieben)
- Neue DB-Spalte `sold_at`: Zeitpunkt, zu dem ein Inserat erstmals als verkauft erkannt wurde (NULL solange aktiv)
- Beide Spalten werden automatisch befüllt — rückwirkend für alle bestehenden Einträge via idempotenter Migration
- Ermöglicht DB-seitige Diagnose: wann wurde ein Inserat erstmals gesehen, wann als verkauft markiert

---

## [2.0.0] - 2026-04-18

### Added

**eBay.de als zweite Anzeigenquelle (PLAN-023)**
- Inserate von eBay.de werden alle 30 Minuten automatisch abgerufen (eBay Browse API)
- eBay-Inserate durchlaufen dieselbe LLM-Analyse und Preisindikator-Pipeline wie rc-network-Inserate
- Alle Listingkarten zeigen ein „eBay"-Badge wenn das Inserat von eBay stammt
- API: `GET /api/listings` akzeptiert neuen Filterparameter `source` (`rcnetwork` oder `ebay`)
- Neue DB-Spalte `source` in der `listings`-Tabelle (Standardwert: `rcnetwork`)
- Verkaufte eBay-Inserate werden stündlich erkannt (HTTP 404 = verkauft/entfernt)

---

## [1.9.0] - 2026-04-18

### Added

**Modelltyp- und Subtyp-Filter (PLAN-022)**
- Filtersheet (Mobile) zeigt zwei neue Dropdowns: Modelltyp (Flugzeug, Hubschrauber, Segler, Multicopter, Boot, Auto) und Subtyp (dynamisch je Typ)
- Subtyp-Dropdown ist deaktiviert solange kein Typ gewählt ist; bei Typwechsel wird Subtyp automatisch zurückgesetzt
- Modelltyp-Sektion wird ausgeblendet wenn die Kategorie den Typ bereits impliziert (rc-cars, Schiffsmodelle)
- Beide Filter werden in der URL persistiert und beim Seitenload wiederhergestellt
- Backend: `GET /api/listings` akzeptiert jetzt `model_type` als Filterparameter (war bisher nur `model_subtype`)

---

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
