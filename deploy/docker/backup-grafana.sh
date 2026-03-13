#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${GRAFANA_URL:-}" ]]; then
  echo "GRAFANA_URL is required (example: http://47.83.217.162:3000)" >&2
  exit 1
fi

if [[ -z "${GRAFANA_USER:-}" ]]; then
  GRAFANA_USER="admin"
fi

if [[ -z "${GRAFANA_PASSWORD:-}" ]]; then
  GRAFANA_PASSWORD="admin"
fi

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="$ROOT_DIR/grafana/backups"
DASHBOARD_DIR="$BACKUP_DIR/dashboards"
ALERT_DIR="$BACKUP_DIR/alert-rules"
DATASOURCE_DIR="$BACKUP_DIR/datasources"

mkdir -p "$DASHBOARD_DIR" "$ALERT_DIR" "$DATASOURCE_DIR"
rm -f "$DASHBOARD_DIR"/*.json "$ALERT_DIR"/*.json "$DATASOURCE_DIR"/*.json
echo "==> Cleared previous backups"

echo "==> Backing up dashboards to $DASHBOARD_DIR"

dashboard_uids=$(curl -sS -u "$GRAFANA_USER:$GRAFANA_PASSWORD" \
  "$GRAFANA_URL/api/search?type=dash-db&limit=5000" | \
  jq -r '.[].uid')

for uid in $dashboard_uids; do
  file="$DASHBOARD_DIR/${uid}.json"
  curl -sS -u "$GRAFANA_USER:$GRAFANA_PASSWORD" \
    "$GRAFANA_URL/api/dashboards/uid/$uid" > "$file"
  echo "  - saved dashboard $uid"
done

if [[ -z "$dashboard_uids" ]]; then
  echo "  - no dashboards found"
fi

echo "==> Backing up Grafana-managed alert rules to $ALERT_DIR"
rule_file="$ALERT_DIR/grafana-alert-rules.json"
curl -sS -u "$GRAFANA_USER:$GRAFANA_PASSWORD" \
  "$GRAFANA_URL/api/v1/provisioning/alert-rules" > "$rule_file"
echo "  - saved alert rules"

echo "==> Backing up datasources to $DATASOURCE_DIR"
datasource_file="$DATASOURCE_DIR/datasources.json"
curl -sS -u "$GRAFANA_USER:$GRAFANA_PASSWORD" \
  "$GRAFANA_URL/api/datasources" > "$datasource_file"
echo "  - saved datasources"

echo "Backup complete."
