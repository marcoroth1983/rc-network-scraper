# Backlog

## Open

- **NOTIFY-01: Per-User Telegram Notifications** — Enable users to receive personal Telegram alerts for their saved searches. Dedicated Telegram bot ("RC-Scout-Bot"), one per project. Account linking via deep-link token pattern: user clicks "Telegram verbinden" on profile page → app generates one-time token → user opens `t.me/RcScoutBot?start=<token>` → bot receives `/start <token>` + Telegram Chat-ID → backend stores `user_id ↔ telegram_chat_id`. Sending is a plain HTTP POST to Telegram API, no SDK or daemon needed. Supports per-user targeting — each user gets only alerts for their own searches. 3 active users currently. See also: MFC-Bussard project memory `reference_telegram_bot_pattern.md` for full pattern documentation.
