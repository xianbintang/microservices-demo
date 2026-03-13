# Policy: Incident 去重与止损幂等

## 1. 目标

避免同一根因触发多条告警时，虚拟员工重复执行止损动作。

---

## 2. 统一原则

1. **先归并 incident，后执行动作**
2. **动作按 incident 去重，不按 alert 去重**
3. **任何动作必须可幂等**

---

## 3. 数据模型（建议）

### Incident

```json
{
  "incident_id": "inc_20260313_001",
  "incident_key": "online-boutique:redis-cart:2026-03-13T14:10",
  "status": "open",
  "alerts": ["AppCPUThrottling", "AppHighLatency"],
  "suspected_cause": "cpu_overload_injection",
  "severity": "critical"
}
```

### Action Ledger

```json
{
  "idempotency_key": "inc_20260313_001:cpu_overload_injection:rollback_injected_revision",
  "incident_id": "inc_20260313_001",
  "cause_id": "cpu_overload_injection",
  "action_id": "rollback_injected_revision",
  "status": "success",
  "executed_at": "2026-03-13T14:12:03Z",
  "cooldown_until": "2026-03-13T14:22:03Z"
}
```

---

## 4. 执行流程（强约束）

1. 收到告警，计算 `incident_key`
2. 若 incident 已存在则合并，否则创建
3. 完成根因分类（得到 `cause_id`）
4. 选择动作（`action_id`）
5. 检查幂等键是否已执行成功
   - 已成功：`skip`
   - 未成功：继续
6. 检查 cooldown
7. 获取 incident lock（防并发）
8. 执行动作并写入 ledger
9. 释放锁并进入恢复观察

---

## 5. 允许重复执行的例外

仅以下情况允许突破去重：
- 上次动作为 `failed`
- incident 严重性升级（如 warning -> critical）
- 人工明确批准重试

---

## 6. 与 Playbook/Runbook 的关系

- Alert Playbook：负责“如何识别与分流”
- Cause Runbook：负责“问题级止损动作定义”
- 本 Policy：负责“止损只执行一次”
