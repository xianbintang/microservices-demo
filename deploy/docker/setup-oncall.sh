#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# setup-oncall.sh — 自动化 Grafana OnCall 插件初始化
#
# 本脚本在远端服务器上执行，完成以下工作：
#   1. 等待 Grafana / OnCall engine 就绪
#   2. 安装并启用 OnCall 插件
#   3. 创建 Grafana Service Account + Token (Admin)
#   4. 调用 OnCall self-hosted install API，完成 Organization 注册
#   5. 将 OnCall plugin auth token 写入 Grafana plugin 配置
#   6. 验证双向连接正常
#
# 幂等性：脚本可多次运行；已存在的资源会被跳过或复用。
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── 配置 ─────────────────────────────────────────────────────────────
GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
GRAFANA_USER="${GRAFANA_USER:-admin}"
GRAFANA_PASSWORD="${GRAFANA_PASSWORD:-admin}"
ONCALL_URL="${ONCALL_URL:-http://localhost:8080}"
ONCALL_INTERNAL_URL="${ONCALL_INTERNAL_URL:-http://oncall:8080}"
GRAFANA_INTERNAL_URL="${GRAFANA_INTERNAL_URL:-http://grafana:3000}"

SA_NAME="oncall-engine"
SA_TOKEN_NAME="oncall-engine-token"

MAX_WAIT=120
INTERVAL=3

# ── 通用函数 ─────────────────────────────────────────────────────────
log()  { printf "\033[1;32m[oncall-setup]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[oncall-setup]\033[0m WARN: %s\n" "$*"; }
err()  { printf "\033[1;31m[oncall-setup]\033[0m ERROR: %s\n" "$*" >&2; }
die()  { err "$@"; exit 1; }

grafana_api() {
  local method="$1" path="$2"; shift 2
  curl -sS -u "${GRAFANA_USER}:${GRAFANA_PASSWORD}" \
    -X "$method" \
    -H "Content-Type: application/json" \
    "${GRAFANA_URL}${path}" "$@"
}

# ── 步骤 1：等待 Grafana 就绪 ───────────────────────────────────────
wait_for_service() {
  local name="$1" url="$2" elapsed=0
  log "等待 ${name} 就绪 (${url})..."
  while true; do
    if curl -sS --fail --max-time 3 "${url}" >/dev/null 2>&1; then
      log "${name} 已就绪 (${elapsed}s)"
      return 0
    fi
    elapsed=$((elapsed + INTERVAL))
    if [[ $elapsed -ge $MAX_WAIT ]]; then
      die "${name} 在 ${MAX_WAIT}s 内未就绪，请检查容器日志"
    fi
    sleep "$INTERVAL"
  done
}

wait_for_service "Grafana" "${GRAFANA_URL}/api/health"
wait_for_service "OnCall"  "${ONCALL_URL}/api/internal/v1/health/"

# ── 步骤 2：安装并启用 OnCall 插件 ──────────────────────────────────
log "检查 OnCall 插件状态..."
PLUGIN_INFO="$(grafana_api GET /api/plugins/grafana-oncall-app/settings 2>/dev/null || echo '{}')"
PLUGIN_ENABLED="$(echo "$PLUGIN_INFO" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("enabled",""))' 2>/dev/null || echo "")"

if [[ "$PLUGIN_ENABLED" != "True" ]]; then
  log "启用 OnCall 插件..."
  grafana_api POST /api/plugins/grafana-oncall-app/settings \
    -d '{"enabled":true,"pinned":true}' >/dev/null
  log "OnCall 插件已启用"
else
  log "OnCall 插件已处于启用状态，跳过"
fi

# ── 步骤 3：创建 Grafana Service Account + Token ────────────────────
log "准备 Grafana Service Account..."

EXISTING_SA="$(grafana_api GET /api/serviceaccounts/search 2>/dev/null \
  | python3 -c "
import json,sys
data = json.load(sys.stdin)
sas = data.get('serviceAccounts', [])
for sa in sas:
    if sa.get('name') == '${SA_NAME}':
        print(sa['id'])
        break
" 2>/dev/null || echo "")"

if [[ -n "$EXISTING_SA" ]]; then
  SA_ID="$EXISTING_SA"
  log "复用已有 Service Account: id=${SA_ID}"
