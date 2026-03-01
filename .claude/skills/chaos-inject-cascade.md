---
description: 触发级联故障注入实验，同时注入多个故障
---

# 级联故障注入

## 用法

```
/chaos-inject-cascade [config]
```

## 参数

- `config`: 级联故障配置名称（如 `default`, `heavy`），或直接指定 JSON 配置

## 内置配置

### default
- adservice: PodKill (2m)
- recommendationservice: NetworkDelay 500ms (3m)
- checkoutservice: MemoryStress 80% (4m)

### heavy
- adservice: PodKill (3m)
- recommendationservice: NetworkDelay 1s (5m)
- checkoutservice: MemoryStress 90% (5m)
- frontend: NetworkLoss 10% (5m)

## 预期告警

- ServiceUnavailable (Critical)
- CascadeFailureDetected (Warning)
- SystemDegraded (Warning)
- CircuitBreakerCascade (Warning)