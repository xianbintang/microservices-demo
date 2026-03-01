#!/bin/bash
# 告警覆盖度检查脚本
# 用途：检查当前告警规则是否覆盖关键场景

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 默认值
NAMESPACE="${1:-online-boutique}"
CRITICAL_ALERT_SCENARIOS_FILE="${2:-docs/chaos/critical-alert-scenarios.md}"
OUTPUT_DIR="${3:-.}"

# 打印带颜色的消息
print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_header() {
    echo ""
    echo "=================================="
    echo "$1"
    echo "=================================="
}

# 从告警场景清单中提取必需告警
extract_critical_alerts() {
    grep -E '^\|\s+\w+\s+\|\s+\w+\s+\|\s+是\s+\|' "$CRITICAL_ALERT_SCENARIOS_FILE" | \
        awk -F'|' '{gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); print $2}' | \
        sort -u
}

# 查询 Prometheus 告警规则
query_prometheus_rules() {
    kubectl get prometheusrules -A -o json 2>/dev/null | \
        jq -r '.items[].spec.groups[].rules[] | select(.alert != null) | .alert' | \
        sort -u
}

# 查询 AlertManager 告警配置
query_alertmanager_rules() {
    # 获取 AlertManager secret 名称
    ALERTMANAGER_SECRET=$(kubectl get secret -n monitoring -l app.kubernetes.io/name=alertmanager -o json 2>/dev/null | \
        jq -r '.items[0].metadata.name')

    if [ -z "$ALERTMANAGER_SECRET" ]; then
        echo ""
    else
        kubectl get secret "$ALERTMANAGER_SECRET" -n monitoring -o json 2>/dev/null | \
            jq -r '.data["alertmanager.yaml"]' | \
            base64 -d | \
            grep -A1 'alert:' | grep 'name:' | awk -F'"' '{print $2}' | \
            sort -u
    fi
}

# 获取所有配置的告警
get_configured_alerts() {
    PROMETHEUS_ALERTS=$(query_prometheus_rules)
    ALERTMANAGER_ALERTS=$(query_alertmanager_rules)

    echo "$PROMETHEUS_ALERTS"
    echo "$ALERTMANAGER_ALERTS" | grep -v '^$'
}

# 主函数
main() {
    print_header "告警覆盖度检查"
    echo "检查时间: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "目标命名空间: $NAMESPACE"

    # 提取必需告警
    print_header "提取关键告警场景"
    CRITICAL_ALERTS=($(extract_critical_alerts))
    TOTAL_SCENARIOS=${#CRITICAL_ALERTS[@]}

    echo "关键场景总数: $TOTAL_SCENARIOS"

    if [ $TOTAL_SCENARIOS -eq 0 ]; then
        print_error "无法提取关键告警场景，请检查文件路径: $CRITICAL_ALERT_SCENARIOS_FILE"
        exit 1
    fi

    echo ""
    echo "必需告警列表:"
    for alert in "${CRITICAL_ALERTS[@]}"; do
        echo "  - $alert"
    done

    # 获取已配置的告警
    print_header "查询已配置的告警规则"
    CONFIGURED_ALERTS=($(get_configured_alerts | sort -u))

    if [ ${#CONFIGURED_ALERTS[@]} -eq 0 ]; then
        print_warning "未找到任何配置的告警规则"
    else
        echo "已配置告警总数: ${#CONFIGURED_ALERTS[@]}"
    fi

    # 检查覆盖度
    print_header "告警覆盖度检查"

    COVERED_COUNT=0
    MISSING_ALERTS=()

    for alert in "${CRITICAL_ALERTS[@]}"; do
        if printf '%s\n' "${CONFIGURED_ALERTS[@]}" | grep -q "^${alert}$"; then
            print_success "$alert"
            ((COVERED_COUNT++))
        else
            print_error "$alert (缺失)"
            MISSING_ALERTS+=("$alert")
        fi
    done

    # 计算覆盖率
    COVERAGE=$((COVERED_COUNT * 100 / TOTAL_SCENARIOS))

    print_header "覆盖度统计"
    echo "已覆盖告警: $COVERED_COUNT/$TOTAL_SCENARIOS"
    echo "告警覆盖率: ${COVERAGE}%"

    # 评估结果
    print_header "评估结果"

    if [ $COVERAGE -ge 80 ] && [ ${#MISSING_ALERTS[@]} -eq 0 ]; then
        echo -e "${GREEN}覆盖率: ${COVERAGE}% ✅${NC}"
        echo -e "${GREEN}关键缺失: 0 个 ✅${NC}"
        echo ""
        echo "整体评价: 通过 ✅"
        echo ""
        echo "建议: 可以执行混沌实验"
        exit 0
    elif [ $COVERAGE -lt 80 ]; then
        echo -e "${RED}覆盖率: ${COVERAGE}% ❌${NC}"
        echo -e "${RED}关键缺失: ${#MISSING_ALERTS[@]} 个 ❌${NC}"
        echo ""
        echo "整体评价: 不通过 ❌"
        echo ""
        echo "建议: 补充缺失的告警规则后再执行混沌实验"
        exit 1
    else
        echo -e "${YELLOW}覆盖率: ${COVERAGE}% ⚠️${NC}"
        echo -e "${YELLOW}关键缺失: ${#MISSING_ALERTS[@]} 个 ⚠️${NC}"
        echo ""
        echo "整体评价: 部分 ⚠️"
        echo ""
        echo "建议: 补充关键缺失的告警规则后再执行关键资源实验"
        exit 1
    fi
}

# 执行主函数
main