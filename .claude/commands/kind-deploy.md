---
description: 一键部署 Online Boutique + 完整可观测性栈（Prometheus, Grafana, Loki, Tempo）到本地 kind 集群或任意远端 K8s 集群。自动检测 arm64/amd64 环境，arm64 从源码构建原生镜像，amd64 拉取 Google 预构建镜像。用法：/kind-deploy [local|down|remote REGISTRY=xxx [CONTEXT=yyy]]
---

## 任务

根据参数 `$ARGUMENTS` 执行 Online Boutique 部署操作。

## 参数解析

- 无参数 / `local`：本地 kind 集群完整部署（自动检测 arm64/amd64）
- `down`：销毁本地 kind 集群和 registry
- `remote REGISTRY=xxx [CONTEXT=yyy]`：部署到远端 K8s 集群

---

## local 模式（默认）

顺序执行以下步骤，任一步骤失败则停止并报告错误。

### 1. 检查前置工具

```bash
make -f Makefile.kind check-prereqs
```

若缺少工具，提示用户安装方式：
- `kind`: `brew install kind`（Mac）或 https://kind.sigs.k8s.io/docs/user/quick-start/
- `helm`: `brew install helm`
- `kubectl`: `brew install kubectl`
- `docker` / `podman`: Docker Desktop for Mac（需分配 8GB+ 内存）

### 2. 启动本地 Registry 并创建 kind 集群

```bash
make -f Makefile.kind create-registry create-cluster
```

这会：
- 在 host 端口 5001 启动 `kind-registry` 容器（registry:2）
- 创建名为 `online-boutique` 的 kind 集群
- 配置 containerd mirror：`us-central1-docker.pkg.dev` → `kind-registry:5000`（本地透明代理）
- 将 kind-registry 加入 containerd NO_PROXY（避免被系统代理劫持）

### 3. 准备镜像（arch-aware）

```bash
make -f Makefile.kind prepare-images
```

**自动根据主机架构分发：**

| 主机架构 | 执行路径 | 说明 |
|---------|---------|------|
| `arm64` (Mac M系列) | `build-images` | 从 `src/` 构建原生 arm64 镜像 |
| `amd64` (x86 Linux/Mac) | `pull-images` | 从 Google public registry 拉取预构建 amd64 镜像 |

**arm64 特殊说明：**
- 10 个应用服务从源码构建（Go/Node.js/Python/Java 均支持 arm64）
- `cartservice`（.NET）除外：Grpc.Tools 2.76.0 的 `linux_arm64/protoc` 有 SIGSEGV bug，保留 amd64（I/O 密集型，Rosetta 开销可接受）
- `redis`, `busybox`, `otel-collector-contrib` 从公共 registry 拉取原生 arm64 版本

**首次耗时估算：**
- arm64 构建模式：20-40 分钟（编译所有服务）
- amd64 拉取模式：5-15 分钟（取决于网络）

### 4. 部署可观测性栈

```bash
make -f Makefile.kind deploy-monitoring
```

部署：kube-prometheus-stack → Loki → Tempo → Promtail（均使用公共多架构镜像，containerd 自动选对应架构）

### 5. 部署 Online Boutique 微服务

```bash
make -f Makefile.kind deploy-app
```

包含：
- Helm install `helm-chart/`（使用 kind overlay `deploy/kind/values-kind.yaml`）
- `patch-probes`：将 gRPC liveness probe 改为 TCP socket probe（kind 单节点更稳定）
- `patch-loadgenerator`：默认 10 并发用户

### 6. 启动端口转发

```bash
make -f Makefile.kind port-forward
```

### 7. 显示 Pod 状态

```bash
make -f Makefile.kind status
```

### 8. 输出访问地址

- Frontend: http://localhost:8080
- Grafana:  http://localhost:3000（admin / admin）

---

## down 模式

```bash
make -f Makefile.kind down
```

销毁 kind 集群 `online-boutique`、本地 registry `kind-registry`，释放端口转发进程。

---

## remote 模式

从 `$ARGUMENTS` 中解析 `REGISTRY=xxx` 和可选的 `CONTEXT=xxx`，然后执行：

```bash
make -f Makefile.kind deploy-remote REGISTRY=<value> [CONTEXT=<value>]
```

**自动流程：**
1. 自动检测目标集群 node 架构（`kubectl get nodes -o jsonpath='{.items[0].status.nodeInfo.architecture}'`）
2. 根据检测结果构建对应架构镜像（arm64 or amd64），推送到 REGISTRY
3. 部署完整监控栈 + Online Boutique 应用

**示例：**
```bash
# 部署到当前 context 的集群（自动检测架构）
make -f Makefile.kind deploy-remote REGISTRY=my.registry.io

# 指定 context（arm64 集群）
make -f Makefile.kind deploy-remote REGISTRY=my.registry.io CONTEXT=my-arm64-cluster
```

---

## 故障排查

| 症状 | 排查步骤 |
|------|---------|
| `ImagePullBackOff` | 检查 `make pull-images` / `build-images` 是否成功；`docker network inspect kind` 确认 kind-registry 在 kind 网络中 |
| `CrashLoopBackOff` | `kubectl logs -n online-boutique <pod>` 查看日志 |
| Grafana 无数据 | 等 2-3 分钟让 spanmetrics 开始生成；检查 `kubectl get pods -n monitoring` 全部 Running |
| kind 创建失败 | 确认 Docker/Podman 正在运行且分配了 8GB+ 内存 |
| 端口冲突 8080/3000 | 手动执行 `kubectl port-forward` 指定其他端口 |
| arm64 build 超时 | 单次 build 最慢（adservice Java）约 10 分钟；可单独重试 `make -f Makefile.kind build-images` |
| containerd 镜像未更新 | 删除缓存后重启 Pod：`podman exec online-boutique-control-plane ctr --namespace k8s.io images rm <image>` + `kubectl rollout restart deployment/<svc> -n online-boutique` |

## 重要说明

- `make up` 幂等：重复运行不会重建已存在的资源
- 所有数据使用 emptyDir（临时），Pod 重启后丢失
- SRE agent 在 kind 模式下禁用（需自定义 `sre-agent:latest` 镜像）
- DingTalk 告警未配置（无 token）
- Tempo gRPC streaming 已禁用（Tempo 2.5.0 不支持 `/api/search/stream`）
- 调整负载：`make -f Makefile.kind patch-loadgenerator LOAD_USERS=20`
