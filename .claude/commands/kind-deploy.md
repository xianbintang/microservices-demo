---
description: 在本地 kind 集群（或远端 K8s）一键部署 Online Boutique + 完整可观测性栈（Prometheus, Grafana, Loki, Tempo）。支持 Mac ARM、Linux AMD64、远端集群。用法：/kind-deploy [local|down|remote REGISTRY=xxx]
---

## 任务

根据参数 `$ARGUMENTS` 执行 Online Boutique 部署操作。

## 参数解析

- 无参数 / `local`：本地 kind 集群完整部署
- `down`：销毁本地 kind 集群和 registry
- `remote REGISTRY=xxx`：部署到远端 K8s 集群（可选 `CONTEXT=xxx`）

## 执行步骤

### local 模式（默认）

执行以下步骤（顺序执行，任一步骤失败则停止）：

1. **检查前置工具**
   ```bash
   make -f Makefile.kind check-prereqs
   ```
   若缺少工具，提示用户安装方式：
   - kind: `brew install kind`（Mac）或 https://kind.sigs.k8s.io/docs/user/quick-start/
   - helm: `brew install helm`
   - kubectl: `brew install kubectl`
   - docker: Docker Desktop for Mac（需 8GB+ 内存配额）

2. **启动本地 Registry 并创建 kind 集群**
   ```bash
   make -f Makefile.kind create-registry create-cluster
   ```

3. **拉取并缓存镜像**（首次约 5-10 分钟，取决于网络）
   ```bash
   make -f Makefile.kind pull-images
   ```

4. **部署可观测性栈**
   ```bash
   make -f Makefile.kind deploy-monitoring
   ```

5. **部署 Online Boutique 微服务**
   ```bash
   make -f Makefile.kind deploy-app
   ```

6. **启动端口转发**
   ```bash
   make -f Makefile.kind port-forward
   ```

7. **显示 Pod 状态**
   ```bash
   make -f Makefile.kind status
   ```

8. 输出访问地址：
   - Frontend: http://localhost:8080
   - Grafana:  http://localhost:3000（用户名/密码：admin/admin）

### down 模式

```bash
make -f Makefile.kind down
```

销毁 kind 集群 `online-boutique` 和本地 registry `kind-registry`，释放端口转发进程。

### remote 模式

从 `$ARGUMENTS` 中解析 `REGISTRY=xxx` 和可选的 `CONTEXT=xxx`，然后执行：
```bash
make -f Makefile.kind deploy-remote REGISTRY=<value> [CONTEXT=<value>]
```

远端模式使用 `--set images.repository=<REGISTRY>` 覆盖镜像仓库，不创建本地 registry。

## 故障排查提示

- **Pod ImagePullBackOff** → 检查 `make -f Makefile.kind pull-images` 是否成功；确认 kind 节点可以访问 `kind-registry:5000`（`docker network connect kind kind-registry`）
- **Pod CrashLoopBackOff** → `kubectl logs -n <namespace> <pod>` 查看详细日志
- **Grafana 无数据** → 等待 2-3 分钟让 otel-collector 开始收集 spanmetrics；检查 `kubectl get pods -n monitoring` 是否全部 Running
- **kind 创建失败** → 确认 Docker Desktop 正在运行且分配了足够内存（建议 8GB+）
- **端口冲突** → 如 8080/3000 已被占用，手动执行 `kubectl port-forward` 指定其他端口
- **镜像拉取超时** → 设置 Docker 代理或使用镜像加速器；或手动执行 `docker pull` 后重试

## 重要说明

- `make -f Makefile.kind up` 是幂等的，重复执行不会重建已存在的资源
- 首次运行约 15-20 分钟（镜像下载 + 集群启动）；后续运行（集群已存在）约 5 分钟
- 所有数据使用 emptyDir（临时存储），Pod 重启后数据丢失
- SRE agent 在 kind 模式下已禁用（需要自定义 `sre-agent:latest` 镜像）
- DingTalk 告警在 kind 模式下未配置（无 token）
- Tempo streaming 已禁用（Tempo 2.5.0 不支持 `/api/search/stream`）
