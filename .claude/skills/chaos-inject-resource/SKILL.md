---
name: chaos-inject-resource
description: 向目标服务注入 CPU 或内存资源压力（kubectl exec + kill-to-recover），触发资源告警。用法：/chaos-inject-resource [service] [type] [value] [duration]
license: MIT
compatibility:
  claude_code: ">=1.0"
metadata:
  author: xianb
  version: 3.0.0
  generatedBy: claude-sonnet-4-6
---

# 资源耗尽注入（kill-to-recover）

通过 `kubectl exec` 在 Pod 内启动守护进程施加资源压力。注入成功后直接退出，**不自动恢复**，恢复由用户手动执行 `kubectl delete pod`。

## 用法

```
/chaos-inject-resource [service] [type] [value]
```

### 参数

- `service`: 目标服务（如 `loadgenerator`、`redis-cart`）
- `type`: `cpu` 或 `memory`
- `value`: 压力值（CPU：worker 数量如 `5`；内存：MiB 如 `512`）

## 前置要求

- 容器需要有 `sh`（Alpine/busybox 均满足）
- CPU 注入使用 `yes > /dev/null`（无需 stress-ng 或 python）
- 内存注入使用 python3 double-fork（需要 python3）
- `/dev/shm` 可写（用于存放注入脚本，绕过只读 rootfs）
- `setsid` 可用（alpine busybox 内置）

## 容器支持情况

| 服务 | CPU 注入 | 内存注入 | 备注 |
|------|---------|---------|------|
| redis-cart | ✅ | ✅ | Alpine, /dev/shm 可写 |
| loadgenerator | ✅ | ✅ | Python 镜像 |
| emailservice | ✅ | ✅ | Python 镜像 |
| recommendationservice | ✅ | ✅ | Python 镜像 |
| frontend 等 distroless | ❌ | ❌ | 无 shell |

## 执行步骤

### 步骤 1：获取 Pod

```bash
POD=$(kubectl get pods -n online-boutique -l app=<service> -o name | head -1 | cut -d'/' -f2)
echo "Target Pod: $POD"
```

### 步骤 2：记录基准

```bash
kubectl exec -n online-boutique $POD -- sh -c "
echo 'Load avg:' \$(cat /proc/loadavg)
ps aux | head -5
"
```

### 步骤 3：注入 CPU 压力（yes worker）

将脚本写入 `/dev/shm`（绕过只读 rootfs），用 `setsid` 脱离 exec session：

```bash
kubectl exec -n online-boutique $POD -- sh -c '
cat > /dev/shm/cpu_stress.sh << "EOF"
#!/bin/sh
for i in $(seq 1 <value>); do
  yes > /dev/null &
done
wait
EOF
chmod +x /dev/shm/cpu_stress.sh
setsid /dev/shm/cpu_stress.sh &
echo "Injected <value> yes workers, setsid PID=$!"
'
```

### 步骤 4：注入内存压力（python3 double-fork）

```bash
kubectl exec -n online-boutique $POD -- python3 -c "
import os, sys, time
if os.fork() > 0: sys.exit(0)
if os.fork() > 0: sys.exit(0)
os.setsid()
size = <value> * 1024 * 1024
buf = bytearray(size)
while True:
    _ = buf[len(buf)//2]
    time.sleep(1)
" &
sleep 2
```

### 步骤 5：确认注入成功

```bash
sleep 3
kubectl exec -n online-boutique $POD -- sh -c "
echo 'Load avg:' \$(cat /proc/loadavg)
echo 'Chaos processes:'
ps aux | grep -E 'yes|python3' | grep -v grep
"
```

进程存在即注入成功，**直接退出，不等待告警，不自动恢复**。

输出注入摘要：

```
✅ 注入完成
   Pod:     <pod>
   Service: <service>
   类型:    CPU (<value> × yes workers)
   恢复方式: kubectl delete pod -n online-boutique <pod>
```

## 预期告警

| 故障类型 | 预期告警 | 触发阈值 |
|---------|---------|---------|
| CPU | AppHighCPUUsage | > 0.1 cores 持续 30s |
| CPU | AppCPUThrottling | 节流 > 50% 持续 30s |
| 内存 | AppHighMemoryUsage | > 400MiB 持续 30s |

## 恢复方式（手动执行）

```bash
kubectl delete pod -n online-boutique <pod>
```

kill Pod 后 Deployment 自动重建干净的新 Pod，chaos 进程随 cgroup 一起消亡。

## kill-to-recover 原理

```
注入阶段：
kubectl exec → setsid cpu_stress.sh → yes × N workers
   ↓
Pod 进程表：
  PID 1    redis-server
  PID 55   yes  ← chaos
  PID 56   yes  ← chaos
  ...

恢复阶段（手动）：
kubectl delete pod
   ↓
Linux cgroup 清空：所有进程消亡（含 chaos）
   ↓
新 Pod：只有 PID 1 业务进程 ✅
```

## 核心原则

- **CPU 注入固定用 `yes > /dev/null`**：Alpine/busybox 通用，无需额外工具
- **脚本写入 `/dev/shm`**：绕过只读 rootfs，busybox `setsid` 需要可执行文件路径
- **注入成功即退出**：不等待、不监控、不自动恢复，保持 skill 职责单一
- **告警规则代码固化**：`deploy/monitoring/alerting/chaos-testing-alerts.yaml`

## 验收标准

- [x] 获取目标 Pod 并确认存在
- [x] 记录基准 load avg
- [x] CPU：通过 `setsid /dev/shm/cpu_stress.sh` 启动 N 个 `yes > /dev/null`
- [x] 内存：通过 python3 double-fork 占用指定 MiB
- [x] exec session 结束后进程仍存在（setsid 脱离）
- [x] 输出注入摘要后退出，不自动恢复
