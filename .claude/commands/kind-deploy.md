---
description: 一键部署 Online Boutique + kube-prometheus-stack（Prometheus + Promtail）到本地 kind 集群或任意远端 K8s 集群。自动检测 arm64/amd64 环境，arm64 从源码构建原生镜像，amd64 拉取 Google 预构建镜像。用法：/kind-deploy [local|down|remote REGISTRY=xxx [CONTEXT=yyy]]
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

### 3. 准备镜像（三级优先级，优先复用本地缓存）

**执行前必须先做 registry 预检**，按优先级选择最快路径：

#### 3a. 检查 registry 当前状态

```bash
curl -s --noproxy localhost http://localhost:5001/v2/_catalog | \
  python3 -c "import json,sys; repos=json.load(sys.stdin)['repositories']; print(f'Registry: {len(repos)}/14 images'); [print(' ✅', r.split('/')[-1]) for r in sorted(repos)]"
```

所需 14 个镜像：`adservice` `cartservice` `checkoutservice` `currencyservice` `emailservice` `frontend` `loadgenerator` `paymentservice` `productcatalogservice` `recommendationservice` `shippingservice` `busybox` `redis` `opentelemetry-collector-contrib`

#### 3b. 按优先级选择路径

**路径 A — 全部就绪（跳过此步骤）：** Registry 已有 14 个镜像 → 直接进入步骤 4，无需任何操作。

**路径 B — 部分缺失（从本地 podman 补推，秒级完成，无需网络）：**

先用以下脚本找出缺失镜像并从本地 podman 推送：

```bash
REGISTRY_REPOS=$(curl -s --noproxy localhost http://localhost:5001/v2/_catalog | \
  python3 -c "import json,sys; print(' '.join(json.load(sys.stdin)['repositories']))")

for img in adservice cartservice checkoutservice currencyservice emailservice \
           frontend loadgenerator paymentservice productcatalogservice \
           recommendationservice shippingservice; do
  if ! echo "$REGISTRY_REPOS" | grep -q "$img"; then
    echo "→ 推送 $img (from local podman)"
    podman push --tls-verify=false \
      "localhost:5001/google-samples/microservices-demo/${img}:v0.10.4" 2>&1 | tail -1
  fi
done

for img_tag in "busybox:latest" "redis:alpine" "opentelemetry-collector-contrib:0.144.0"; do
  img="${img_tag%%:*}"
  if ! echo "$REGISTRY_REPOS" | grep -q "$img"; then
    echo "→ 推送 $img (from local podman)"
    podman push --tls-verify=false \
      "localhost:5001/google-samples/microservices-demo/${img_tag}" 2>&1 | tail -1
  fi
done
```

若 podman 中也没有某个镜像（`podman push` 报 `image not known`），则该镜像进入路径 C。

**路径 C — 本地无缓存（从网络拉取或构建，耗时）：**

```bash
make -f Makefile.kind prepare-images
```

| 主机架构 | 执行路径 | 耗时估算 |
|---------|---------|---------|
| `arm64` (Mac M系列) | 从 `src/` 构建原生 arm64 镜像 | 20–40 分钟（首次）|
| `amd64` (Intel Mac) | 从 Google registry 拉取 amd64 镜像 | 5–15 分钟 |

**arm64 说明：** cartservice 保留 amd64（Grpc.Tools 2.76.0 arm64 protoc 有 SIGSEGV bug）；redis/busybox/otelcol 拉取公共多架构镜像。

### 4. 部署监控组件（kube-prometheus-stack + Promtail）

```bash
make -f Makefile.kind deploy-monitoring
```

部署：kube-prometheus-stack → Promtail（均使用公共多架构镜像，containerd 自动选对应架构）

**说明：** Grafana、Loki、Tempo、Alertmanager 运行在远端 Docker 栈（`47.83.217.162`），与 kind 集群部署解耦。kind 本地只运行 Prometheus（负责 k8s 指标采集 + remote_write 到远端）和 Promtail（负责容器日志采集 + 推送到远端 Loki）。

### 5. 部署 Online Boutique 微服务

**执行前必须先检查 helm release 状态**，清理因中断留下的锁：

```bash
HELM_STATUS=$(helm status online-boutique -n online-boutique -o json 2>/dev/null | \
  python3 -c "import json,sys; print(json.load(sys.stdin).get('info',{}).get('status','not-found'))" 2>/dev/null || echo "not-found")
echo "Helm release status: $HELM_STATUS"
```

| 状态 | 处理方式 |
|------|---------|
| `not-found` | 直接安装，无需清理 |
| `deployed` | 直接 upgrade，无需清理 |
| `pending-install` / `pending-upgrade` | **必须先执行** `helm uninstall online-boutique -n online-boutique`，再安装 |
| `failed` | 执行 `helm uninstall online-boutique -n online-boutique`，再安装 |

清理命令（仅当状态为 pending-* 或 failed 时执行）：

```bash
helm uninstall online-boutique -n online-boutique
```

然后执行：

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
- Grafana:  http://47.83.217.162:3000（admin / admin，远端 Docker 栈，与 kind 集群独立部署）

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
3. 部署监控组件 + Online Boutique 应用

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
| `another operation in progress` (helm) | 执行步骤 5 的 helm status 检查，`helm uninstall online-boutique -n online-boutique` 清锁后重试 |
| Registry 空（重建后镜像丢失） | 先检查 `podman images \| grep localhost:5001`，有则用步骤 3b 脚本批量推送；全无则运行 `make -f Makefile.kind prepare-images` |
| `ImagePullBackOff` | 检查 `make pull-images` / `build-images` 是否成功；`docker network inspect kind` 确认 kind-registry 在 kind 网络中 |
| `CrashLoopBackOff` | `kubectl logs -n online-boutique <pod>` 查看日志 |
| Prometheus 无数据 | 检查 `kubectl get pods -n monitoring` 全部 Running；等 2-3 分钟让 spanmetrics 开始生成 |
| kind 创建失败 | 确认 Docker/Podman 正在运行且分配了 8GB+ 内存 |
| 端口冲突 8080 | 手动执行 `kubectl port-forward` 指定其他端口 |
| arm64 build 超时 | 单次 build 最慢（adservice Java）约 10 分钟；可单独重试 `make -f Makefile.kind build-images` |
| containerd 镜像未更新 | 删除缓存后重启 Pod：`podman exec online-boutique-control-plane ctr --namespace k8s.io images rm <image>` + `kubectl rollout restart deployment/<svc> -n online-boutique` |

## 重要说明

- `make up` 幂等：重复运行不会重建已存在的资源
- 所有数据使用 emptyDir（临时），Pod 重启后丢失
- Tempo gRPC streaming 已禁用（Tempo 2.5.0 不支持 `/api/search/stream`）
- 调整负载：`make -f Makefile.kind patch-loadgenerator LOAD_USERS=20`
