# 火山引擎 VKE 部署指南

本文档说明如何将 Online Boutique 微服务应用部署到火山引擎 VKE (容器服务)。

## 📋 前置要求

### 1. 火山引擎账号准备

| 项目 | 说明 | 获取方式 |
|------|------|---------|
| **火山引擎账号** | 已实名认证的账号 | https://console.volcengine.com |
| **容器镜像服务 (CR)** | 用于存储应用镜像 | 控制台 → 容器镜像服务 → 创建实例 |
| **VKE 集群** | Kubernetes 集群 | 控制台 → 容器服务 → 创建集群 |
| **AK/SK** | 访问密钥 (可选) | 控制台 → 访问控制 → 访问密钥 |

### 2. 本地工具安装

```bash
# 检查工具是否已安装
docker --version          # Docker (必需)
kubectl version --client  # kubectl (必需)
helm version              # Helm (推荐)

# macOS 安装方式
brew install docker
brew install kubectl
brew install helm
```

### 3. 获取 kubeconfig

1. 登录火山引擎控制台
2. 进入 **容器服务 VKE** → 选择集群
3. 点击 **集群信息** → **连接信息**
4. 下载 kubeconfig 文件或复制配置

```bash
# 将 kubeconfig 放到默认位置
mkdir -p ~/.kube
cp ~/Downloads/kubeconfig ~/.kube/config

# 验证连接
kubectl cluster-info
```

## 🚀 快速开始

### 步骤 1: 配置环境变量

```bash
# 复制配置模板
cp .env.volc .env.volc.local

# 编辑配置 (修改以下变量)
vim .env.volc.local
```

**必须修改的配置：**

```bash
# 镜像仓库地址 (从火山引擎 CR 获取)
REGISTRY=cr-cn-beijing.volces.com

# 你的命名空间 (火山引擎 CR 中创建的命名空间)
NAMESPACE=your-namespace

# 镜像版本
IMAGE_TAG=v0.10.4
```

### 步骤 2: 获取 CR 访问凭证

1. 登录火山引擎控制台
2. 进入 **容器镜像服务** → **实例** → 选择实例
3. 点击 **访问凭证** → **设置密码**
4. 记录用户名 (通常是你的账号 ID)

```bash
# 登录火山引擎 CR
make -f Makefile.volc login

# 或手动登录
docker login cr-cn-beijing.volces.com
# 输入用户名和密码
```

### 步骤 3: 一键部署

```bash
# 使用 Makefile 一键部署
make -f Makefile.volc all

# 或者分步执行：
make -f Makefile.volc check-env      # 1. 检查环境
make -f Makefile.volc migrate-images # 2. 迁移镜像
make -f Makefile.volc deploy         # 3. 部署应用
```

### 步骤 4: 验证部署

```bash
# 查看部署状态
make -f Makefile.volc status

# 获取前端访问地址
make -f Makefile.volc get-frontend-url

# 输出示例：
# http://123.45.67.89
```

## 📁 文件说明

| 文件 | 说明 |
|------|------|
| `.env.volc` | 环境变量模板 |
| `Makefile.volc` | 部署自动化脚本 |
| `deploy/values-volc.yaml` | Helm values (自动生成) |

## 🔧 常用命令

```bash
# 查看帮助
make -f Makefile.volc help

# 查看部署状态
make -f Makefile.volc status

# 查看日志
make -f Makefile.volc logs

# 端口转发 (本地调试)
make -f Makefile.volc port-forward
# 访问 http://localhost:8080

# 删除部署
make -f Makefile.volc undeploy
```

## 🔍 可观测性部署 (可选)

### 部署 Jaeger (链路追踪)

```bash
make -f Makefile.volc deploy-jaeger
```

### 部署 Prometheus (监控)

```bash
make -f Makefile.volc deploy-prometheus
```

## ⚠️ 注意事项

### 镜像拉取问题

如果使用火山引擎 CR 私有镜像，需要创建 imagePullSecret：

```bash
# 创建 Secret
kubectl create secret docker-registry volc-registry-secret \
  --docker-server=cr-cn-beijing.volces.com \
  --docker-username=<用户名> \
  --docker-password=<密码> \
  -n online-boutique

# 在 Helm values 中添加
# serviceAccounts.annotations: |
#   eks.volcengine.com/image-pull-secrets: volc-registry-secret
```

### LoadBalancer 问题

如果 LoadBalancer IP 一直为空：

1. 检查 VKE 集群是否配置了 CLB
2. 检查子网是否有可用 IP
3. 查看事件: `kubectl describe svc frontend-external -n online-boutique`

### 网络访问

确保安全组/网络 ACL 允许访问：
- 前端端口: 80
- Jaeger UI: 16686 (如部署)
- Prometheus: 9090 (如部署)

## 📊 资源需求

| 服务 | CPU | 内存 |
|------|-----|------|
| frontend | 100m-200m | 64Mi-128Mi |
| cartservice | 200m-300m | 64Mi-128Mi |
| checkoutservice | 100m-200m | 64Mi-128Mi |
| currencyservice | 100m-200m | 128Mi-256Mi |
| emailservice | 100m-200m | 64Mi-128Mi |
| paymentservice | 100m-200m | 64Mi-128Mi |
| productcatalogservice | 100m-200m | 64Mi-128Mi |
| recommendationservice | 100m-200m | 220Mi-450Mi |
| shippingservice | 100m-200m | 64Mi-128Mi |
| adservice | 200m-300m | 180Mi-300Mi |
| loadgenerator | 300m-500m | 256Mi-512Mi |
| redis-cart | 70m-125m | 200Mi-256Mi |

**总计约:** 1.7 CPU, 1.5GB 内存

## 🔗 相关链接

- [火山引擎容器服务文档](https://www.volcengine.com/docs/6460-73580)
- [火山引擎容器镜像服务文档](https://www.volcengine.com/docs/6421-72464)
- [Online Boutique 原项目](https://github.com/GoogleCloudPlatform/microservices-demo)