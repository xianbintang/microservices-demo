#!/bin/bash
# Grafana Skill 完整功能测试脚本

SCRIPT_DIR="/Users/bytedance/workspace/AlarmKeeper/microservices-demo/.claude/skills/grafana"

echo "🧪 Grafana Skill 完整功能测试"
echo "================================"
echo ""

# 测试计数器
PASS=0
FAIL=0
WARN=0

# 测试函数
run_test() {
    local test_num="$1"
    local test_name="$2"
    local command="$3"
    local expected_pattern="$4"

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "测试 $test_num: $test_name"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "命令: $command"
    echo ""

    OUTPUT=$(eval "$command" 2>&1)
    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
        if [ -n "$expected_pattern" ]; then
            if echo "$OUTPUT" | grep -qE "$expected_pattern"; then
                echo "✅ PASS"
                PASS=$((PASS + 1))
                echo "输出预览:"
                echo "$OUTPUT" | head -5
            else
                echo "❌ FAIL - 输出不匹配预期"
                echo "预期匹配: $expected_pattern"
                echo "实际输出:"
                echo "$OUTPUT"
                FAIL=$((FAIL + 1))
            fi
        else
            if [ -z "$OUTPUT" ]; then
                echo "⚠️  WARN - 命令执行成功但无输出"
                WARN=$((WARN + 1))
            else
                echo "✅ PASS"
                PASS=$((PASS + 1))
                echo "输出预览:"
                echo "$OUTPUT" | head -5
            fi
        fi
    else
        echo "❌ FAIL - 退出码: $EXIT_CODE"
        echo "输出:"
        echo "$OUTPUT"
        FAIL=$((FAIL + 1))
    fi
    echo ""
}

# 执行所有测试
run_test "1" "help 功能" \
    "$SCRIPT_DIR/grafana.sh help" \
    "可用 actions"

run_test "2" "test-connection - 连接测试" \
    "$SCRIPT_DIR/grafana.sh test-connection" \
    "Grafana.*OK"

run_test "3" "list-datasources - 列出所有数据源" \
    "$SCRIPT_DIR/grafana.sh list-datasources" \
    "Prometheus"

run_test "4" "list-datasources --type prometheus - 过滤数据源" \
    "$SCRIPT_DIR/grafana.sh list-datasources --type=prometheus" \
    "prometheus"

run_test "5" "search-dashboards - 搜索 Dashboard" \
    "$SCRIPT_DIR/grafana.sh search-dashboards boutique" \
    ""

run_test "6" "query-prometheus 'up' - 简单查询" \
    "$SCRIPT_DIR/grafana.sh query-prometheus 'up'" \
    "status"

run_test "7" "错误处理 - 无效 action" \
    "$SCRIPT_DIR/grafana.sh invalid-action 2>&1" \
    "未知|unknown"

# 测试总结
echo "================================"
echo "📊 测试总结"
echo "================================"
echo "✅ 通过: $PASS"
echo "❌ 失败: $FAIL"
echo "⚠️  警告: $WARN"
echo "总计: $((PASS + FAIL + WARN)) 个测试"
echo ""

if [ $FAIL -eq 0 ]; then
    echo "🎉 所有测试通过！Grafana Skill 功能正常"
    exit 0
else
    echo "⚠️  有 $FAIL 个测试失败，请检查"
    exit 1
fi
