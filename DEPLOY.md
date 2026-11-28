# Deploying NSE Relative Strength (Docker, VPS in India)

The production stack is three containers on one server:

```
 browser ──HTTPS──▶ caddy (TLS, gzip, HSTS) ──▶ web (FastAPI + React app, login)
                                                  │  reads
                                    data volume ◀─┤  rs_data.json, nse_*.csv, users.json
                                   cache volume ◀─┘  price caches, NSE archive
                                                  ▲  writes
                         worker (scheduler: 18:30 build, hourly catch-up, backups)
```

* **web** — the API and the site.  Private: every page and API call needs a
  login (`backend/auth.py`); admins can also start a price update and edit the
  Telegram watchlist.
* **worker** — runs `cron_daily.sh` on the IST timetable in `deploy/scheduler.py`
  (new listings → events → FII/DII → build → audit → Telegram brief) and a
  daily backup.  It has Chromium for NSE's listing page.
* **caddy** — gets and renews the HTTPS certificate for your domain by itself.

> **Why a server in India:** NSE's official daily price file, the listing
> data and the FII/DII figures only answer Indian IP addresses.  A server in
> Mumbai or Bangalore runs the whole pipeline; elsewhere the build falls back
> to Yahoo-only data and misses NSE's corrections.

## 1 · The server

| | Minimum | Recommended |
|---|---|---|
| CPU / RAM | 2 vCPU / 2 GB | 2 vCPU / **4 GB** (the build holds ~2,600 price histories in memory) |
| Disk | 25 GB | 40 GB SSD |
| OS | Ubuntu 24.04 LTS | |
| Region | **Mumbai (ap-south-1) or Bangalore** | |

Examples: AWS Lightsail *Mumbai* 4 GB plan, DigitalOcean *BLR1* 4 GB droplet,
Azure *Central India*, Google Cloud *asia-south1*.

**Domain:** point an `A` record (e.g. `rs.yourdomain.com`) at the server's
public IP before the first start — Caddy needs it to issue the certificate.

## 2 · Prepare the server (once)

```bash
ssh ubuntu@SERVER_IP

# updates + firewall (SSH, HTTP for the certificate challenge, HTTPS)
sudo apt update && sudo apt -y upgrade && sudo apt -y install unattended-upgrades git
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw --force enable

# Docker Engine + Compose plugin (official repository)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
docker compose version
```

Use SSH keys and turn off password logins (`PasswordAuthentication no` in
`/etc/ssh/sshd_config`).

## 3 · Deploy

```bash
git clone https://github.com/dopawire/nse-relative-strength.git
cd nse-relative-strength
cp .env.example .env
nano .env        # SITE_ADDRESS=rs.yourdomain.com, NSE_RS_SECRET=$(openssl rand -hex 32)

docker compose up -d --build
docker compose exec web python -m backend.users add YOUR_NAME --admin   # asks for a password
```

Open `https://rs.yourdomain.com` and sign in.  The first start seeds the data
volume with the snapshot in the image, so the site works immediately; the
worker's first evening build fills the caches (≈ 5–10 minutes: two years of
prices plus NSE's last 300 daily files).

### Optional: bring the current caches along (instant first build)

From the machine that runs the pipeline today:

```bash
tar czf nse-rs-cache.tgz -C ~/.cache nse-rs
scp nse-rs-cache.tgz ubuntu@SERVER_IP:~/nse-relative-strength/
```

On the server:

```bash
docker compose stop worker web
docker run --rm -v nse-rs_cache:/cache -v "$PWD":/in alpine \
  sh -c 'tar xzf /in/nse-rs-cache.tgz -C /tmp && cp -r /tmp/nse-rs/. /cache/ && chown -R 10001:10001 /cache'
docker compose start web worker
```

## 4 · Everyday operations

| Task | Command |
|---|---|
| Status | `docker compose ps` · `curl -s https://rs.yourdomain.com/api/health` |
| Pipeline log | `docker compose exec worker tail -n 100 /data/run.log` |
| Scheduler log | `docker compose logs -f worker` |
| Run the build now | `docker compose exec worker bash cron_daily.sh` |
| Update to the latest code | `git pull && docker compose up -d --build` |
| Users | `docker compose exec web python -m backend.users list` · `add NAME [--admin]` · `passwd NAME` · `remove NAME` |
| Telegram brief | set `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` in `.env`, then `docker compose up -d` |

**Backups:** the worker writes `/data/backups/nse-rs-YYYYMMDD-HHMM.tar.gz`
every night at 02:15 (data volume + NSE archive, 14 kept).  Copy them off the
server now and then:

```bash
docker compose cp worker:/data/backups ./backups
```

Restore: stop `web` and `worker`, extract a backup's `data/` into the `data`
volume (and `cache/.nse_archive.json` into `cache`), start them again.

## 5 · Security notes

* Passwords are scrypt-hashed; sessions are signed, HttpOnly, `SameSite=Strict`,
  HTTPS-only cookies that expire after 14 days (`NSE_RS_SESSION_DAYS`).
  Changing a password signs that user out everywhere.
* 10 failed logins from one address or for one user lock them out for 15 minutes.
* Write actions need an admin plus a custom request header (CSRF protection);
  responses carry a strict Content-Security-Policy, `X-Frame-Options: DENY`,
  HSTS (Caddy) and no-store caching for data.
* Only Caddy is published (ports 80/443); the app port is internal.  The
  containers run as an unprivileged user.
* Keep `.env` out of git (it is in `.gitignore`).
* **The old public site:** GitHub Pages still serves the pre-2.0 static
  snapshot, refreshed by the home machine's cron (`PUBLISH_SITE=1`) and the
  `daily_build.yml` workflow.  For a private setup, turn those off and disable
  Pages (repo → Settings → Pages), and consider making the repository private —
  it carries the daily data snapshots.

## 6 · Local development

```bash
bash run_server.sh                 # API + built app on http://127.0.0.1:8000 (login off on localhost)
cd frontend && npm run dev         # hot-reloading app on :5173, proxies /api to :8000
npm test                           # unit tests (vitest)
python -m pytest tests/            # API, pipeline and browser smoke tests
```

Run the whole production stack locally with `SITE_ADDRESS=:80` and
`NSE_RS_COOKIE_SECURE=0` in `.env`, then `docker compose up --build` and open
http://localhost.
