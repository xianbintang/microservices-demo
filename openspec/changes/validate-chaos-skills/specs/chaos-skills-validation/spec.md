## ADDED Requirements

### Requirement: 告警覆盖度检查 skill 可执行

`/chaos-check-alerts` SHALL 能在 kind 集群上扫描 Prometheus 告警规则，对比内置关键场景清单（15 条），输出覆盖度报告，并给出是否允许执行混沌实验的结论。

覆盖率阈值：总体 ≥ 80%，Critical 场景必须 100% 覆盖。

#### Scenario: 执行告警覆盖度检查

- **WHEN** 用户触发 `/chaos-check-alerts online-boutique`
- **THEN** 输出包含：已覆盖告警列表、缺失告警列表、覆盖率百分比、是否允许执行实验的结论

#### Scenario: 覆盖率不足时阻塞实验

- **WHEN** Prometheus 中 Critical 级别告警场景覆盖率 < 100%
- **THEN** 输出明确标注 "阻塞：补充缺失告警规则后重试"，不允许继续执行注入实验

---

### Requirement: Pod 故障注入 skill 可执行

`/chaos-inject-pod` SHALL 在 kind 集群上成功创建 PodChaos CRD，终止目标服务的 Pod，并记录基准指标和实验元数据。

#### Scenario: 指定服务注入 Pod 故障

- **WHEN** 用户触发 `/chaos-inject-pod frontend 2m`
- **THEN** Chaos Mesh 成功创建 PodChaos 资源，frontend Pod 被终止并由 K8s 重建，Skill 输出实验 ID、目标 Pod 名、实验时长

#### Scenario: 随机选择服务注入 Pod 故障

- **WHEN** 用户触发 `/chaos-inject-pod`（不指定服务）
- **THEN** Skill 从 online-boutique namespace 随机选择一个服务执行 PodKill

---

### Requirement: 网络延迟注入 skill 可执行

`/chaos-inject-network` SHALL 在目标环境上尝试创建 NetworkChaos CRD，注入指定延迟，并明确告知用户在 kind 环境下的兼容性状态。

#### Scenario: 注入网络延迟

- **WHEN** 用户在 kind 集群触发 `/chaos-inject-network recommendationservice 500ms 3m`
- **THEN** Skill 尝试创建 NetworkChaos CRD，检查 chaos-daemon tc 模块状态；若 tc 不支持则输出明确的环境限制说明，不静默失败；若支持则输出实验状态

---

### Requirement: 资源耗尽注入 skill 可执行

`/chaos-inject-resource` SHALL 在目标 Pod 上创建 StressChaos CRD，施加 CPU 或内存压力，并验证相关告警触发。

#### Scenario: CPU 压力注入

- **WHEN** 用户触发 `/chaos-inject-resource checkoutservice cpu 80 5m`
- **THEN** StressChaos CRD 创建成功，目标 Pod CPU 使用率上升，Skill 输出当前 CPU 使用率和预期告警

#### Scenario: 内存压力注入

- **WHEN** 用户触发 `/chaos-inject-resource checkoutservice memory 512 5m`
- **THEN** StressChaos CRD 创建成功，目标 Pod 内存使用率上升

---

### Requirement: 依赖故障注入 skill 可执行

`/chaos-inject-dependency` SHALL 通过 NetworkChaos 或 HTTPChaos 模拟依赖服务不可用，使调用方接收到连接超时或 5xx 响应。

#### Scenario: 模拟依赖服务不可用

- **WHEN** 用户触发 `/chaos-inject-dependency cartservice redis 3m`
- **THEN** 创建对应 Chaos CRD，cartservice 到 Redis 的连接失败，Skill 输出故障类型和预期告警

---

### Requirement: 级联故障注入 skill 可执行

`/chaos-inject-cascade` SHALL 同时创建多个 Chaos CRD（PodChaos + NetworkChaos 或其他组合），模拟多点同时故障场景。

