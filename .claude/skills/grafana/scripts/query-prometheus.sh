#!/bin/bash
# 查询 Prometheus 指标

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/auth.sh"

# 解析参数
EXPR=""
DATASOURCE_UID=""
START_TIME="now-1h"
END_TIME="now"
STEP="60s"

while [ $# -gt 0 ]; do
  case "$1" in
    --datasource=*) DATASOURCE_UID="${1#*=}" ;;
    --start=*) START_TIME="${1#*=}" ;;
    --end=*) END_TIME="${1#*=}" ;;
    --step=*) STEP="${1#*=}" ;;
    *) [ -z "$EXPR" ] && EXPR="$1" ;;
  esac
  shift
done

# 自动选择 Prometheus 数据源
if [ -z "$DATASOURCE_UID" ]; then
  DATASOURCE_UID=$(curl -s "$GRAFANA_URL/api/datasources" \
    -H "Authorization: Bearer $GRAFANA_TOKEN" | \
    python3 -c "import json,sys; ds=[x for x in json.load(sys.stdin) if 'prometheus' in x.get('type','')]; print(ds[0]['uid'] if ds else '')")
fi

# 转换时间格式
START_EPOCH=$(date +%s)
END_EPOCH=$(date +%s)

# 调用 Prometheus API
curl -s "$GRAFANA_URL/api/datasources/proxy/uid/$DATASOURCE_UID/api/v1/query_range" \
  -H "Authorization: Bearer $GRAFANA_TOKEN" \
  -G \
  --data-urlencode "query=$EXPR" \
  --data-urlencode "start=$((START_EPOCH - 3600))" \
  --data-urlencode "end=$END_EPOCH" \
  --data-urlencode "step=$STEP" | \
  python3 -c "import json,sys; result=json.load(sys.stdin); print(json.dumps(result, indent=2))"
