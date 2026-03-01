# 级联故障注入 skill

触发级联故障注入实验，同时注入多个故障。

## 用法

```
/chaos-inject-cascade [config]
```

### 参数

- `config`: 级联故障配置名称（如 `default`, `heavy`），或直接指定 JSON 配置

## 预期告警

- CascadeFailureDetected (Critical)
- ServiceUnavailable (Critical)
- SystemDegraded (Warning)
- CircuitBreakerCascade (Warning)
