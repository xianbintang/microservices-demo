# 生成实验报告 skill

生成完整的混沌实验报告，包含实验信息、观察数据、验证结果和改进建议。

## 核心原则

**告警规则必须代码固化** - 所有告警规则必须存储在代码仓库中（`deploy/monitoring/alerting/`），禁止使用临时 `kubectl apply` 命令创建告警规则。报告中的改进建议应明确指向需要修改的代码文件路径（如 `deploy/monitoring/alerting/chaos-testing-alerts.yaml`）。

## 用法

```
/chaos-report [experiment-id]
```

### 参数

- `experiment-id`: 可选，指定实验 ID（默认：生成最近完成实验的报告）

## 输出示例

```
混沌实验报告
============
实验 ID: pod-failure-20240101-100000
报告生成时间: 2024-01-01 10:05:00

实验信息:
- 实验类型: Pod 故障
- 目标服务: frontend
- 故障类型: PodKill
- 实验时长: 2m
- 开始时间: 2024-01-01 10:00:00
- 结束时间: 2024-01-01 10:02:00
- 预期告警: PodNotReady, ServiceUnavailable

观察数据:
Pod 状态:
- 故障前: Running (frontend-7d9f5c6f8d-x2k4p)
- 故障后: Pending → Running → Ready (45s)
- 重建后: Running (frontend-7d9f5c6f8d-p7j9l)

Service 状态:
- 故障前: 3/3 endpoints
- 故障后: 2/3 → 3/3 (20s)

性能指标:
- QPS: 150 → 120 → 145 (3min 内恢复 96.7%)
- 错误率: 0.1% → 3.2% → 0.15%
- P95 延迟: 80ms → 180ms → 85ms

链路数据:
- 错误 span: 142 个
- 超时 span: 23 个
- 平均响应时间: 120ms

告警验证结果:
✅ PodNotReady: 5s 内触发，响应时间优秀
❌ ServiceUnavailable: 未触发
覆盖率: 50% (1/2)

自我恢复验证结果:
✅ Pod 恢复时间: 45s (优秀)
✅ Service 更新时间: 20s (优秀)
✅ 连接重建: 无泄漏 (15s)
✅ 资源恢复: 3min (优秀)
评价: 通过

问题识别:
1. ServiceUnavailable 告警未触发

改进建议:
1. 检查 ServiceUnavailable 告警规则
2. 或调整预期告警列表

Runbook 更新:
- ✅ Pod 故障恢复时间: 45s
- ✅ 错误率 spike: 3.2%
- ✅ 恢复成功率: 100%

附件:
- Grafana 大盘截图: ./reports/pod-failure-20240101-100000/grafana.png
- Tempo 链路: ./reports/pod-failure-20240101-100000/traces.json
- Loki 日志: ./reports/pod-failure-20240101-100000/logs.json

总结:
- 系统弹性: 优秀 ✅
- 告警有效性: 部分 ⚠️
- 自我恢复能力: 优秀 ✅
- 整体评价: 通过 ⚠️
```

## 验收标准

- [ ] 能正确获取实验信息
- [ ] 能整合所有观察数据
- [ ] 能包含告警验证结果
- [ ] 能包含自我恢复验证结果
- [ ] 能生成可读的完整报告
- [ ] 能提供改进建议
- [ ] 能更新 Runbook
