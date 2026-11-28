#!/bin/sh
# Usage: run-container.sh <instance> <port> <wechat|qq>
# Builds the desktop image (upstream wechat-selkies plus the input executor) from the container/ folder beside this
# script and recreates one desktop running one client.
# DESKTOP_ROOT (default ~/.local/share/wechat-selkies) holds the shared password and frame-ancestors files and one folder
# per instance with its config volume, master-token and browser-token, and the machine identity the clients tie sign-ins
# to: hostname, machine-id, product-uuid and mac-address, generated once on first run so every recreation is the same
# machine.
set -eu
SRC="$(cd "$(dirname "$0")" && pwd)"
D="${DESKTOP_ROOT:-$HOME/.local/share/wechat-selkies}"
IMAGE=message-center-desktop:local
NAME="$1"; PORT="$2"; APP="$3"
I="$D/$NAME"
case "$APP" in
  wechat) WECHAT=true; QQ=false ;;
  qq) WECHAT=false; QQ=true ;;
  *) echo "app must be wechat or qq" >&2; exit 2 ;;
esac
hex() { od -An -N"$1" -tx1 /dev/urandom | tr -d ' \n'; }
if [ ! -f "$I/hostname" ]; then
  set -- OptiPlex-7090 ThinkCentre-M70q Vostro-3910 ProDesk-400-G7
  shift $(( $(od -An -N1 -tu1 /dev/urandom) % 4 ))
  echo "iris-$1" > "$I/hostname"
fi
[ -f "$I/machine-id" ] || hex 16 > "$I/machine-id"
[ -f "$I/product-uuid" ] || hex 16 | sed -E 's/(.{8})(.{4})(.{4})(.{4})(.{12})/\1-\2-\3-\4-\5/' > "$I/product-uuid"
# Realtek's OUI, the NIC most desktops ship with.
[ -f "$I/mac-address" ] || hex 3 | sed -E 's/(..)(..)(..)/00:e0:4c:\1:\2:\3/' > "$I/mac-address"
HOST="$(cat "$I/hostname")"
# Without provenance attestations an unchanged build keeps the same image id, so all instances share one image.
docker build --pull --provenance=false -q -t "$IMAGE" "$SRC" >/dev/null
docker rm -f "selkies-$NAME" >/dev/null 2>&1 || true
docker run -d --name "selkies-$NAME" --hostname "$HOST" --mac-address "$(cat "$I/mac-address")" --restart unless-stopped \
  -v "$I/machine-id:/etc/machine-id:ro" -v "$I/machine-id:/var/lib/dbus/machine-id:ro" \
  -v "$I/product-uuid:/sys/devices/virtual/dmi/id/product_uuid:ro" \
  -p "127.0.0.1:$PORT:3000" --shm-size 1gb --memory 3g \
  -e CUSTOM_USER=iris -e PASSWORD="$(cat "$D/password")" \
  -e SELKIES_ENABLE_BASIC_AUTH=false -e SELKIES_MASTER_TOKEN="$(cat "$I/master-token")" \
  -e SELKIES_TOKENS_FILE=/config/selkies-tokens.json -e SELKIES_FRAME_ANCESTORS="$(cat "$D/frame-ancestors")" \
  -e SELKIES_AUDIO_ENABLED=false -e SELKIES_PRINTING_ENABLED=false -e SELKIES_ENABLE_DUAL_MODE=false \
  -e AUTO_START_WECHAT="$WECHAT" -e AUTO_START_QQ="$QQ" -e TZ=Asia/Shanghai \
  -v "$I/config:/config" "$IMAGE"
