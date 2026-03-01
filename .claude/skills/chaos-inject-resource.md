---
description: 触发资源耗尽注入实验，对目标 Pod 应用 CPU 或内存压力
---

# 资源耗尽注入

## 用法

```
/chaos-inject-resource [service] [type] [value] [duration]
```

## 参数

- `service`: 目标服务名称（如 `checkoutservice`）
- `type`: 资源类型（cpu 或 memory）
- `value`: 压力值（如 90 表示 90%）
- `duration`: 可选，实验时长（默认：5m），格式：数字+s/m/h

## 预期告警

- HighCPUUsage (Warning)
- HighMemoryUsage (Warning)
- PodOOMKilled (Critical)
- CPUThrottlingHigh (Warning)

## 前置检查

- 检查告警规则是否包含资源告警（如 PodOOMKilled）
- 如果缺失，建议补充后再执行