else
  SA_ID="$(grafana_api POST /api/serviceaccounts \
    -d "{\"name\":\"${SA_NAME}\",\"role\":\"Admin\"}" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
  log "已创建 Service Account: id=${SA_ID}"
fi

EXISTING_TOKEN="$(grafana_api GET "/api/serviceaccounts/${SA_ID}/tokens" 2>/dev/null \
  | python3 -c "
import json,sys
tokens = json.load(sys.stdin)
for t in tokens:
    if t.get('name') == '${SA_TOKEN_NAME}':
        print('exists')
        break
" 2>/dev/null || echo "")"

if [[ "$EXISTING_TOKEN" == "exists" ]]; then
  warn "Token '${SA_TOKEN_NAME}' 已存在但无法读取明文值；将删除后重建"
  grafana_api GET "/api/serviceaccounts/${SA_ID}/tokens" 2>/dev/null \
    | python3 -c "
import json,sys
tokens = json.load(sys.stdin)
for t in tokens:
    if t.get('name') == '${SA_TOKEN_NAME}':
        print(t['id'])
        break
" 2>/dev/null | while read -r tid; do
    grafana_api DELETE "/api/serviceaccounts/${SA_ID}/tokens/${tid}" >/dev/null 2>&1 || true
  done
fi

GRAFANA_TOKEN="$(grafana_api POST "/api/serviceaccounts/${SA_ID}/tokens" \
  -d "{\"name\":\"${SA_TOKEN_NAME}\"}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["key"])')"
log "已创建 Grafana API Token: ${GRAFANA_TOKEN:0:12}..."

# ── 步骤 4：调用 OnCall self-hosted install API ─────────────────────
log "执行 OnCall self-hosted install..."
INSTALL_RESP="$(curl -sS -X POST \
  "${ONCALL_URL}/api/internal/v1/plugin/self-hosted/install" \
  -H "Content-Type: application/json" \
  -H "X-Instance-Context: {\"stack_id\":5,\"org_id\":100,\"grafana_token\":\"${GRAFANA_TOKEN}\"}" \
  2>&1)" || true

ONCALL_TOKEN="$(echo "$INSTALL_RESP" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    token = d.get("onCallToken") or d.get("token") or ""
    error = d.get("error")
    if token:
        print(token)
    elif error and str(error) != "None":
        print("ERROR:" + str(error))
    else:
        print("")
except Exception as e:
    print("PARSE_ERROR:" + str(e))
' 2>/dev/null)" || ONCALL_TOKEN=""

if [[ "$ONCALL_TOKEN" == ERROR:* || "$ONCALL_TOKEN" == PARSE_ERROR:* ]]; then
  warn "Install API 返回错误: ${ONCALL_TOKEN}"
  warn "原始响应: ${INSTALL_RESP}"
  die "OnCall install 失败，请检查 oncall 容器日志"
fi

if [[ -z "$ONCALL_TOKEN" ]]; then
  die "未能获取 OnCall plugin token，请查看 oncall 容器日志"
fi
log "已获取 OnCall plugin token: ${ONCALL_TOKEN:0:16}..."

# ── 步骤 5：将 token 对写入 Grafana plugin 配置 ─────────────────────
log "配置 Grafana OnCall 插件..."
grafana_api POST /api/plugins/grafana-oncall-app/settings \
  -d "{
    \"enabled\": true,
    \"pinned\": true,
    \"jsonData\": {
      \"onCallApiUrl\": \"${ONCALL_INTERNAL_URL}\",
      \"grafanaUrl\": \"${GRAFANA_INTERNAL_URL}\",
      \"stackId\": 5,
      \"orgId\": 100
    },
    \"secureJsonData\": {
      \"grafanaToken\": \"${GRAFANA_TOKEN}\",
      \"onCallApiToken\": \"${ONCALL_TOKEN}\"
    }
  }" >/dev/null
log "Grafana OnCall 插件配置完成"

# ── 步骤 6：验证连接 ────────────────────────────────────────────────
log "验证 OnCall 插件连接..."
sleep 2

STATUS="$(grafana_api GET /api/plugins/grafana-oncall-app/resources/plugin/v2/status 2>/dev/null || echo '{}')"
CONNECTED="$(echo "$STATUS" | python3 -c '
import json,sys
d = json.load(sys.stdin)
g = d.get("connection_to_grafana", {})
print("true" if g.get("connected") else "false")
' 2>/dev/null || echo "false")"

if [[ "$CONNECTED" == "true" ]]; then
  VERSION="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version","unknown"))' 2>/dev/null || echo "unknown")"
  log "✅ OnCall 插件连接成功！"
  log "   版本: ${VERSION}"
  log "   OnCall API: ${ONCALL_INTERNAL_URL}"
  log "   Grafana API: ${GRAFANA_INTERNAL_URL}"
else
  warn "插件连接验证失败，请手动检查"
  warn "Status 响应: ${STATUS}"
  exit 1
fi
