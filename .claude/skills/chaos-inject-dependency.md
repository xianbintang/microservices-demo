---
description: 触发服务依赖故障注入实验，模拟依赖服务不可用
---

# 依赖故障注入

## 用法

```
/chaos-inject-dependency [service] [dependency] [duration]
```

## 参数

- `service`: 上游服务名称（如 `frontend`）
- `dependency`: 依赖服务名称（如 `adservice`）
- `duration`: 可选，实验时长（默认：3m），格式：数字+s/m/h

## 预期告警

- ServiceUnavailable (Critical)
- DependencyErrorRateHigh (Warning)
- CircuitBreakerOpen (Warning)