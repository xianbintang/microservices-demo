## Context

当前项目有 11 个混沌工程 Skills（`chaos-abort`、`chaos-check-alerts`、`chaos-inject-cascade`、`chaos-inject-dependency`、`chaos-inject-network`、`chaos-inject-pod`、`chaos-inject-resource`、`chaos-monitor`、`chaos-report`、`chaos-validate-alerts`、`chaos-validate-self-heal`）。这些 Skills 在上一个 Spec 中完成了文档编写，但从未被端到端触发执行过。

现状问题：
- Skills 中描述的命令（如 `kubectl get networkchaos`、`helm test`）从未在真实 kind 集群上验证过
- 告警规则覆盖度不完整：`chaos-check-alerts` 要求 15 个关键场景全部覆盖，但 `chaos-testing-alerts.yaml` 只有 4 条规则
- `deploy/chaos/` 中的实验 YAML 模板字段未经验证（namespace 写 `monitoring` 而非 `online-boutique`，label selector 等）
- Skills 的执行流程描述了不存在的功能（如 Grafana 大盘链接、实验 ID 机制）

环境约束：
- 目标验证环境：本地 kind 集群（已部署 Chaos Mesh、kube-prometheus-stack、Online Boutique）
- Chaos Mesh 已安装（CRD 已确认存在：networkchaos、podchaos 等）
- 可观测性栈：Prometheus + Grafana + Loki + Tempo（自建）
- **只在 kind 本地验证，不涉及 VKE 或其他远端集群**

## Goals / Non-Goals

**Goals:**
- 逐一触发所有 11 个 chaos skills，记录实际运行结果
- 修复 skills 中与实际环境不符的描述、命令、输出格式
- 补全 `chaos-testing-alerts.yaml` 中缺失的告警规则，达到覆盖率 ≥ 80%
- 修复 `deploy/chaos/` 实验 YAML 模板中的字段错误
- 更新 `docs/chaos/` 运行手册反映实际已验证的操作步骤

**Non-Goals:**
- 不新增 Skills（只验证和修复现有 11 个）
- 不实现自动化 CI/CD 测试流水线
- 不考虑 VKE 或其他远端集群（只验证 kind 本地环境）
- 不实现 Grafana 大盘看板（现有大盘已够用）

## Decisions

**决策 1：验证顺序——从支撑 Skills 到注入 Skills**

按依赖关系顺序验证：
1. 基础工具类：`chaos-check-alerts` → `chaos-monitor`
2. 简单注入：`chaos-inject-pod` → `chaos-inject-network` → `chaos-inject-resource`
3. 复杂注入：`chaos-inject-dependency` → `chaos-inject-cascade`
4. 验证与报告：`chaos-validate-alerts` → `chaos-validate-self-heal` → `chaos-report` → `chaos-abort`

理由：注入 Skills 依赖告警覆盖度检查先通过；验证 Skills 需要实验先运行。

**决策 2：告警规则修复策略——仅修改 `chaos-testing-alerts.yaml`**

所有告警规则变更集中在 `deploy/monitoring/alerting/chaos-testing-alerts.yaml`，不触碰 `prometheusrule-app.yaml`（生产规则）。新增规则统一打 `chaos_test: "true"` 标签，便于过滤。

理由：遵循 Skills 中的"告警规则必须代码固化"原则，同时隔离混沌测试告警与生产告警。

**决策 3：Skill 修复粒度——仅修复明确错误，保留设计意图**

发现错误（如命令语法、namespace 错误、不存在的 API）直接修复；设计意图合理但环境暂未支持的功能（如 Grafana 实验大盘）改为可选项并加注释，不删除。

**决策 4：kind 环境特殊处理**

Chaos Mesh 在 kind 中对网络故障有限制（NetworkChaos 需要 tc 内核模块）。验证时：
- `chaos-inject-network`：验证是否能 apply CRD，检查 Chaos Mesh pod 日志确认是否生效
- 若 tc 模块不可用，在 skill 文档中明确标注 kind 环境限制，VKE 环境可正常使用

## Risks / Trade-offs

- **[风险] 告警规则部分场景无 metric 支撑** → 缓解：先检查 Prometheus 实际存在哪些指标（traces_spanmetrics_*、kube_pod_*），只添加能实际触发的告警
- **[风险] kind 环境 NetworkChaos 可能不生效** → 缓解：记录环境约束，在 skill 中加环境前置检查步骤
- **[风险] Chaos Mesh StressChaos 的 resource limit 约束** → 缓解：确认 target Pod 无 limit 或 limit 足够大，或在 skill 中加说明
- **[取舍] 部分 Skill 的"实验 ID"机制是约定，非系统自动生成** → 接受：在 skill 中改为"建议手动记录实验 ID 格式"，不承诺自动追踪
