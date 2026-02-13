# Deployment & Webhook Setup Guide

## Prerequisites

- Python 3.9+
- Poetry
- A server with a public domain and HTTPS (for webhooks)
- Notion integration token
- Todoist API token

## 1. Install Dependencies

```bash
# Install Poetry (if not installed)
curl -sSL https://install.python-poetry.org | python3 -

# Install project dependencies
cd /path/to/notion-todoist-sync
poetry install
```

## 2. Configure Environment

Copy `.env.example` or create `.env` in the project root:

```env
NOTION_TOKEN=your_notion_integration_token
NOTION_DATABASE_ID=your_notion_database_id
TODOIST_TOKEN=your_todoist_api_token

# Webhook Configuration
WEBHOOK_URL=https://your-domain.com
WEBHOOK_PORT=8001
TODOIST_WEBHOOK_SECRET=your_todoist_webhook_secret
NOTION_WEBHOOK_SECRET=your_notion_webhook_secret

# Sync Configuration
CONFLICT_RESOLUTION_STRATEGY=last_modified_wins
SYNC_STATE_DB_PATH=sync_state.db
```

Also ensure `config/sync_config.json` and `config/webhook_config.json` are present (copy from the repo).

## 3. Run Locally (Development)

```bash
# With ngrok for HTTPS tunneling
ngrok http 8000

# In another terminal
make webhook
```

## 4. Deploy to a Server

### Set up nginx reverse proxy

Add these location blocks to your nginx HTTPS server config:

```nginx
location /webhooks/ {
    proxy_pass http://127.0.0.1:8001;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /todoist/ {
    proxy_pass http://127.0.0.1:8001;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Then reload nginx:

```bash
nginx -t && systemctl reload nginx
```

### Create systemd service

Create `/etc/systemd/system/notion-todoist-sync.service`:

```ini
[Unit]
Description=Notion-Todoist Sync Webhook Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/Projects/notion-todoist-sync
ExecStart=/root/.local/bin/poetry run python -m notion_todoist_sync.webhook_server
Restart=on-failure
RestartSec=5
Environment=WEBHOOK_PORT=8001

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
systemctl daemon-reload
systemctl enable notion-todoist-sync
systemctl start notion-todoist-sync
```

### Managing the service

```bash
# Check status
systemctl status notion-todoist-sync

# View logs (live)
journalctl -u notion-todoist-sync -f

# Restart after code changes
cd /root/Projects/notion-todoist-sync && git pull && systemctl restart notion-todoist-sync

# Check sync status via API
curl https://your-domain.com/sync-status
```

## 5. Register Webhooks

Both Notion and Todoist webhooks need to be registered whenever the webhook URL changes (e.g., new domain or new server).

### Notion Webhook

1. Go to [Notion Developer Portal](https://www.notion.so/my-integrations)
2. Select your integration
3. Go to **Webhooks** (or Automations) section
4. Add a new webhook with URL: `https://your-domain.com/webhooks/notion`
5. Notion will send a verification request:
   - It first sends a GET with `?challenge=xxx` (handled automatically)
   - Then it sends a POST with a `verification_token` in the body
   - Watch the server logs for `VERIFICATION TOKEN: xxx`
   - Copy that token and paste it into the Notion UI to complete verification
6. Select the database(s) you want to watch for changes

### Todoist Webhook

1. Go to [Todoist App Management](https://developer.todoist.com/appconsole.html)
2. Select your app (or create one)
3. Under **Webhooks**, set the URL to: `https://your-domain.com/todoist/webhooks/todoist`
4. The webhook secret is shown in the app settings — put it in `.env` as `TODOIST_WEBHOOK_SECRET`
5. Todoist requires OAuth activation:
   - The app needs at least one user to authorize it
   - Visit the OAuth authorization URL for your app to activate webhooks

### Verifying webhooks work

After registration, make a small change in Notion or Todoist and check the logs:

```bash
journalctl -u notion-todoist-sync -f
```

You should see incoming webhook events and sync processing messages.

## Webhook Endpoints Summary

| Endpoint | Method | Purpose |
|---|---|---|
| `/webhooks/notion` | GET | Notion challenge verification |
| `/webhooks/notion` | POST | Receive Notion events |
| `/todoist/webhooks/todoist` | POST | Receive Todoist events |
| `/sync-status` | GET | Check sync status (via nginx alias) |
| `/health` | GET | Health check |
