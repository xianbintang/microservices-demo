## Why

混沌工程 Skills（`.claude/skills/chaos-*.md`）在上一个 Spec 开发完成后，从未作为真实 Skill 被端到端触发验证过。手动验证时发现：告警规则缺失需临时 apply、kind 环境下 Chaos Mesh 故障注入失败、Skills 的输出描述与实际环境能力不匹配。这导致 Skills 无法在需要时可靠使用，形同虚设。

## What Changes

- **逐一触发所有 11 个 chaos skills**，记录实际输出、发现问题
- **修复 skill 文件**：修正命令、环境检测逻辑、输出描述，确保在 kind + VKE 环境下可用
- **修复告警规则**：补全 `chaos-check-alerts` 期望的所有关键告警（PodOOMKilled、DependencyErrorRateHigh 等缺失项），确保覆盖率 ≥ 80%
- **修复 Chaos Mesh YAML 模板**：修正 `deploy/chaos/` 中的实验模板，确保 kind 环境可以成功 apply
- **补全验证文档**：更新 `docs/chaos/` 运行手册，记录已验证的环境约束和已知限制

## Capabilities

### New Capabilities

- `chaos-skills-validation`: 端到端 Skills 验证框架——涵盖环境就绪性检查、各 Skill 触发验证、问题修复追踪和最终验证报告

### Modified Capabilities

（无）

## Impact

- **`.claude/skills/chaos-*.md`**（11 个文件）：可能修复 skill 描述、命令、验证步骤
- **`deploy/monitoring/alerting/chaos-testing-alerts.yaml`**：补全缺失的告警规则
- **`deploy/chaos/*.yaml`**：修复 Chaos Mesh 实验模板（namespace、selector、duration 等字段）
- **`docs/chaos/runbook.md`** 及相关文档：更新已验证的操作步骤和环境限制说明
