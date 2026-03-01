#!/bin/bash
# 告警验证脚本
# 用途：验证混沌实验期间告警是否正确触发

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 默认值
NAMESPACE="${1:-online-boutique}"
EXPECTED_ALERTS_FILE="${2:-.chaos-expected-alerts.txt}"
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

# 获取混沌工程专用告警
get_chaos_alerts() {
    kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
        wget -q -O- 'http://localhost:9090/api/v1/query?query=ALERTS{chaos_test="true",alertstate="firing"}' 2>/dev/null | \
        jq -r '.data.result[].metric.alertname' 2>/dev/null | sort -u
}

# 获取所有告警
get_all_alerts() {
    kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
        wget -q -O- 'http://localhost:9090/api/v1/query?query=ALERTS{alertstate="firing"}' 2>/dev/null | \
        jq -r '.data.result[].metric.alertname' 2>/dev/null | sort -u
}

# 获取告警详情
get_alert_details() {
    local alert_name="$1"
    kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
        wget -q -O- "http://localhost:9090/api/v1/query?query=ALERTS{alertname=\"${alert_name}\",alertstate=\"firing\"}" 2>/dev/null | \
        jq -r '.data.result[] | "  - \(.metric.alertname): namespace=\(.metric.namespace // "N/A"), pod=\(.metric.pod // "N/A"), severity=\(.metric.severity // "unknown")"' 2>/dev/null
}

# 主函数
main() {
    print_header "告警验证"
    echo "验证时间: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "目标命名空间: $NAMESPACE"

    # 获取实际告警
    print_header "查询实际告警"
    CHAOS_ALERTS=($(get_chaos_alerts))
    ALL_ALERTS=($(get_all_alerts))

    echo "混沌工程专用告警: ${#CHAOS_ALERTS[@]} 个"
    echo "所有活跃告警: ${#ALL_ALERTS[@]} 个"

    # 读取预期告警
    print_header "对比预期告警"
    EXPECTED_ALERTS=()
    if [ -f "$EXPECTED_ALERTS_FILE" ]; then
        while IFS= read -r alert; do
            [ -n "$alert" ] && EXPECTED_ALERTS+=("$alert")
        done < "$EXPECTED_ALERTS_FILE"
        echo "预期告警: ${#EXPECTED_ALERTS[@]} 个"
    else
        print_warning "未找到预期告警文件: $EXPECTED_ALERTS_FILE"
        echo "默认检查混沌工程专用告警"
    fi

    # 验证告警
    print_header "告警验证结果"

    if [ ${#EXPECTED_ALERTS[@]} -eq 0 ]; then
        # 使用混沌工程专用告警
        if [ ${#CHAOS_ALERTS[@]} -gt 0 ]; then
            print_success "混沌工程告警已触发"
            echo ""
            echo "告警详情:"
            for alert in "${CHAOS_ALERTS[@]}"; do
                get_alert_details "$alert"
            done
            echo ""
            echo "验证结论: 通过 ✅"
            exit 0
        else
            print_error "未检测到混沌工程告警"
            echo ""
            echo "可能原因:"
            echo "1. 实验时长过短（< 1 分钟）"
            echo "2. 故障已恢复，告警已清除"
            echo "3. 告警规则 duration 未满足"
            echo ""
            echo "所有活跃告警:"
            for alert in "${ALL_ALERTS[@]}"; do
                get_alert_details "$alert"
            done
            echo ""
            echo "验证结论: 不通过 ❌"
            exit 1
        fi
    else
        # 使用预期告警列表
        MATCHED_COUNT=0
        MISSING_ALERTS=()

        for alert in "${EXPECTED_ALERTS[@]}"; do
            if printf '%s\n' "${ALL_ALERTS[@]}" | grep -q "^${alert}$"; then
                print_success "$alert"
                ((MATCHED_COUNT++))
            else
                print_error "$alert (缺失)"
                MISSING_ALERTS+=("$alert")
            fi
        done

        COVERAGE=$((MATCHED_COUNT * 100 / ${#EXPECTED_ALERTS[@]}))

        print_header "验证统计"
        echo "匹配告警: $MATCHED_COUNT/${#EXPECTED_ALERTS[@]}"
        echo "告警覆盖率: ${COVERAGE}%"

        # 评估结果
        print_header "验证结论"
        if [ $COVERAGE -ge 80 ] && [ ${#MISSING_ALERTS[@]} -eq 0 ]; then
            echo -e "${GREEN}覆盖率: ${COVERAGE}% ✅${NC}"
            echo -e "${GREEN}缺失告警: 0 个 ✅${NC}"
            echo ""
            echo "整体评价: 通过 ✅"
            exit 0
        else
            echo -e "${RED}覆盖率: ${COVERAGE}% ❌${NC}"
            echo -e "${RED}缺失告警: ${#MISSING_ALERTS[@]} 个 ❌${NC}"
            echo ""
            echo "整体评价: 不通过 ❌"
            echo ""
            echo "建议:"
            echo "1. 延长实验时长以满足告警规则 duration"
            echo "2. 检查故障是否已恢复导致告警清除"
            echo "3. 验证告警规则表达式是否正确"
            exit 1
        fi
    fi
}

# 执行主函数
main
