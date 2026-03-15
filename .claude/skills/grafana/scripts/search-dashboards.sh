#!/bin/bash
# 搜索 Grafana Dashboard

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/auth.sh"

QUERY="${1}"
LIMIT="${2:-50}"

curl -s "$GRAFANA_URL/api/search" \
  -H "Authorization: Bearer $GRAFANA_TOKEN" \
  -G \
  --data-urlencode "query=$QUERY" \
  --data-urlencode "limit=$LIMIT" | \
  python3 -c "import json,sys; results=json.load(sys.stdin); print('\n'.join([f\"{r['title']} (uid={r['uid']}, url={r.get('url','')})\" for r in results]))"
