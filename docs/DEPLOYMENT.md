# Deployment guide

How to put Bolo upay online on your own server, with HTTPS, in about 30 minutes. Already deployed? Jump to section 0 to update the live server.
HTTPS is required: browsers block the microphone on plain `http://`.

## 0. Quick update of the live server (boloupay.shagato.space)

The live server already runs nginx (with Cloudflare and certbot) in front of the **app container only**, published on `127.0.0.1:28620` by `docker-compose.override.yml` (see `deploy/nginx-boloupay.shagato.space.conf`). To ship the latest `main`:

```bash
ssh <user>@<server>
cd /opt/bolo-upay                       # or wherever the repo is cloned
git pull origin main
```

**Check `.env` before building.** Since R7 the API needs these, or logins break on every restart and admin tools are closed:

```bash
grep -E '^(AUTH_SECRET|DEMO_MODE|ADMIN_TOKEN|LLM_PROVIDER|CONSOLE_STAFF|CONSOLE_TOKEN)=' .env
```

| Variable | Value for the public demo |
|---|---|
| `AUTH_SECRET` | a long random value: `openssl rand -hex 32` (keep it the same across deploys) |
| `DEMO_MODE` | `true` (persona picker, one-tap demo scenarios, reset, default console code) |
| `ADMIN_TOKEN` | a long random value (`openssl rand -hex 24`) for `X-Admin-Token` ops calls |
| `LLM_PROVIDER` / `LLM_API_KEY` | `gemini` and your key (demo only; production uses a local model, see README) |
| `CONSOLE_STAFF` | `Mitu:<password>,Rafi:<password>`, or leave empty to use the code `support-demo` (demo mode only) |

Add any missing line, e.g. `echo "AUTH_SECRET=$(openssl rand -hex 32)" >> .env`, then rebuild only the app container (nginx keeps running):

```bash
docker compose up -d --build app
docker compose ps                          # app should be "healthy" after ~30 s
docker compose logs --tail=50 app          # no tracebacks
curl -s https://boloupay.shagato.space/api/health
# {"ok":true,"llm":"gemini","tts":true,"model":"gradient_boosting"}
```

**Smoke test (2 minutes)** in Chrome at `https://boloupay.shagato.space`:
1. Unlock with PIN `1234`. The home screen shows the upay agent icon and the **Demo scenarios** card.
2. Tap **1. Fake upay employee** → RED, the authentication ladder highlights the 30-second hold, "Why?" lists the reasons.
3. Tap **2. Wrong recipient** → "Which Rahim?". Tap **3. Unusually large amount** → "Did you mean ৳350?".
4. `https://boloupay.shagato.space/console/` opens the support console sign-in.
5. Without a token, `curl -s https://boloupay.shagato.space/api/me` returns `401`.

If the build or start fails, roll back to the previous commit: `git log --oneline -5`, `git checkout <previous-merge>`, `docker compose up -d --build app`, then `git checkout main` once fixed. Cloudflare may cache the old web app for a few minutes; the server sends `Cache-Control: no-cache`, so a hard refresh (Ctrl+Shift+R) shows the new build.

**Android APK for the judges** (from your machine):

```bash
cd app && flutter build apk --release --dart-define=API_BASE=https://boloupay.shagato.space
# app/build/app/outputs/flutter-apk/app-release.apk
```

## 1. What you need

| Item | Minimum |
|---|---|
| Server | Ubuntu 22.04/24.04 or Debian 12, 2 vCPU, 4 GB RAM, 20 GB disk (the Flutter build needs the RAM) |
| Access | SSH with `sudo` |
| Domain | A domain or subdomain you control, e.g. `bolo.example.com` |
| Network | Ports **80** and **443** open to the internet |
| Optional | A Gemini or OpenAI API key for the second parsing path |

## 2. Point the domain at the server

In your DNS provider, add an **A record**:

| Type | Name | Value | TTL |
|---|---|---|---|
| A | `bolo` (or `@` for the root domain) | your server's public IPv4 | 300 |

Check it before continuing (it can take a few minutes):

```bash
dig +short bolo.example.com     # must print your server's IP
```

Also open ports 80 and 443 in your cloud provider's firewall / security group.

## 3. Deploy

```bash
ssh <user>@<server-ip>

git clone https://github.com/clickTwice26/Team-WALL-E-Bolo-upay.git /opt/bolo-upay
cd /opt/bolo-upay
sudo DOMAIN=bolo.example.com bash deploy/setup.sh
```

