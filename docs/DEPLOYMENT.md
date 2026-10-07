# Deployment guide

How to put Bolo upay online on your own server, with HTTPS, in about 30 minutes.
HTTPS is required: browsers block the microphone on plain `http://`.

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
# {"ok":true,"llm":"gemini","model":"logistic_regression"}   (llm is null without a key)
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
flutter run -d <iphone> --dart-define=API_BASE=https://bolo.example.com        # iPhone (Xcode, Mac)
```

## 9. Security notes

- Never commit `.env`; it is already in `.gitignore`.
- The prototype uses synthetic users and a demo PIN. Do not enter real names, numbers or PINs.
- Every screen shows a "prototype, not the official upay app" ribbon; keep it.
