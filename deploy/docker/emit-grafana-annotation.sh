#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  emit-grafana-annotation.sh \
    --event <inject_start|mitigation_done|mitigation_failed> \
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
    [--idempotency-key <key>] \
    [--dashboard-uid <uid>]

Auth:
  - Preferred: GRAFANA_SERVICE_ACCOUNT_TOKEN or GRAFANA_TOKEN
  - Fallback:  GRAFANA_USER/GRAFANA_PASSWORD or GRAFANA_USERNAME/GRAFANA_PASSWORD

Env:
  - GRAFANA_URL (required)
  - GRAFANA_DASHBOARD_UID (optional, default: fffrl21oam2gwa)

Notes:
  - best-effort caller pattern: call this script and ignore failure if needed.
  - mitigation events support idempotency_key to avoid duplicate final annotations.
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
IDEMPOTENCY_KEY=""
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
    --idempotency-key) IDEMPOTENCY_KEY="${2:-}"; shift 2 ;;
    --dashboard-uid) DASHBOARD_UID="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

require_arg "GRAFANA_URL" "${GRAFANA_URL:-}"
require_arg "event" "$EVENT"
require_arg "service" "$SERVICE"
require_arg "namespace" "$NAMESPACE"
require_arg "source" "$SOURCE"

case "$EVENT" in
  inject_start)
    require_arg "fault_id (inject_start)" "$FAULT_ID"
    ;;
  mitigation_done|mitigation_failed)
    require_arg "incident_id ($EVENT)" "$INCIDENT_ID"
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

if [[ -z "$IDEMPOTENCY_KEY" && ( "$EVENT" == "mitigation_done" || "$EVENT" == "mitigation_failed" ) ]]; then
  IDEMPOTENCY_KEY="mitigation__${INCIDENT_ID}__${ACTION_ID}__${SERVICE}__${NAMESPACE}"
fi

SAFE_IDEMPOTENCY_KEY=""
if [[ -n "$IDEMPOTENCY_KEY" ]]; then
  SAFE_IDEMPOTENCY_KEY="$(python3 - "$IDEMPOTENCY_KEY" <<'PY'
import re,sys
print(re.sub(r'[^A-Za-z0-9._-]', '_', sys.argv[1]))
PY
)"

  TAG_FILTER="idempotency_key:${SAFE_IDEMPOTENCY_KEY}"
  ENCODED_TAG_FILTER="$(urlencode "$TAG_FILTER")"
  EXISTING_JSON="$(curl -sS --fail "${CURL_AUTH_ARGS[@]}" \
    "${GRAFANA_URL}/api/annotations?dashboardUID=${DASHBOARD_UID}&limit=50&tags=${ENCODED_TAG_FILTER}")"
  EXISTING_COUNT="$(python3 - <<'PY' "$EXISTING_JSON"
import json,sys
obj=json.loads(sys.argv[1])
print(len(obj if isinstance(obj, list) else []))
PY
)"
  if [[ "$EXISTING_COUNT" != "0" ]]; then
    echo "SKIP: annotation already exists by idempotency_key=$SAFE_IDEMPOTENCY_KEY"
    exit 0
  fi
fi

ANNO_TIME_MS="$(python3 - <<'PY'
import time
print(int(time.time() * 1000))
PY
)"

PAYLOAD="$(python3 - "$DASHBOARD_UID" "$ANNO_TIME_MS" "$EVENT" "$FAULT_ID" "$INCIDENT_ID" "$ACTION_ID" "$SERVICE" "$NAMESPACE" "$SOURCE" "$DEPLOYMENT" "$POD" "$CONTAINER" "$NOTE" "$SAFE_IDEMPOTENCY_KEY" <<'PY'
import json,sys
(
  dashboard_uid,time_ms,event,fault_id,incident_id,action_id,
  service,namespace,source,deployment,pod,container,note,idempotency_key
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
if idempotency_key:
  tags.append(f"idempotency_key:{idempotency_key}")

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
