#!/bin/bash
# 列出 Grafana 数据源

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/auth.sh"

TYPE_FILTER="${1#--type=}"

if [ -n "$TYPE_FILTER" ]; then
  curl -s "$GRAFANA_URL/api/datasources" \
    -H "Authorization: Bearer $GRAFANA_TOKEN" | \
    python3 -c "import json,sys; ds=[x for x in json.load(sys.stdin) if x.get('type','').find('$TYPE_FILTER')>=0]; print('\n'.join([f\"{d['name']} (uid={d['uid']}, type={d['type']})\" for d in ds]))"
else
  curl -s "$GRAFANA_URL/api/datasources" \
    -H "Authorization: Bearer $GRAFANA_TOKEN" | \
    python3 -c "import json,sys; ds=json.load(sys.stdin); print('\n'.join([f\"{d['name']} (uid={d['uid']}, type={d['type']})\" for d in ds]))"
fi
