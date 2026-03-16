#!/usr/bin/env bash
set -euo pipefail

HOST="${PROM_ALERT_HOST:-}"
CONTAINER="${PROM_ALERT_CONTAINER:-prometheus-alert}"
DB_PATH="${PROM_ALERT_DB_PATH:-/app/db/PrometheusAlertDB.db}"
TEMPLATE_NAME="${PROM_ALERT_TEMPLATE_NAME:-grafana-fs}"

read -r -d '' TEMPLATE <<'EOF' || true
{{$a := index .alerts 0}}{{if eq .state "ok"}}**<font color="green">[已恢复]</font>{{index $a.labels "alertname"}}{{if index $a.labels "service"}}（{{index $a.labels "service"}}）{{else if index $a.labels "service_name"}}（{{index $a.labels "service_name"}}）{{end}}**{{else}}**<font color="red">[告警触发]</font>{{index $a.labels "alertname"}}{{if index $a.labels "service"}}（{{index $a.labels "service"}}）{{else if index $a.labels "service_name"}}（{{index $a.labels "service_name"}}）{{end}}**{{end}}
时间：{{GetCSTtime ""}}
Labels：
• alertname: {{index $a.labels "alertname"}}{{if index $a.labels "grafana_folder"}}
• grafana_folder: {{index $a.labels "grafana_folder"}}{{end}}{{if index $a.labels "service"}}
• service: {{index $a.labels "service"}}{{end}}{{if index $a.labels "service_name"}}
• service_name: {{index $a.labels "service_name"}}{{end}}
来源：[点击查看告警]({{$a.generatorURL}})
静默：[一键静默]({{$a.silenceURL}})
EOF

SQL=$(cat <<EOF
UPDATE prometheus_alert_d_b
SET tpl='${TEMPLATE}'
WHERE tplname='${TEMPLATE_NAME}';

INSERT INTO prometheus_alert_d_b (tpltype, tpluse, tplname, tpl, created, webhook_content_type)
SELECT 'fs', 'Grafana', '${TEMPLATE_NAME}', '${TEMPLATE}', datetime('now'), ''
WHERE NOT EXISTS (
  SELECT 1 FROM prometheus_alert_d_b WHERE tplname='${TEMPLATE_NAME}'
);
EOF
)

VERIFY_SQL="SELECT tpl FROM prometheus_alert_d_b WHERE tplname='${TEMPLATE_NAME}' LIMIT 1;"

run_sql() {
  local sql="$1"
  if [[ -n "$HOST" ]]; then
    ssh "$HOST" "docker exec -i ${CONTAINER} sqlite3 ${DB_PATH}" <<<"$sql"
  else
    docker exec -i "$CONTAINER" sqlite3 "$DB_PATH" <<<"$sql"
  fi
}

run_sql "$SQL" >/dev/null
RESULT="$(run_sql "$VERIFY_SQL")"

if [[ -z "$RESULT" ]]; then
  echo "ERROR: template ${TEMPLATE_NAME} not found after apply" >&2
  exit 1
fi

echo "OK: applied template ${TEMPLATE_NAME} (container=${CONTAINER}${HOST:+, host=${HOST}})"