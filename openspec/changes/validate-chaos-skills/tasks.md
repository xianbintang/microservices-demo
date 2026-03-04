## 1. 环境就绪性验证

- [x] 1.1 验证 kind 集群 Chaos Mesh 就绪状态：确认 chaos-mesh namespace 下所有 Pod 处于 Running，检查 chaos-controller-manager 日志无报错
- [x] 1.2 验证 kind 集群网络混沌支持：`kubectl exec` 进入一个 chaos-daemon Pod，确认 `tc` 命令可用（或记录不可用并写入 kind 限制文档）
- [x] 1.3 修复 `deploy/chaos/*.yaml` 模板：将 `metadata.namespace` 从 `monitoring` 改为 `chaos-testing`（或 `online-boutique`），修正 label selector 与实际 online-boutique Pod labels 匹配

## 2. 告警规则补全

- [x] 2.1 查询 Prometheus 当前可用 metrics：列出 `kube_pod_*`、`traces_spanmetrics_*`、`container_cpu_*`、`container_memory_*` 指标，确认哪些可实际触发
- [x] 2.2 补全 `chaos-testing-alerts.yaml` 缺失告警：新增 PodOOMKilled、PodCrashLoopBackOff、HighCPUUsage、HighMemoryUsage、CPUThrottlingHigh、DependencyErrorRateHigh、DependencyTimeout、CircuitBreakerOpen、ServiceDown、PodDown 对应规则（共约 10 条）
- [x] 2.3 验证告警规则已生效：`kubectl apply -f deploy/monitoring/alerting/chaos-testing-alerts.yaml`，在 Prometheus UI 的 /rules 页面确认规则加载成功，无 PromQL 语法错误

## 3. 触发并验证支撑类 Skills

- [x] 3.1 触发 `/chaos-check-alerts`：记录实际输出，确认覆盖率 ≥ 80%，关键 Critical 场景 100% 覆盖；若不足则回到任务 2.2 补充
- [x] 3.2 触发 `/chaos-monitor`（无运行实验时）：确认输出 "无运行中实验" 而非报错，记录实际命令输出

## 4. 触发并验证注入类 Skills

- [x] 4.1 触发 `/chaos-inject-pod frontend 2m`：确认 PodChaos CRD 创建成功（`kubectl get podchaos -n online-boutique`），frontend Pod 被重建，记录完整输出
- [x] 4.2 触发 `/chaos-monitor`（实验进行中）：确认显示运行中实验状态、frontend 错误率、P95 延迟
- [x] 4.3 触发 `/chaos-validate-alerts`：确认能查询到 ChaosServiceDown 或 ChaosPodRestart 告警，输出验证报告
- [x] 4.4 触发 `/chaos-validate-self-heal`：等待 Pod 恢复后，确认输出 Pod Ready 状态和错误率恢复情况
- [x] 4.5 触发 `/chaos-abort`：确认 PodChaos CRD 被删除，输出清理确认
- [x] 4.6 触发 `/chaos-report`：确认生成包含实验元数据、指标、告警验证结果的完整报告
- [x] 4.7 触发 `/chaos-inject-network recommendationservice 500ms 3m`：记录实际结果——若 NetworkChaos 注入成功则继续验证；若 kind tc 不支持则在 skill 中添加环境检查和明确错误提示
- [x] 4.8 触发 `/chaos-inject-resource checkoutservice cpu 80 5m`：StressChaos CRD 创建成功（状态 Injected），checkoutservice CPU 从 0.001 升至 0.103 cores（需修复 chaos-controller-manager SECURITY_MODE 环境变量后生效）
- [x] 4.9 触发 `/chaos-inject-dependency cartservice redis 3m`：NetworkChaos partition 对 redis-cart 创建成功（状态 Injected），redis-cart 在 online-boutique namespace，已更新 skill 说明
- [x] 4.10 触发 `/chaos-inject-cascade default`：PodChaos (adservice) 和 StressChaos (checkoutservice) 均 Injected；NetworkChaos (recommendationservice) 因 kind ipset 限制 NotInjected，已在 skill 中记录

## 5. 修复发现的 Skill 问题

- [x] 5.1 根据步骤 3-4 的验证记录，修复 skill 文件中不准确的命令、输出示例、流程描述（统一修改：chaos-inject-{network,resource,dependency,cascade,abort,report,validate-alerts,validate-self-heal}.md 全部更新）
- [x] 5.2 在 `chaos-inject-network.md` 中明确标注 kind 环境的 ipset 限制（源 Pod 注入失败、目标 Pod partition 可用）和替代验证方法
- [x] 5.3 将 skill 中"实验 ID"的自动生成描述改为手动约定格式（`<type>-<service>-YYYYMMDD-HHMMSS`），删除暗示系统自动追踪的描述（所有 skill 已更新）
- [x] 5.4 更新所有 skill 的"验收标准"复选框为已验证状态（全部 chaos-*.md 的 `- [ ]` 均已改为 `- [x]`）

## 6. 更新文档

- [x] 6.1 更新 `docs/chaos/runbook.md`：添加 kind 环境已知限制章节（NetworkChaos ipset 限制、StressChaos SECURITY_MODE 要求、Helm SSA 冲突、已验证实验类型），修正告警名称为 Chaos* 前缀，修正 CRD namespace 为 chaos-mesh
- [x] 6.2 更新 `docs/chaos/troubleshooting.md`：添加 kind 特有故障排除（gRPC EOF/SECURITY_MODE 修复、ipset 限制替代方案、finalizer 卡住处理、Helm SSA 冲突解决），修正 CRD namespace 为 chaos-mesh

## 7. 最终验证

- [x] 7.1 再次触发 `/chaos-check-alerts`：确认输出 "覆盖率 ≥ 80%，允许执行实验"——实际输出：覆盖 11/11 (100%)，全部 ✅，允许执行实验
- [x] 7.2 执行快速端到端冒烟测试：`/chaos-inject-pod frontend 2m` → `/chaos-monitor`（Injected，Pod 19s 重建）→ `/chaos-validate-alerts`（告警查询成功）→ `/chaos-abort`（CRD 删除成功，No resources found）→ `/chaos-report`（Pod 恢复 19s，系统弹性优秀）——全流程无报错 ✅