#### Scenario: 执行默认级联故障配置

- **WHEN** 用户触发 `/chaos-inject-cascade default`
- **THEN** 同时创建 2 个以上 Chaos CRD，Skill 显示所有故障的状态和预期影响

---

### Requirement: 混沌实验监控 skill 可执行

`/chaos-monitor` SHALL 查询当前运行中的所有 Chaos Mesh CRD，显示实验状态、目标服务的实时关键指标（错误率、延迟）和告警状态。

#### Scenario: 监控运行中的实验

- **WHEN** 用户在实验进行中触发 `/chaos-monitor`
- **THEN** 输出包含：所有运行中的 Chaos CRD 名称、目标服务、已运行时长、当前错误率和 P95 延迟

---

### Requirement: 告警验证 skill 可执行

`/chaos-validate-alerts` SHALL 查询 Alertmanager API 获取实验期间触发的告警，与预期告警列表对比，输出验证报告。

#### Scenario: 验证实验期间告警触发情况

- **WHEN** 用户在实验结束后触发 `/chaos-validate-alerts`
- **THEN** 输出：预期告警列表、实际触发告警列表、覆盖率百分比、未触发告警的可能原因

---

### Requirement: 自我恢复验证 skill 可执行

`/chaos-validate-self-heal` SHALL 在故障移除后检查服务状态（Pod Running、Endpoints Ready、错误率恢复），输出恢复时间和健康状态。

#### Scenario: 验证 Pod 故障后自我恢复

- **WHEN** PodChaos 实验结束后用户触发 `/chaos-validate-self-heal`
- **THEN** 输出：Pod 状态（Ready/NotReady）、Service endpoints 状态、当前错误率与基准对比、恢复时间

---

### Requirement: 实验报告生成 skill 可执行

`/chaos-report` SHALL 汇总实验信息、观察数据、告警验证结果，生成结构化 Markdown 报告，包含改进建议。

#### Scenario: 生成完整实验报告

- **WHEN** 用户在实验完成后触发 `/chaos-report`
- **THEN** 输出包含：实验元数据、基准指标、实验期间指标、告警验证结果、自我恢复结果、改进建议（指向具体文件路径）

---

### Requirement: 中止实验 skill 可执行

`/chaos-abort` SHALL 删除所有运行中的 Chaos Mesh CRD，等待故障移除，验证资源清理完成。

#### Scenario: 中止所有运行中实验

- **WHEN** 用户触发 `/chaos-abort`
- **THEN** 所有 Chaos CRD 被删除，输出已中止的实验列表和清理确认

#### Scenario: 中止指定实验

- **WHEN** 用户触发 `/chaos-abort network-latency-experiment`
- **THEN** 只删除指定名称的 Chaos CRD，其他实验不受影响

---

### Requirement: 告警规则完整覆盖关键场景

`deploy/monitoring/alerting/chaos-testing-alerts.yaml` SHALL 包含所有 `chaos-check-alerts` skill 要求的 15 个关键告警场景对应的 PrometheusRule，且每条规则的 PromQL 表达式在当前 Prometheus 数据中可实际触发。

#### Scenario: 覆盖率检查通过

- **WHEN** 用户在补全告警规则后触发 `/chaos-check-alerts`
- **THEN** 总体覆盖率 ≥ 80%，所有 Critical 级别场景覆盖率 = 100%，输出"允许执行实验"

---

### Requirement: Chaos Mesh 实验 YAML 模板字段正确

`deploy/chaos/*.yaml` 中的所有实验模板 SHALL 使用正确的 namespace（`online-boutique`）、有效的 label selector、正确的 API 字段名称（与 Chaos Mesh 当前版本匹配）。

#### Scenario: 直接 kubectl apply 实验模板成功

- **WHEN** 用户执行 `kubectl apply -f deploy/chaos/network-latency.yaml`
- **THEN** 命令成功，Chaos Mesh 接受该 CRD，不报 namespace 错误或字段验证错误
