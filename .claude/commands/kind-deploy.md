---
description: 一键部署 Online Boutique + kube-prometheus-stack 到远端服务器的 Kind 集群（47.83.217.162），自动对接已运行的可观测栈（Prometheus/Grafana/Loki/Tempo）。用法：/kind-deploy [up|down|status|rollback]
---

## 任务

通过 SSH 连接远端服务器 `47.83.217.162`，使用 `deploy/kind/deploy-remote.sh` 脚本执行 Kind 集群部署操作。

## 参数解析

- 无参数 / `up`：远端 Kind 集群完整部署
- `down`：销毁远端 Kind 集群和 Registry
- `status`：查看远端集群状态
- `rollback`：回滚到上一版本

---

## up 模式（默认）

### 1. 同步代码到远端

```bash
rsync -avz --exclude='.git' --exclude='node_modules' --exclude='.DS_Store' \
  ./ root@47.83.217.162:/opt/microservices-demo/
```

### 2. 执行远端部署脚本

```bash
ssh root@47.83.217.162 'cd /opt/microservices-demo && bash deploy/kind/deploy-remote.sh up'
```

脚本自动执行 7 步：
1. **前置检查**：验证 docker/kind/kubectl/helm 已安装，添加 helm repo
2. **本地 Registry**：在端口 5001 启动 `kind-registry` 容器
3. **Kind 集群**：创建集群，修复 containerd config_path，配置 registry mirror，桥接可观测栈 Docker 网络
4. **镜像准备**：从 Google Registry 拉取 11 个微服务 + redis + busybox + otel-collector-contrib（共 14 个镜像），推送到本地 registry
5. **部署监控**：kube-prometheus-stack（Prometheus remote_write 到可观测栈）
6. **部署应用**：Helm install Online Boutique + TCP probe 补丁 + DISABLE_PROFILER 修复 + NodePort + socat 端口转发
7. **验证**：等待所有 Pod 就绪，输出访问地址

### 3. 访问地址

- Frontend: http://47.83.217.162:9999
- Grafana:  http://47.83.217.162:3000（admin / admin）

---

## down 模式

```bash
ssh root@47.83.217.162 'cd /opt/microservices-demo && bash deploy/kind/deploy-remote.sh down'
```

销毁 Kind 集群、Registry 容器、frontend-proxy systemd 服务。

---

## status 模式

```bash
ssh root@47.83.217.162 'cd /opt/microservices-demo && bash deploy/kind/deploy-remote.sh status'
```

显示集群节点、应用 Pod、监控 Pod、Services、Registry 镜像列表、端口转发状态。

---

## rollback 模式

```bash
ssh root@47.83.217.162 'cd /opt/microservices-demo && bash deploy/kind/deploy-remote.sh rollback'
```

回滚 Helm release 到上一个成功部署版本。

---

## 环境变量

所有参数均可通过环境变量自定义：

```bash
ssh root@47.83.217.162 'cd /opt/microservices-demo && \
  FRONTEND_PORT=8888 LOAD_USERS=20 IMAGE_TAG=v0.10.5 \
  bash deploy/kind/deploy-remote.sh up'
```

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CLUSTER_NAME` | `online-boutique` | Kind 集群名称 |
| `IMAGE_TAG` | `v0.10.4` | 应用镜像版本 |
| `DEPLOY_NS` | `online-boutique` | 应用命名空间 |
| `MONITORING_NS` | `monitoring` | 监控命名空间 |
| `LOAD_USERS` | `10` | 负载生成器并发用户数 |
| `FRONTEND_PORT` | `9999` | 宿主机前端端口 |
| `OBS_NETWORK` | 自动检测 | 可观测栈 Docker 网络名 |
| `SKIP_MONITORING` | `false` | 跳过监控栈部署 |
| `DRY_RUN` | `false` | 仅打印命令不执行 |

---

## 故障排查

| 症状 | 排查步骤 |
|------|---------|
| `another operation in progress` (helm) | SSH 到远端执行 `helm uninstall online-boutique -n online-boutique` 清锁后重试 |
| `ImagePullBackOff` | 检查 containerd config_path 是否配置（脚本会自动修复）；确认 `kind-registry` 在 kind 网络中 |
| `CrashLoopBackOff` | SSH 到远端 `kubectl logs -n online-boutique <pod>` 查看日志；Node.js 服务可能需要 `DISABLE_PROFILER=1` |
| Prometheus 无数据 | 检查 `kubectl get pods -n monitoring` 全部 Running；验证 Kind 节点已加入可观测栈 Docker 网络 |
| Frontend 不可达 | 检查 `systemctl status frontend-proxy`（socat 端口转发服务） |
| 端口冲突 | 通过 `FRONTEND_PORT=其他端口` 环境变量指定其他端口 |

## 重要说明

- 部署脚本幂等：重复运行不会重建已存在的资源
- 远端服务器要求：Docker 20.10+、4 核 CPU、8GB+ 内存、20GB+ 可用磁盘
- 可观测栈（Prometheus/Grafana/Loki/Tempo）通过 Docker Compose 独立运行在同一宿主机
- Kind 集群通过 Docker 网络桥接自动对接可观测栈，使用容器名直连（无需公网 IP 绕行）
- Frontend 通过 NodePort(30080) + socat(systemd service) 暴露到宿主机端口
