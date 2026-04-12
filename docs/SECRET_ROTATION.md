# Secret Rotation Procedures

How to rotate each secret used by RC-Markt Scout. All operations require SSH access to the VPS.

---

## 1. JWT_SECRET

**Effect of rotation:** All active sessions are immediately invalidated. Every user must log in again.

```bash
# 1. Generate a new secret
python3 -c "import secrets; print(secrets.token_hex(32))"

# 2. SSH into VPS and update .env
ssh deploy@152.53.238.3
nano /opt/rcn-scout/.env
# Replace JWT_SECRET=<old> with JWT_SECRET=<new>

# 3. Restart the backend container (only backend reads JWT_SECRET)
cd /opt/rcn-scout
docker compose -f docker-compose.prod.yml restart backend

# 4. Verify
curl -s https://rcn-scout.d2x-labs.de/health
# Expected: {"status":"ok"}
# Browser: existing session should redirect to login page
```

---

## 2. GOOGLE_CLIENT_SECRET

**Effect of rotation:** Existing sessions remain valid (JWT-based). Only new OAuth logins use the client secret. During the brief window between secret change in Google Console and VPS update, new logins will fail.

```bash
# 1. Go to Google Cloud Console > APIs & Services > Credentials
#    Select the OAuth 2.0 Client ID for rcn-scout
#    Click "Reset Secret" — copy the new secret immediately

# 2. SSH into VPS and update .env
ssh deploy@152.53.238.3
nano /opt/rcn-scout/.env
# Replace GOOGLE_CLIENT_SECRET=<old> with GOOGLE_CLIENT_SECRET=<new>

# 3. Restart the backend
cd /opt/rcn-scout
docker compose -f docker-compose.prod.yml restart backend

# 4. Verify: open browser, logout, login again via Google
```

---

## 3. DB_PASSWORD

**Effect of rotation:** Requires coordinated update of both PostgreSQL and the backend. Brief downtime expected.

```bash
# 1. SSH into VPS
ssh deploy@152.53.238.3
cd /opt/rcn-scout

# 2. Change the password inside PostgreSQL
docker compose -f docker-compose.prod.yml exec db \
  psql -U rcscout -d rcscout -c "ALTER USER rcscout PASSWORD 'NEW_PASSWORD_HERE';"

# 3. Update .env with the new password
nano /opt/rcn-scout/.env
# Replace DB_PASSWORD=<old> with DB_PASSWORD=<new>

# 4. Restart backend (picks up new DATABASE_URL from env)
docker compose -f docker-compose.prod.yml restart backend

# 5. Verify
curl -s https://rcn-scout.d2x-labs.de/health
# If backend can't connect to DB, health check will fail
```

**Important:** DB_PASSWORD must be URL-safe (no `@`, `:`, `/`, `%` characters) because it is interpolated into the DATABASE_URL connection string.

---

## 4. VPS SSH Key (used by CI/CD)

**Effect of rotation:** CI/CD deployments will fail until the new key is configured in GitHub Secrets.

```bash
# 1. On VPS: generate a new key pair for the deploy user
ssh deploy@152.53.238.3
ssh-keygen -t ed25519 -f ~/.ssh/id_deploy_new -C "deploy@rcn-scout"
cat ~/.ssh/id_deploy_new.pub >> ~/.ssh/authorized_keys

# 2. Test the new key from your local machine
ssh -i /path/to/id_deploy_new deploy@152.53.238.3 "echo ok"

# 3. Update GitHub Secrets
#    Repository > Settings > Secrets and variables > Actions
#    Update VPS_SSH_KEY_STAGING with the contents of the new PRIVATE key

# 4. Remove the old key from authorized_keys on VPS
#    Edit ~/.ssh/authorized_keys and remove the old key line

# 5. Verify: trigger a deploy (push to main or re-run workflow)
```

---

## 5. GitHub Container Registry (ghcr.io) PAT

If a Personal Access Token is used on the VPS to pull images (instead of public packages):

```bash
# 1. Create a new PAT on GitHub
#    Settings > Developer settings > Personal access tokens
#    Scope: read:packages

# 2. On VPS: update Docker login
ssh deploy@152.53.238.3
echo "NEW_PAT" | docker login ghcr.io -u marcoroth1983 --password-stdin

# 3. Verify: pull an image
docker pull ghcr.io/marcoroth1983/rc-network-scraper/backend:latest
```

---

## When to Rotate

- **Immediately** if any secret is suspected to be compromised
- **JWT_SECRET**: if the `.env` file on VPS was accessed by an unauthorized party
- **GOOGLE_CLIENT_SECRET**: if it appears in logs, git history, or shared channels
- **DB_PASSWORD**: if database access is suspected from outside the Docker network
- **SSH Key**: if the GitHub repository secrets are compromised or the key was shared
