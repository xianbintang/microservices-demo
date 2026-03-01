# 资源耗尽注入 skill

触发资源耗尽注入实验，对目标 Pod 应用 CPU 或内存压力。

## 核心原则

**告警规则必须代码固化** - 所有告警规则必须存储在代码仓库中（`deploy/monitoring/alerting/`），禁止使用临时 `kubectl apply` 命令创建告警规则。

## 用法

```
/chaos-inject-resource [service] [type] [value] [duration]
```

### 参数

- `service`: 目标服务名称（如 `checkoutservice`）
- `type`: 资源类型（cpu 或 memory）
- `value`: 压力值（如 90 表示 90%）
- `duration`: 可选，实验时长（默认：5m），格式：数字+s/m/h

## 预期告警

- HighCPUUsage (Warning)
- HighMemoryUsage (Warning)
- PodOOMKilled (Critical)
- CPUThrottlingHigh (Warning)
