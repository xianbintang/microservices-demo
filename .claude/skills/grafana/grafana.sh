#!/bin/bash
# Grafana Skill 主入口脚本

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 解析 action
ACTION="${1:-help}"
shift || true

# 根据 action 分发到对应脚本
case "$ACTION" in
  test-connection)
    exec "$SCRIPT_DIR/scripts/test-connection.sh" "$@"
    ;;
  list-datasources)
    exec "$SCRIPT_DIR/scripts/list-datasources.sh" "$@"
    ;;
  query-prometheus)
    exec "$SCRIPT_DIR/scripts/query-prometheus.sh" "$@"
    ;;
  search-dashboards)
    exec "$SCRIPT_DIR/scripts/search-dashboards.sh" "$@"
    ;;
  help|--help|-h)
    echo "Grafana Skill - 操作 Grafana 的统一接口"
    echo ""
    echo "用法: /grafana <action> [args...]"
    echo ""
    echo "可用 actions:"
    echo "  test-connection      测试 Grafana 连接"
    echo "  list-datasources     列出所有数据源"
    echo "  query-prometheus     查询 Prometheus 指标"
    echo "  search-dashboards    搜索 Dashboard"
    echo ""
    echo "运行 /grafana <action> --help 查看详细用法"
    ;;
  *)
    echo "❌ 未知 action: $ACTION"
    echo "运行 /grafana help 查看可用命令"
    exit 1
    ;;
esac
