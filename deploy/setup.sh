#!/usr/bin/env bash
# One-command deploy for Bolo upay on a fresh Ubuntu/Debian server.
#
#   curl -fsSL https://raw.githubusercontent.com/clickTwice26/Team-WALL-E-Bolo-upay/main/deploy/setup.sh \
#     | sudo DOMAIN=bolo.example.com bash
#
# Optional:  LLM_PROVIDER=gemini LLM_API_KEY=... LLM_MODEL=gemini-2.5-flash
#            DEMO_MODE=false (default true: this script deploys the public demo)
#            CONSOLE_STAFF="Mitu:password,Rafi:password" (named support-console accounts)
# Before running: point the domain's A record at this server and open ports 80 and 443.
set -euo pipefail

: "${DOMAIN:?Set DOMAIN, e.g. DOMAIN=bolo.example.com}"
REPO="${REPO:-https://github.com/clickTwice26/Team-WALL-E-Bolo-upay.git}"
DIR="${DIR:-/opt/bolo-upay}"

echo "==> Installing Docker (if needed)"
if ! command -v docker >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y ca-certificates curl git
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker >/dev/null 2>&1 || true

echo "==> Getting the code into $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only
else
  git clone "$REPO" "$DIR"
fi
cd "$DIR"

echo "==> Writing .env"
# keep secrets from an earlier run so sessions and the admin token survive a redeploy
old() { if [ -f .env ]; then grep -m1 "^$1=" .env | cut -d= -f2- || true; fi; }
random_hex() { od -An -N32 -tx1 /dev/urandom | tr -d ' \n'; }
AUTH_SECRET="${AUTH_SECRET:-$(old AUTH_SECRET)}"; AUTH_SECRET="${AUTH_SECRET:-$(random_hex)}"
ADMIN_TOKEN="${ADMIN_TOKEN:-$(old ADMIN_TOKEN)}"; ADMIN_TOKEN="${ADMIN_TOKEN:-$(random_hex)}"
CONSOLE_STAFF="${CONSOLE_STAFF:-$(old CONSOLE_STAFF)}"
cat > .env <<EOF
DOMAIN=${DOMAIN}
LLM_PROVIDER=${LLM_PROVIDER:-}
LLM_API_KEY=${LLM_API_KEY:-}
LLM_MODEL=${LLM_MODEL:-}
HOLD_SECONDS=${HOLD_SECONDS:-30}
CORS_ORIGINS=*
DEMO_MODE=${DEMO_MODE:-true}
AUTH_SECRET=${AUTH_SECRET}
ADMIN_TOKEN=${ADMIN_TOKEN}
CONSOLE_STAFF=${CONSOLE_STAFF}
EOF
chmod 600 .env

echo "==> Opening firewall ports (if ufw is active)"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q active; then
  ufw allow 80/tcp && ufw allow 443/tcp
fi

echo "==> Building and starting (first build downloads Flutter: 10-20 min)"
docker compose up -d --build

echo "==> Waiting for the app"
for i in $(seq 1 60); do
  if docker compose exec -T app python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')" >/dev/null 2>&1; then
    echo "App is up. Open: https://${DOMAIN}   (demo PIN 1234)"
    exit 0
  fi
  sleep 5
done
echo "App did not answer yet. Check: docker compose logs -f app caddy"
exit 1
