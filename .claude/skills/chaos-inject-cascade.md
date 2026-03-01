# 级联故障注入 skill

触发级联故障注入实验，同时注入多个故障。

## 核心原则

**告警规则必须代码固化** - 所有告警规则必须存储在代码仓库中（`deploy/monitoring/alerting/`），禁止使用临时 `kubectl apply` 命令创建告警规则。

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
