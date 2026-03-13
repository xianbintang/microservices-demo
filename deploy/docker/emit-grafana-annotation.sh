#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTH_FILE="${GRAFANA_AUTH_FILE:-$SCRIPT_DIR/.grafana-auth.env}"
if [[ -f "$AUTH_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$AUTH_FILE"
fi

usage() {
  cat <<'EOF'
Usage:
  emit-grafana-annotation.sh \
    --event <inject_start|mitigation_done> \
    --service <service> \
    --namespace <namespace> \
    --source <caller> \
    [--fault-id <fault_id>] \
    [--incident-id <incident_id>] \
    [--action-id <action_id>] \
    [--deployment <deployment>] \
    [--pod <pod>] \
    [--container <container>] \
    [--note <text>] \
    [--dashboard-uid <uid>]

Auth:
  - Preferred: GRAFANA_SERVICE_ACCOUNT_TOKEN or GRAFANA_TOKEN
  - Fallback:  GRAFANA_USER/GRAFANA_PASSWORD or GRAFANA_USERNAME/GRAFANA_PASSWORD

Env:
  - GRAFANA_URL (optional, default: http://47.83.217.162:3000)
  - GRAFANA_DASHBOARD_UID (optional, default: fffrl21oam2gwa)
  - GRAFANA_AUTH_FILE (optional, default: deploy/docker/.grafana-auth.env)

Local auth file (optional):
  - Default path: deploy/docker/.grafana-auth.env
  - Supported keys: GRAFANA_SERVICE_ACCOUNT_TOKEN / GRAFANA_TOKEN / GRAFANA_USER / GRAFANA_USERNAME / GRAFANA_PASSWORD

Notes:
  - Best-effort caller pattern: call this script and ignore failure if needed.
  - No idempotency check: only call when operation succeeds (no duplicate annotations).
EOF
}

require_arg() {
  local name="$1"
  local value="$2"
  if [[ -z "$value" ]]; then
    echo "ERROR: $name is required" >&2
    exit 1
  fi
}

urlencode() {
  python3 - "$1" <<'PY'
import sys, urllib.parse
print(urllib.parse.quote(sys.argv[1], safe=''))
PY
}

EVENT=""
SERVICE=""
NAMESPACE=""
SOURCE=""
FAULT_ID=""
INCIDENT_ID=""
ACTION_ID=""
DEPLOYMENT=""
POD=""
CONTAINER=""
NOTE=""
GRAFANA_URL="${GRAFANA_URL:-http://47.83.217.162:3000}"
DASHBOARD_UID="${GRAFANA_DASHBOARD_UID:-fffrl21oam2gwa}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --event) EVENT="${2:-}"; shift 2 ;;
    --service) SERVICE="${2:-}"; shift 2 ;;
    --namespace) NAMESPACE="${2:-}"; shift 2 ;;
    --source) SOURCE="${2:-}"; shift 2 ;;
    --fault-id) FAULT_ID="${2:-}"; shift 2 ;;
    --incident-id) INCIDENT_ID="${2:-}"; shift 2 ;;
    --action-id) ACTION_ID="${2:-}"; shift 2 ;;
    --deployment) DEPLOYMENT="${2:-}"; shift 2 ;;
    --pod) POD="${2:-}"; shift 2 ;;
    --container) CONTAINER="${2:-}"; shift 2 ;;
    --note) NOTE="${2:-}"; shift 2 ;;
    --dashboard-uid) DASHBOARD_UID="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

require_arg "event" "$EVENT"
require_arg "service" "$SERVICE"
require_arg "namespace" "$NAMESPACE"
require_arg "source" "$SOURCE"

case "$EVENT" in
  inject_start)
    require_arg "fault_id (inject_start)" "$FAULT_ID"
    ;;
  mitigation_done)
    require_arg "action_id ($EVENT)" "$ACTION_ID"
    ;;
  *)
    echo "ERROR: unsupported event=$EVENT" >&2
    exit 1
    ;;
esac

TOKEN="${GRAFANA_SERVICE_ACCOUNT_TOKEN:-${GRAFANA_TOKEN:-}}"
USER="${GRAFANA_USER:-${GRAFANA_USERNAME:-}}"
PASSWORD="${GRAFANA_PASSWORD:-}"

CURL_AUTH_ARGS=()
if [[ -n "$TOKEN" ]]; then
  CURL_AUTH_ARGS=(-H "Authorization: Bearer $TOKEN")
elif [[ -n "$USER" && -n "$PASSWORD" ]]; then
  CURL_AUTH_ARGS=(-u "$USER:$PASSWORD")
else
  echo "ERROR: missing Grafana auth (token or user/password)" >&2
  exit 1
fi

# 注：已移除幂等性检查
# 原因：现在只在执行成功时写入 annotation，同一操作不会重复成功
# - mitigation_done: 删除成功才写入，pod 已不存在，不会重复
# - mitigation_failed: 已不再使用（失败时不写入 annotation）

ANNO_TIME_MS="$(python3 - <<'PY'
import time
print(int(time.time() * 1000))
PY
)"

PAYLOAD="$(python3 - "$DASHBOARD_UID" "$ANNO_TIME_MS" "$EVENT" "$FAULT_ID" "$INCIDENT_ID" "$ACTION_ID" "$SERVICE" "$NAMESPACE" "$SOURCE" "$DEPLOYMENT" "$POD" "$CONTAINER" "$NOTE" <<'PY'
import json,sys
(
  dashboard_uid,time_ms,event,fault_id,incident_id,action_id,
  service,namespace,source,deployment,pod,container,note
)=sys.argv[1:]

parts=[
  f"event={event}",
  f"service={service}",
  f"namespace={namespace}",
]
if fault_id:
  parts.append(f"fault_id={fault_id}")
if incident_id:
  parts.append(f"incident_id={incident_id}")
if action_id:
  parts.append(f"action_id={action_id}")
if deployment:
  parts.append(f"deployment={deployment}")
if pod:
  parts.append(f"pod={pod}")
if container:
  parts.append(f"container={container}")
if note:
  parts.append(note)

text=" ".join(parts)

tags=[
  f"event:{event}",
  f"service:{service}",
  f"namespace:{namespace}",
  f"source:{source}",
]
if fault_id:
  tags.append(f"fault_id:{fault_id}")
if incident_id:
  tags.append(f"incident_id:{incident_id}")
if action_id:
  tags.append(f"action_id:{action_id}")

payload={
  "dashboardUID": dashboard_uid,
  "time": int(time_ms),
  "text": text,
  "tags": tags,
}
print(json.dumps(payload, ensure_ascii=False))
PY
)"

RESP="$(curl -sS --fail "${CURL_AUTH_ARGS[@]}" \
  -H "Content-Type: application/json" \
  -X POST "${GRAFANA_URL}/api/annotations" \
  -d "$PAYLOAD")"

ANNO_ID="$(python3 - <<'PY' "$RESP"
import json,sys
print(json.loads(sys.argv[1]).get("id",""))
PY
)"

echo "OK: annotation created id=${ANNO_ID:-unknown} event=$EVENT service=$SERVICE namespace=$NAMESPACE"