With the optional LLM (fine for the demo; production should use a local model, see the README section "LLM today, local model in production"):

```bash
sudo DOMAIN=bolo.example.com \
     LLM_PROVIDER=gemini LLM_API_KEY=<your-key> LLM_MODEL=gemini-2.5-flash \
     bash deploy/setup.sh
```

The script installs Docker if needed, writes `.env` (mode 600), opens ports 80/443 in `ufw` if it is active, builds the image and starts two containers:

| Container | Role |
|---|---|
| `app` | FastAPI backend + Flutter web build on port 8000 (internal only) |
| `caddy` | Public entry on 80/443; gets and renews the Let's Encrypt certificate |

The first build takes **10–20 minutes** (it downloads the Flutter SDK image). When it finishes it prints:

```
App is up. Open: https://bolo.example.com   (demo PIN 1234)
```

## 4. Check it works

```bash
curl -s https://bolo.example.com/api/health
# {"ok":true,"llm":"gemini","tts":true,"model":"gradient_boosting"}   (llm is null without a key)
```

Then, in Chrome on a phone or laptop:
1. Open `https://bolo.example.com` and unlock with PIN `1234`.
2. Tap the microphone and allow microphone access.
3. Say "আম্মুকে দেড় হাজার টাকা পাঠাও" and confirm with PIN `1234`.
4. Open `https://bolo.example.com/docs` to see the API.

## 5. Everyday commands

Run these in `/opt/bolo-upay`:

| Task | Command |
|---|---|
| See status | `docker compose ps` |
| Follow logs | `docker compose logs -f app caddy` |
| Update to the latest code | `git pull && docker compose up -d --build` |
| Restart | `docker compose restart` |
| Stop | `docker compose down` |
| Reset demo data | `curl -X POST -H "X-Admin-Token: $(grep ^ADMIN_TOKEN= .env \| cut -d= -f2)" https://bolo.example.com/api/demo/reset` (or the reset button in the app's demo settings when `DEMO_MODE=true`) |
| Change the LLM key | edit `.env`, then `docker compose up -d` |
| Add support-console staff | set `CONSOLE_STAFF=Mitu:<password>,Rafi:<password>` in `.env`, then `docker compose up -d` |
| Turn the demo controls off | set `DEMO_MODE=false` in `.env` (no persona picker, reset or default console code), then `docker compose up -d` |

Data (SQLite) lives in the Docker volume `bolo-data` and survives restarts and updates.

## 6. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Browser shows a certificate error, or Caddy logs `challenge failed` | DNS is not pointing at the server yet, or port 80 is closed. Check `dig +short <domain>` and the cloud firewall, then `docker compose restart caddy`. |
| Build stops with `killed` or exit code 137 | Not enough RAM. Add swap: `sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`, then rerun the script. |
| `port is already allocated` on 80 or 443 | Another web server (nginx, Apache) is running. Stop it: `sudo systemctl disable --now nginx apache2`. |
| Page loads but says it cannot reach the server | The `app` container is not healthy. Run `docker compose logs --tail=80 app`. |
| Microphone button does nothing | Use Chrome or Edge over **https**. Safari and Firefox have limited speech support. Typing always works. |
| `llm` is `null` in `/api/health` | No key set, or the key is wrong. The app still works on the rule parser. Check `.env` and `docker compose logs app`. |
| Git clone asks for a password | The repository is private. Make it public, or clone with a GitHub personal access token. |

## 7. Without a domain (fallback)

Without a domain there is no HTTPS, so voice input will not work for remote users. For a local demo on your own laptop, voice works on `localhost`:

```bash
pip install -r api/requirements.txt
cd app && flutter build web --release --no-web-resources-cdn && cd ..
cd api && DEMO_MODE=true uvicorn app.main:app --port 8000
# open http://localhost:8000 in Chrome
```

## 8. Mobile apps against the deployed server

```bash
cd app
flutter build apk --release --dart-define=API_BASE=https://bolo.example.com   # Android
```

## 9. Security notes

- Never commit `.env`; it is already in `.gitignore`.
- The prototype uses synthetic users and a demo PIN. Do not enter real names, numbers or PINs.
- Every screen shows a "prototype, not the official upay app" ribbon; keep it.
