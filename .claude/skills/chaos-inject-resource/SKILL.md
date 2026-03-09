---
name: chaos-inject-resource
description: 向目标服务注入 CPU 或内存资源压力（kubectl exec + kill-to-recover），触发资源告警。用法：/chaos-inject-resource [service] [type] [value] [duration]
license: MIT
compatibility:
  claude_code: ">=1.0"
metadata:
  author: xianb
  version: 2.0.0
  generatedBy: claude-sonnet-4-6
---

# 资源耗尽注入（kill-to-recover）

通过 `kubectl exec` 直接在 Pod 内启动守护进程施加 CPU 或内存压力。kill Pod 即可恢复（新 Pod 不含 chaos 进程）。

## 用法

```
/chaos-inject-resource [service] [type] [value] [duration]
```

### 参数

- `service`: 目标服务（如 `loadgenerator`、`redis-cart`）
- `type`: `cpu` 或 `memory`
- `value`: 压力值（CPU：cores 如 `2`；内存：MiB 如 `512`）
- `duration`: 可选，实验时长（默认：5m）

## 前置要求

### 容器需要有 python 或 shell

- ✅ 支持：`loadgenerator` (python)、`redis-cart` (alpine+python3)、`emailservice` (python)
- ❌ 不支持：`frontend`、`checkoutservice` 等 distroless 镜像

### 双叉守护进程要求

容器需要 `allowPrivilegeEscalation: true` 或放开 seccomp 限制（大多数默认配置已满足）。

## 执行步骤

### 步骤 1：检查目标容器

```bash
kubectl get pods -n online-boutique -l app=<service> -o name | head -1
```

### 步骤 2：记录基准资源使用

```bash
POD=$(kubectl get pods -n online-boutique -l app=<service> -o name | head -1 | cut -d'/' -f2)

echo "📊 基准资源使用（${POD}）"
kubectl exec -n online-boutique ${POD} -- ps aux | grep -E "PID|stress" | head -5

kubectl top pod -n online-boutique ${POD}
```

### 步骤 3：注入故障

**选择目标 Pod（通常选第一个）：**

```bash
POD=$(kubectl get pods -n online-boutique -l app=<service> -o name | head -1 | cut -d'/' -f2)
```

**CPU 压力（双叉守护进程）：**

```bash
kubectl exec -n online-boutique ${POD} -- python3 -c "
import os, sys, subprocess, time, signal

# 当前进程
pid = os.getpid()
print(f'Injector PID: {pid}', file=sys.stderr, flush=True)

# 第一次 fork → 子进程退出
if os.fork() > 0:
    sys.exit(0)

# 第二次 fork → 孙进程独立运行
if os.fork() > 0:
    sys.exit(0)

# 孙进程：创建独立 session + detach
os.setsid()
os.chdir('/')
signal.signal(signal.SIGCHLD, signal.SIG_IGN)

print(f'Daemon PID: {os.getpid()}', file=sys.stderr, flush=True)

# 启动 stress-ng（持续占用 CPU）
subprocess.run(['stress-ng', '--cpu', '2', '--cpu-load', str(<value> * 100)])
" &
sleep 2
```

**内存压力（双叉守护进程）：**

```bash
kubectl exec -n online-boutique ${POD} -- python3 -c "
import os, sys, time

# 当前进程
pid = os.getpid()
print(f'Injector PID: {pid}', file=sys.stderr, flush=True)

# 第一次 fork
if os.fork() > 0:
    sys.exit(0)

# 第二次 fork
if os.fork() > 0:
    sys.exit(0)

# 孙进程：守护化
os.setsid()
os.chdir('/')
print(f'Daemon PID: {os.getpid()}', file=sys.stderr, flush=True)

# 持续占用内存（避免被优化）
size = <value> * 1024 * 1024  # MiB → bytes
buffer = bytearray(size)
while True:
    # 触发实际访问，防止被优化掉
    _ = buffer[len(buffer)//2]
    time.sleep(1)
" &
sleep 2
```

### 步骤 4：确认注入状态

```bash
kubectl exec -n online-boutique ${POD} -- ps aux | grep -E "stress-ng|python3"
kubectl top pod -n online-boutique ${POD}
```

期望看到 stress-ng 或 python3 进程占用资源。

### 步骤 5：等待告警触发

```bash
echo "⏳ 等待 <duration> 观察告警..."
sleep <duration>
```

### 步骤 6：恢复（kill-to-recover）

```bash
kubectl delete pod -n online-boutique ${POD}
echo "✅ Pod 已删除，新 Pod 将自动恢复（无 chaos 进程）"
```

验证新 Pod 干净：

```bash
NEW_POD=$(kubectl get pods -n online-boutique -l app=<service> -o name | head -1 | cut -d'/' -f2)
kubectl exec -n online-boutique ${NEW_POD} -- ps aux | grep -E "stress-ng|python3" || echo "✅ 新 Pod 无 chaos 进程"
```

## 预期告警

| 故障类型 | 预期告警 | 触发阈值 |
|---------|---------|---------|
| CPU | ChaosHighCPUUsage | > 0.5 cores 持续 1m |
| CPU | ChaosCPUThrottling | 节流 > 50% 持续 1m |
| 内存 | ChaosHighMemoryUsage | > 400MiB 持续 1m |
| 内存超限 | ChaosOOMKilled | 容器被 OOM 终止 |

## kill-to-recover 原理

```
注入阶段：
kubectl exec → python3 double-fork → 守护进程 PID 30
   ↓
旧 Pod 进程表：
  PID 1   业务进程
  PID 30  python3 [chaos]  ← exec 注入

恢复阶段：
kubectl delete pod
   ↓
Linux cgroup 清空：PID 1 + PID 30 全部消亡
   ↓
Deployment 控制器创建新 Pod
   ↓
新 Pod 进程表：
  PID 1   业务进程
  （无 chaos 进程）  ← ✅ kill-to-recover
```

## 与 Chaos Mesh StressChaos 对比

| 方式 | 注入位置 | Kill Pod 能恢复？ | 原理 |
|-----|---------|-----------------|------|
| StressChaos | chaos-daemon 外部管理 | ❌ 否 | daemon 监听 Pod，新 Pod 重新注入 |
| **kubectl exec** | Pod 内部进程 | ✅ 是 | 进程属于 Pod cgroup，Pod 死→进程死→新 Pod 干净 |

## 局限性

1. **需要容器有 python**：distroless 镜像不支持（可用 `kubectl debug` ephemeral container 替代）
2. **注入状态不持久**：重启即恢复（这正是 kill-to-recover 的价值）
3. **需要权限**：double-fork 需要 allowPrivilegeEscalation 或放开 seccomp

## 什么时候选择 kill-to-recover

- 应急演练：模拟「重启 Pod 能否解决问题」的判断场景
- 开发调试：临时注入故障，调试完 kill pod 快速清理
- 入门级混沌测试：不想留下 Chaos CRD 状态，测试完即走

## 核心原则

**告警规则必须代码固化** — 告警规则存储于 `deploy/monitoring/alerting/chaos-testing-alerts.yaml`。

## 验收标准

- [x] 检查目标容器存在且有 python/shell
- [x] 记录基准 CPU/内存使用量
- [x] 使用双叉守护进程注入（防止随主进程退出）
- [x] 根据 type 参数生成正确的 stress-ng 或内存占用命令
- [x] kill Pod 后验证新 Pod 无 chaos 进程
