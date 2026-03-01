# 告警覆盖度检查报告模板

## 报告结构

```markdown
# 告警覆盖度检查报告

## 检查时间
{{TIMESTAMP}}

## 目标命名空间
{{NAMESPACE}}

## 覆盖度统计
- 关键场景总数: {{TOTAL_SCENARIOS}}
- 已覆盖场景数: {{COVERED_SCENARIOS}}
- 缺失场景数: {{MISSING_SCENARIOS}}
- 告警覆盖率: {{COVERAGE_PERCENTAGE}}

## 已覆盖的告警 ✅
{{COVERED_ALERTS_TABLE}}

## 缺失的告警 ❌
{{MISSING_ALERTS_TABLE}}

## 评估结果
- 覆盖率: {{COVERAGE_PERCENTAGE}} {{STATUS_ICON}}
- 关键缺失: {{CRITICAL_MISSING_COUNT}} 个 {{STATUS_ICON}}

## 操作建议
{{RECOMMENDATIONS}}

## 阻塞状态
{{BLOCK_STATUS}}

## 附件
- 告警规则清单: ./alerts-{{TIMESTAMP}}.json
- 覆盖度详情: ./coverage-details-{{TIMESTAMP}}.json
```

## 模板变量

| 变量 | 说明 | 格式 |
|------|------|------|
| TIMESTAMP | 检查时间 | YYYY-MM-DD HH:MM:SS |
| NAMESPACE | 目标命名空间 | string |
| TOTAL_SCENARIOS | 关键场景总数 | number |
| COVERED_SCENARIOS | 已覆盖场景数 | number |
| MISSING_SCENARIOS | 缺失场景数 | number |
| COVERAGE_PERCENTAGE | 覆盖率百分比 | number% |
| STATUS_ICON | 状态图标 | ✅ / ⚠️ / ❌ |
| COVERED_ALERTS_TABLE | 已覆盖告警表格 | Markdown 表格 |
| MISSING_ALERTS_TABLE | 缺失告警表格 | Markdown 表格 |
| CRITICAL_MISSING_COUNT | 关键缺失数量 | number |
| RECOMMENDATIONS | 操作建议 | Markdown 列表 |
| BLOCK_STATUS | 阻塞状态 | 允许/阻塞/部分允许 |

## 状态图标

| 状态 | 图标 | 说明 |
|------|------|------|
| 允许 | ✅ | 可以执行混沌实验 |
| 部分 | ⚠️ | 可以执行部分实验 |
| 阻塞 | ❌ | 需补充告警规则 |

## 表格格式

### 已覆盖告警表格

```markdown
| 场景名称 | 告警名称 | 严重级别 | 状态 |
|---------|---------|---------|------|
| Pod 崩溃/终止 | PodDown | Critical | ✅ |
| Pod 就绪状态 | PodNotReady | Critical | ✅ |
```

### 缺失告警表格

```markdown
| 场景名称 | 建议告警名称 | 严重级别 | 重要性 |
|---------|-------------|---------|--------|
| Pod OOM | PodOOMKilled | Critical | **关键** |
| 熔断器打开 | CircuitBreakerOpen | Warning | 重要 |
```