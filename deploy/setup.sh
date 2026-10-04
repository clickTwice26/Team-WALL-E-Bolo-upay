#!/usr/bin/env bash
# One-command deploy for Bolo upay on a fresh Ubuntu/Debian server.
#
#   curl -fsSL https://raw.githubusercontent.com/clickTwice26/Team-WALL-E-Bolo-upay/main/deploy/setup.sh \
#     | sudo DOMAIN=bolo.example.com bash
#
# Optional:  LLM_PROVIDER=gemini LLM_API_KEY=... LLM_MODEL=gemini-2.5-flash
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
cat > .env <<EOF
DOMAIN=${DOMAIN}
LLM_PROVIDER=${LLM_PROVIDER:-}
LLM_API_KEY=${LLM_API_KEY:-}
LLM_MODEL=${LLM_MODEL:-}
HOLD_SECONDS=${HOLD_SECONDS:-30}
CORS_ORIGINS=*
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
