# 混沌实验监控 skill

监控正在运行的混沌实验，显示实时状态和关键指标。

## 用法

```
/chaos-monitor [experiment-id]
```

### 参数

- `experiment-id`: 可选，指定实验 ID（默认：显示所有运行中的实验）

## 输出示例

```
混沌实验监控
============
运行中的实验: 1

实验 1: pod-failure-20240101-100000
-------------------------------------
状态: Running (已运行 45s / 2m)
目标服务: frontend
故障类型: PodKill

实时指标:
Pod 状态: Running (15s 前) → Ready (5s 前)
Service endpoints: 3/3 (已更新)
错误率: 3.2% (基准: 0.1%) ⚠️
P95 延迟: 180ms (基准: 80ms)
QPS: 142 (基准: 150)

告警状态:
✅ PodNotReady: 已触发 (30s 前触发，25s 前恢复)
⏳ ServiceUnavailable: 等待中

Grafana 大盘:
http://localhost:3000/d/chaos-experiments?var-experiment=pod-failure-20240101-100000

下一步:
- 使用 /chaos-validate-alerts 验证告警触发
- 使用 /chaos-validate-self-heal 验证自我恢复
- 使用 /chaos-abort 中止实验
```

## 验收标准

- [ ] 能正确查询运行中的实验
- [ ] 能获取实时关键指标
- [ ] 能显示告警状态
- [ ] 能提供 Grafana 大盘链接
- [ ] 能提供下一步操作指引
