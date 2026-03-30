#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 从远程 Grafana 实例备份全部配置到本地 JSON 文件
# 备份范围：Dashboards / Alert Rules / Datasources / Contact Points /
#           Notification Policies / Folders
#
# 用法（三选一，优先级从高到低）：
#   1) 直接运行（自动读取项目根目录 .env）：
#        ./backup-grafana.sh
#   2) 通过 Makefile：
#        make backup-grafana
#   3) 手动指定环境变量：
#        GRAFANA_URL=http://47.83.217.162:3000 ./backup-grafana.sh
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$ROOT_DIR/../.." && pwd)"

# 自动加载项目根目录的 .env（仅填充未设置的变量，不覆盖已有环境变量）
ENV_FILE="$PROJECT_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
  while IFS='=' read -r key value; do
    # 跳过空行和注释
    [[ -z "$key" || "$key" =~ ^[[:space:]]*# ]] && continue
    key=$(echo "$key" | xargs)
    value=$(echo "$value" | xargs)
    # 仅在环境变量未设置时才赋值
    if [[ -z "${!key:-}" ]]; then
      export "$key=$value"
    fi
  done < "$ENV_FILE"
fi

if [[ -z "${GRAFANA_URL:-}" ]]; then
  echo "[ERROR] GRAFANA_URL 未设置且 .env 中也未找到" >&2
  echo "  请在 $ENV_FILE 中配置 GRAFANA_URL 或通过环境变量传入" >&2
  exit 1
fi

GRAFANA_USER="${GRAFANA_USER:-admin}"
GRAFANA_PASSWORD="${GRAFANA_PASSWORD:-admin}"
AUTH="$GRAFANA_USER:$GRAFANA_PASSWORD"

echo "==> Grafana 备份开始"
echo "    目标: $GRAFANA_URL"
echo "    用户: $GRAFANA_USER"
echo ""

BACKUP_DIR="$ROOT_DIR/grafana/backups"
DASHBOARD_DIR="$BACKUP_DIR/dashboards"
ALERT_DIR="$BACKUP_DIR/alert-rules"
DATASOURCE_DIR="$BACKUP_DIR/datasources"
CONTACT_DIR="$BACKUP_DIR/contact-points"
FOLDER_DIR="$BACKUP_DIR/folders"

# 辅助函数：带错误处理的 curl 封装
grafana_get() {
  local endpoint="$1"
  local resp
  resp=$(curl -sS -w "\n%{http_code}" -u "$AUTH" "$GRAFANA_URL$endpoint" 2>&1) || {
    echo "  [ERROR] 请求 $endpoint 失败: $resp" >&2
    return 1
  }
  local http_code
  http_code=$(echo "$resp" | tail -1)
  local body
  body=$(echo "$resp" | sed '$d')
  if [[ "$http_code" -lt 200 || "$http_code" -ge 300 ]]; then
    echo "  [ERROR] $endpoint 返回 HTTP $http_code: $body" >&2
    return 1
  fi
  echo "$body"
}

mkdir -p "$DASHBOARD_DIR" "$ALERT_DIR" "$DATASOURCE_DIR" "$CONTACT_DIR" "$FOLDER_DIR"
rm -f "$DASHBOARD_DIR"/*.json "$ALERT_DIR"/*.json "$DATASOURCE_DIR"/*.json \
      "$CONTACT_DIR"/*.json "$FOLDER_DIR"/*.json \
      "$BACKUP_DIR"/notification-policies.json
echo "==> Cleared previous backups"

# --- Folders ---
echo "==> Backing up folders to $FOLDER_DIR"
grafana_get "/api/folders?limit=1000" | python3 -m json.tool > "$FOLDER_DIR/folders.json"
echo "  - saved folders"

# --- Dashboards ---
echo "==> Backing up dashboards to $DASHBOARD_DIR"
dashboard_uids=$(grafana_get "/api/search?type=dash-db&limit=5000" | jq -r '.[].uid')

for uid in $dashboard_uids; do
  file="$DASHBOARD_DIR/${uid}.json"
  grafana_get "/api/dashboards/uid/$uid" | python3 -m json.tool > "$file"
  echo "  - saved dashboard $uid"
done

if [[ -z "$dashboard_uids" ]]; then
  echo "  - no dashboards found"
fi

# --- Alert Rules ---
echo "==> Backing up Grafana-managed alert rules to $ALERT_DIR"
grafana_get "/api/v1/provisioning/alert-rules" | python3 -m json.tool > "$ALERT_DIR/grafana-alert-rules.json"
echo "  - saved alert rules"

# --- Datasources ---
echo "==> Backing up datasources to $DATASOURCE_DIR"
grafana_get "/api/datasources" | python3 -m json.tool > "$DATASOURCE_DIR/datasources.json"
echo "  - saved datasources"

# --- Contact Points ---
echo "==> Backing up contact points to $CONTACT_DIR"
grafana_get "/api/v1/provisioning/contact-points" | python3 -m json.tool > "$CONTACT_DIR/contact-points.json"
echo "  - saved contact points"

# --- Notification Policies ---
echo "==> Backing up notification policies"
grafana_get "/api/v1/provisioning/policies" | python3 -m json.tool > "$BACKUP_DIR/notification-policies.json"
echo "  - saved notification policies"

echo ""
echo "==> Backup complete. Files saved to: $BACKUP_DIR"
echo "    dashboards/          - $(ls "$DASHBOARD_DIR"/*.json 2>/dev/null | wc -l | tr -d ' ') files"
echo "    alert-rules/         - $(ls "$ALERT_DIR"/*.json 2>/dev/null | wc -l | tr -d ' ') files"
echo "    datasources/         - $(ls "$DATASOURCE_DIR"/*.json 2>/dev/null | wc -l | tr -d ' ') files"
echo "    contact-points/      - $(ls "$CONTACT_DIR"/*.json 2>/dev/null | wc -l | tr -d ' ') files"
echo "    folders/             - $(ls "$FOLDER_DIR"/*.json 2>/dev/null | wc -l | tr -d ' ') files"
echo "    notification-policies.json"
