#!/bin/bash
# 测试 Grafana 连接

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/auth.sh"

curl -s "$GRAFANA_URL/api/health" \
  -H "Authorization: Bearer $GRAFANA_TOKEN" | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print(f\"✅ Grafana {d.get('version','unknown')} OK\")"
