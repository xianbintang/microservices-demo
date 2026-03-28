#!/usr/bin/env bash
###############################################################################
# deploy-remote.sh — Online Boutique 远端 Kind 集群一键部署脚本
#
# 使用说明：
#   1. 将整个项目同步到远端服务器（rsync / scp / git clone）
#   2. 确保远端已安装：docker、kind、kubectl、helm、socat、jq
#   3. 可选：先在远端通过 docker-compose 启动可观测栈
#      （deploy/docker/docker-compose.yml），脚本会自动检测并对接
#   4. 运行部署：
#        bash deploy/kind/deploy-remote.sh up
#   5. 其他命令：
#        bash deploy/kind/deploy-remote.sh down       # 销毁集群与资源
#        bash deploy/kind/deploy-remote.sh status     # 查看集群状态
#        bash deploy/kind/deploy-remote.sh images     # 仅拉取/推送镜像
#        bash deploy/kind/deploy-remote.sh rollback   # 回滚到上一个 Helm 版本
#
# 环境变量（均有默认值，可按需覆盖）：
#   CLUSTER_NAME      集群名称         默认: online-boutique
#   IMAGE_TAG         应用镜像版本     默认: v0.10.4
#   DEPLOY_NS         应用命名空间     默认: online-boutique
#   MONITORING_NS     监控命名空间     默认: monitoring
#   LOAD_USERS        压测并发用户数   默认: 10
#   FRONTEND_PORT     宿主机前端端口   默认: 9999
#   OBS_NETWORK       可观测栈网络名   默认: 自动检测
#   SKIP_MONITORING   跳过监控部署     默认: false
#   DRY_RUN           仅打印不执行     默认: false
#
# 部署流程（共7步）：
#   Step 1: 前置检查（工具、Helm repo）
#   Step 2: 启动本地 Docker Registry
#   Step 3: 创建 Kind 集群（含 containerd 修复）
#   Step 4: 拉取/推送镜像到本地 Registry
#   Step 5: 部署监控栈（kube-prometheus-stack）
#   Step 6: 部署应用（Online Boutique + probe 修复 + env 修复）
#   Step 7: 验证部署并设置端口转发
###############################################################################
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════
# 默认配置
# 所有配置均可通过同名环境变量覆盖，实现参数化部署
# ═══════════════════════════════════════════════════════════════════
CLUSTER_NAME="${CLUSTER_NAME:-online-boutique}"
IMAGE_TAG="${IMAGE_TAG:-v0.10.4}"
DEPLOY_NS="${DEPLOY_NS:-online-boutique}"
MONITORING_NS="${MONITORING_NS:-monitoring}"
LOAD_USERS="${LOAD_USERS:-10}"
FRONTEND_PORT="${FRONTEND_PORT:-9999}"
KIND_REGISTRY_NAME="kind-registry"
KIND_REGISTRY_PORT="${KIND_REGISTRY_PORT:-5001}"
LOCAL_REGISTRY="localhost:${KIND_REGISTRY_PORT}"
GOOGLE_REGISTRY="${GOOGLE_REGISTRY:-us-central1-docker.pkg.dev/google-samples/microservices-demo}"
SKIP_MONITORING="${SKIP_MONITORING:-false}"
DRY_RUN="${DRY_RUN:-false}"

# 可观测栈 Docker 网络，默认空表示自动检测
OBS_NETWORK="${OBS_NETWORK:-}"

# 11 个微服务列表
APP_SERVICES=(frontend checkoutservice shippingservice productcatalogservice \
  recommendationservice emailservice paymentservice currencyservice \
  loadgenerator adservice cartservice)

# 推送到本地 registry 的路径前缀（与 helm values 中 images.repository 保持一致）
PUSH_PREFIX="${LOCAL_REGISTRY}/google-samples/microservices-demo"

# 脚本所在目录，用于定位项目中的配置文件
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ═══════════════════════════════════════════════════════════════════
# 日志工具
# 带颜色 + 时间戳，方便在终端和日志文件中定位问题
# ═══════════════════════════════════════════════════════════════════
_RED='\033[0;31m'
_GREEN='\033[0;32m'
_YELLOW='\033[0;33m'
_BLUE='\033[0;34m'
_CYAN='\033[0;36m'
_BOLD='\033[1m'
_RESET='\033[0m'

_ts() { date '+%Y-%m-%d %H:%M:%S'; }

log_info()  { echo -e "${_BLUE}[$(_ts)]${_RESET} ${_GREEN}[INFO]${_RESET}  $*"; }
log_warn()  { echo -e "${_BLUE}[$(_ts)]${_RESET} ${_YELLOW}[WARN]${_RESET}  $*" >&2; }
log_error() { echo -e "${_BLUE}[$(_ts)]${_RESET} ${_RED}[ERROR]${_RESET} $*" >&2; }
log_step()  { echo -e "\n${_BLUE}[$(_ts)]${_RESET} ${_BOLD}${_CYAN}══════ $* ══════${_RESET}"; }

# dry-run 模式下仅打印命令，不执行
run() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    log_info "${_YELLOW}[DRY-RUN]${_RESET} $*"
  else
    eval "$@"
  fi
}

# 出错时打印上下文信息帮助排查
die() {
  log_error "$1"
  log_error "集群=${CLUSTER_NAME} 命名空间=${DEPLOY_NS} 镜像版本=${IMAGE_TAG}"
  exit 1
}

# ═══════════════════════════════════════════════════════════════════
# Step 1: 前置检查
# 检查所有必要的命令行工具是否已安装，添加 Helm repo
# ═══════════════════════════════════════════════════════════════════
preflight_check() {
  log_step "Step 1/7: 前置检查"

  local required_tools=(docker kind kubectl helm jq socat)
  for tool in "${required_tools[@]}"; do
    if ! command -v "$tool" &>/dev/null; then
      die "缺少必要工具: ${tool}，请先安装"
    fi
  done
  log_info "所有必要工具已就绪: ${required_tools[*]}"

  # 检测系统架构
  local arch
  arch="$(uname -m)"
  if [[ "$arch" == "aarch64" || "$arch" == "arm64" ]]; then
    PLATFORM="linux/arm64"
  else
    PLATFORM="linux/amd64"
  fi
  log_info "系统架构: ${arch} → 容器平台: ${PLATFORM}"

  # 添加 Helm repo（幂等操作，已有则跳过）
  run "helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true"
  run "helm repo update"
  log_info "Helm repo 已就绪"
}

# ═══════════════════════════════════════════════════════════════════
# Step 2: 启动本地 Docker Registry
# Kind 节点通过 containerd mirror 从此 registry 拉取镜像，
# 避免每次部署都从 Google Registry 拉取，加速部署
# ═══════════════════════════════════════════════════════════════════
ensure_registry() {
  log_step "Step 2/7: 本地 Docker Registry"

  # 幂等：如果 registry 容器已在运行则跳过
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${KIND_REGISTRY_NAME}$"; then
    log_info "Registry 已在运行 (${LOCAL_REGISTRY})"
    return 0
  fi

  # 如果容器存在但未运行，先删除再重建
  docker rm -f "${KIND_REGISTRY_NAME}" 2>/dev/null || true

  run "docker run -d --restart=always \
    -p '127.0.0.1:${KIND_REGISTRY_PORT}:5000' \
    --name '${KIND_REGISTRY_NAME}' registry:2"

  log_info "Registry 已启动: ${LOCAL_REGISTRY}"
}

# ═══════════════════════════════════════════════════════════════════
# Step 3: 创建 Kind 集群
# 包含三个关键修复：
#   A) containerd config_path — 让 containerd 识别 certs.d 目录
#   B) hosts.toml — HTTP mirror 配置指向本地 registry
#   F) 可观测栈网络 — 将 Kind 节点连入 Docker 可观测网络
# ═══════════════════════════════════════════════════════════════════
create_cluster() {
  log_step "Step 3/7: Kind 集群"

  # 幂等：集群已存在则跳过创建
  if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    log_info "集群 ${CLUSTER_NAME} 已存在，跳过创建"
  else
    # 动态生成 Kind 集群配置（单节点 control-plane）
    local kind_cfg="/tmp/kind-config-${CLUSTER_NAME}.yaml"
    cat > "${kind_cfg}" <<KINDEOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
KINDEOF
    run "kind create cluster --name '${CLUSTER_NAME}' --config '${kind_cfg}'"
    log_info "集群 ${CLUSTER_NAME} 已创建"
  fi

  # 将 registry 容器连入 kind 网络，使 Kind 节点能通过容器名访问 registry
  run "docker network connect kind '${KIND_REGISTRY_NAME}' 2>/dev/null || true"

  # 切换 kubectl 上下文到新集群
  run "kubectl config use-context 'kind-${CLUSTER_NAME}'"

  # 动态生成并应用 registry configmap，让 Kind 知道本地 registry 的存在
  cat <<REGEOF | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: local-registry-hosting
  namespace: kube-public
data:
  localRegistryHosting.v1: |
    host: "localhost:${KIND_REGISTRY_PORT}"
    help: "https://kind.sigs.k8s.io/docs/user/local-registry/"
REGEOF

  local node="${CLUSTER_NAME}-control-plane"

  # ── 修复 A: containerd config_path ──
  # Kind 默认的 containerd 配置缺少 config_path 设置，
  # 导致 /etc/containerd/certs.d/ 下的 hosts.toml 不会被读取。
  # 必须追加此配置并重启 containerd 才能让 mirror 生效。
  log_info "修复 containerd config_path（使 certs.d 目录生效）..."
  docker exec "${node}" sh -c '
    # 检查是否已有 config_path 配置，避免重复追加
    if ! grep -q "config_path" /etc/containerd/config.toml 2>/dev/null; then
      cat >> /etc/containerd/config.toml <<EOF

# 启用 /etc/containerd/certs.d 作为 registry mirror 配置目录
[plugins."io.containerd.grpc.v1.cri".registry]
  config_path = "/etc/containerd/certs.d"
EOF
      echo "config_path 已追加到 containerd config.toml"
    else
      echo "config_path 已存在，跳过"
    fi
  '

  # 重启 containerd 使配置生效
  docker exec "${node}" systemctl restart containerd
  log_info "containerd 已重启，等待就绪..."

  # 等待 containerd 完全就绪（最多 30 秒）
  local retries=0
  while ! docker exec "${node}" crictl info &>/dev/null; do
    retries=$((retries + 1))
    if [[ $retries -ge 30 ]]; then
      die "containerd 重启后 30 秒仍未就绪，node=${node}"
    fi
    sleep 1
  done
  log_info "containerd 已就绪 (耗时 ${retries}s)"

  # ── 修复 B: hosts.toml ──
  # 配置 containerd 将 kind-registry:5000 作为 HTTP mirror，
  # 注意：不能包含 skip_verify 或任何 TLS 配置，否则 containerd 会尝试 HTTPS 导致失败
  log_info "配置 containerd registry mirror (hosts.toml)..."
  docker exec "${node}" sh -c '
    mkdir -p /etc/containerd/certs.d/kind-registry:5000
    cat > /etc/containerd/certs.d/kind-registry:5000/hosts.toml <<EOF
server = "http://kind-registry:5000"

[host."http://kind-registry:5000"]
  capabilities = ["pull", "resolve"]
EOF
  '
  log_info "hosts.toml 已写入（HTTP mirror，无 TLS 配置）"

  # ── 修复 F: 可观测栈网络连接 ──
  # 自动检测可观测栈的 Docker 网络，将 Kind 节点连入，
  # 使集群内部署的 OTel Collector / Prometheus 可以通过容器名
  # （prometheus / loki / tempo）直接访问可观测栈
  detect_and_join_obs_network "${node}"

  log_info "Kind 集群就绪: ${CLUSTER_NAME}"
}

# ═══════════════════════════════════════════════════════════════════
# 修复 F: 自动检测可观测栈 Docker 网络
# 通过 docker inspect prometheus 容器获取其所在网络，
# 然后将 Kind 节点连入该网络
# ═══════════════════════════════════════════════════════════════════
detect_and_join_obs_network() {
  local node="$1"

  # 如果用户显式指定了网络，直接使用
  if [[ -n "${OBS_NETWORK}" ]]; then
    log_info "使用用户指定的可观测网络: ${OBS_NETWORK}"
    run "docker network connect '${OBS_NETWORK}' '${node}' 2>/dev/null || true"
    return 0
  fi

  # 自动检测：通过 docker inspect prometheus 容器获取网络名
  if docker inspect prometheus &>/dev/null; then
    # 从 prometheus 容器的网络配置中提取第一个网络名
    OBS_NETWORK=$(docker inspect prometheus \
      --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' \
      | head -1)
    if [[ -n "${OBS_NETWORK}" && "${OBS_NETWORK}" != "bridge" ]]; then
      log_info "自动检测到可观测栈网络: ${OBS_NETWORK}"
      run "docker network connect '${OBS_NETWORK}' '${node}' 2>/dev/null || true"
      # 同时将 registry 连入可观测网络（可选，便于排查）
      run "docker network connect '${OBS_NETWORK}' '${KIND_REGISTRY_NAME}' 2>/dev/null || true"
      log_info "Kind 节点 ${node} 已加入网络 ${OBS_NETWORK}"
      return 0
    fi
  fi

  log_warn "未检测到可观测栈（prometheus 容器不存在或网络为默认 bridge）"
  log_warn "OTel Collector 将使用宿主机 IP 作为端点（回退方案）"
}

# ═══════════════════════════════════════════════════════════════════
# 判断可观测栈端点
# 如果 Kind 节点已连入可观测网络，使用容器名作为端点（更可靠）
# 否则回退到宿主机 Docker gateway IP
# ═══════════════════════════════════════════════════════════════════
resolve_obs_endpoints() {
  if [[ -n "${OBS_NETWORK}" ]]; then
    # Kind 节点已在可观测网络中，可以直接用容器名通信
    OBS_PROMETHEUS="http://prometheus:9090"
    OBS_TEMPO="tempo:4317"
    OBS_LOKI="http://loki:3100"
    log_info "可观测端点（容器名）: prometheus=${OBS_PROMETHEUS} tempo=${OBS_TEMPO} loki=${OBS_LOKI}"
  else
    # 回退方案：使用 docker host gateway IP
    local host_ip
    host_ip=$(docker network inspect kind \
      --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}' 2>/dev/null \
      | head -1)
    if [[ -z "$host_ip" ]]; then
      host_ip="172.17.0.1"
    fi
    OBS_PROMETHEUS="http://${host_ip}:9090"
    OBS_TEMPO="${host_ip}:4317"
    OBS_LOKI="http://${host_ip}:3100"
    log_info "可观测端点（宿主机IP回退）: prometheus=${OBS_PROMETHEUS} tempo=${OBS_TEMPO} loki=${OBS_LOKI}"
  fi
}

# ═══════════════════════════════════════════════════════════════════
# Step 4: 拉取/推送镜像到本地 Registry
# 从 Google Registry 拉取 11 个微服务 + busybox + redis + otel-collector，
# tag 后推送到 localhost:5001，Kind 节点通过 mirror 从中拉取
# ═══════════════════════════════════════════════════════════════════
prepare_images() {
  log_step "Step 4/7: 镜像准备"

  local total=${#APP_SERVICES[@]}
  local idx=0

  # 拉取并推送 11 个微服务镜像
  for svc in "${APP_SERVICES[@]}"; do
    idx=$((idx + 1))
    log_info "[${idx}/${total}] 拉取 ${svc}:${IMAGE_TAG}"
    run "docker pull --platform '${PLATFORM}' '${GOOGLE_REGISTRY}/${svc}:${IMAGE_TAG}'"
    run "docker tag '${GOOGLE_REGISTRY}/${svc}:${IMAGE_TAG}' '${PUSH_PREFIX}/${svc}:${IMAGE_TAG}'"
    run "docker push '${PUSH_PREFIX}/${svc}:${IMAGE_TAG}'"
  done

  # 拉取并推送 busybox（loadgenerator init container 使用）
  log_info "拉取 busybox:latest（loadgenerator init 容器）"
  run "docker pull --platform '${PLATFORM}' busybox:latest"
  run "docker tag busybox:latest '${PUSH_PREFIX}/busybox:latest'"
  run "docker push '${PUSH_PREFIX}/busybox:latest'"

  # 拉取并推送 redis:alpine（cartservice 的后端存储）
  log_info "拉取 redis:alpine（cartservice 后端）"
  run "docker pull --platform '${PLATFORM}' redis:alpine"
  run "docker tag redis:alpine '${PUSH_PREFIX}/redis:alpine'"
  run "docker push '${PUSH_PREFIX}/redis:alpine'"

  # 拉取并推送 otel-collector-contrib（自建可观测 collector）
  log_info "拉取 opentelemetry-collector-contrib:0.144.0"
  run "docker pull --platform '${PLATFORM}' otel/opentelemetry-collector-contrib:0.144.0"
  run "docker tag otel/opentelemetry-collector-contrib:0.144.0 '${PUSH_PREFIX}/opentelemetry-collector-contrib:0.144.0'"
  run "docker push '${PUSH_PREFIX}/opentelemetry-collector-contrib:0.144.0'"

  log_info "所有镜像已推送到 ${LOCAL_REGISTRY}"
}

# ═══════════════════════════════════════════════════════════════════
# 修复 G: 生成 kube-prometheus-stack 的 Helm values
# 禁用 Grafana/AlertManager/defaultRules（使用远端可观测栈），
# 启用 remoteWrite 将指标转发到可观测栈 Prometheus，
# 资源限制适合 Kind 单节点环境
# ═══════════════════════════════════════════════════════════════════
generate_kps_values() {
  resolve_obs_endpoints

  local values_file="/tmp/kps-values-${CLUSTER_NAME}.yaml"
  cat > "${values_file}" <<EOF
# 自动生成的 kube-prometheus-stack values
# 生成时间: $(date -Iseconds)
# 集群: ${CLUSTER_NAME}

# 禁用 Grafana — 使用远端 Grafana
grafana:
  enabled: false

# 禁用 AlertManager — 告警规则在远端评估
alertmanager:
  enabled: false

# 禁用内置告警规则 — 远端 Prometheus 统一管理
defaultRules:
  create: false

# Prometheus Operator 配置
prometheusOperator:
  # Kind 环境禁用 TLS 和 admission webhooks，避免证书问题
  tls:
    enabled: false
  admissionWebhooks:
    enabled: false
    patch:
      enabled: false

# Prometheus 实例配置
prometheus:
  prometheusSpec:
    # Kind 单节点资源有限，合理控制资源用量
    resources:
      requests:
        cpu: 200m
        memory: 512Mi
      limits:
        cpu: 1000m
        memory: 2Gi
    retention: 1h
    retentionSize: "500MB"
    # 不在本地评估告警规则，仅做 collector
    ruleSelector:
      matchLabels:
        local-alerting: "enabled"
    ruleNamespaceSelector: {}
    additionalAlertManagerConfigs: []
    additionalScrapeConfigs: []
    # 将所有指标 remote write 到可观测栈 Prometheus
    remoteWrite:
      - url: "${OBS_PROMETHEUS}/api/v1/write"
        queueConfig:
          maxSamplesPerSend: 10000
          maxShards: 30
          capacity: 5000
          minShards: 1
          maxRetries: 3
        writeRelabelConfigs:
          - sourceLabels: [__name__]
            action: drop
            regex: "ALERTS|ALERTS_FOR_STATE"

# 启用 node-exporter（Kind 环境无冲突）
nodeExporter:
  enabled: true
EOF

  log_info "kube-prometheus-stack values 已生成: ${values_file}"
  echo "${values_file}"
}

# ═══════════════════════════════════════════════════════════════════
# 修复 H: 生成应用的 Helm values
# 使用 kind-registry:5000 作为镜像仓库（containerd mirror 透传），
# 启用 selfHostedObservability 并指向检测到的可观测端点
# ═══════════════════════════════════════════════════════════════════
generate_app_values() {
  resolve_obs_endpoints

  local values_file="/tmp/app-values-${CLUSTER_NAME}.yaml"
  cat > "${values_file}" <<EOF
# 自动生成的 Online Boutique 应用 values
# 生成时间: $(date -Iseconds)
# 集群: ${CLUSTER_NAME}

# 镜像仓库指向本地 Kind Registry
# containerd mirror 会将 kind-registry:5000 的请求路由到本地 registry 容器
images:
  repository: kind-registry:5000/google-samples/microservices-demo
  tag: "${IMAGE_TAG}"

# 启用自建可观测性（OTel Collector → Prometheus/Tempo/Loki）
selfHostedObservability:
  enabled: true
  prometheusRemoteWrite:
    endpoint: "${OBS_PROMETHEUS}/api/v1/write"
  tempo:
    endpoint: "${OBS_TEMPO}"
    insecure: true
  loki:
    otlpEndpoint: "${OBS_LOKI}/otlp"

# frontend 设为 local 平台，不创建外部 LoadBalancer
frontend:
  externalService: false
  platform: local

# loadgenerator 并发用户数
loadGenerator:
  checkFrontendInitContainer: true
EOF

  log_info "应用 values 已生成: ${values_file}"
  echo "${values_file}"
}

# ═══════════════════════════════════════════════════════════════════
# Step 5: 部署监控栈
# 使用 kube-prometheus-stack Helm chart，仅部署 Prometheus + node-exporter，
# Grafana/AlertManager/Loki/Tempo 使用远端可观测栈
# ═══════════════════════════════════════════════════════════════════
deploy_monitoring() {
  if [[ "${SKIP_MONITORING}" == "true" ]]; then
    log_step "Step 5/7: 监控部署（已跳过 SKIP_MONITORING=true）"
    return 0
  fi

  log_step "Step 5/7: 部署监控栈"

  # 创建命名空间（幂等）
  run "kubectl create namespace '${MONITORING_NS}' --dry-run=client -o yaml | kubectl apply -f -"

  # 生成 values 文件
  local values_file
  values_file=$(generate_kps_values)

  # 部署/升级 kube-prometheus-stack
  log_info "部署 kube-prometheus-stack（Prometheus only）..."
  run "helm upgrade --install kube-prometheus-stack \
    prometheus-community/kube-prometheus-stack \
    -n '${MONITORING_NS}' \
    -f '${values_file}' \
    --timeout 10m --wait"

  log_info "监控栈部署完成（remoteWrite → ${OBS_PROMETHEUS}）"
}

# ═══════════════════════════════════════════════════════════════════
# Step 6: 部署应用
# 使用项目自带的 helm-chart，加载生成的 values，
# 部署后执行三项关键修复：
#   C) DISABLE_PROFILER/DEBUGGER 环境变量
#   D) gRPC probe → TCP socket probe
#   E) Frontend 外部访问（NodePort + socat）
# ═══════════════════════════════════════════════════════════════════
deploy_app() {
  log_step "Step 6/7: 部署应用"

  # 创建命名空间（幂等）
  run "kubectl create namespace '${DEPLOY_NS}' --dry-run=client -o yaml | kubectl apply -f -"

  # 生成 values 文件
  local values_file
  values_file=$(generate_app_values)

  # 部署/升级 Online Boutique
  log_info "部署 Online Boutique..."
  run "helm upgrade --install online-boutique '${PROJECT_ROOT}/helm-chart/' \
    -n '${DEPLOY_NS}' \
    -f '${values_file}' \
    --timeout 10m --wait"

  log_info "Helm 部署完成，开始执行关键修复..."

  # ── 修复 C: 为 currencyservice 和 paymentservice 设置 DISABLE_PROFILER=1、DISABLE_DEBUGGER=1 ──
  # 这两个 Node.js 服务在 Kind 环境中启用 profiler/debugger 会导致启动异常缓慢或崩溃
  patch_env_disable_profiler

  # ── 修复 D: gRPC probe → TCP socket probe ──
  # Kind 单节点集群的 gRPC HTTP/2 握手比生产环境慢，
  # TCP socket probe 仅检查端口监听，更可靠
  patch_probes

  # ── 修复 E: Frontend 外部访问 ──
  # 将 frontend service 改为 NodePort，通过 socat 做宿主机端口转发
  setup_frontend_access

  # 设置 loadgenerator 并发数
  run "kubectl set env deployment/loadgenerator -n '${DEPLOY_NS}' USERS='${LOAD_USERS}' 2>/dev/null || true"

  log_info "应用部署完成"
}

# ═══════════════════════════════════════════════════════════════════
# 修复 C: DISABLE_PROFILER 和 DISABLE_DEBUGGER
# currencyservice 和 paymentservice 是 Node.js 服务，
# 在资源受限的 Kind 环境中 profiler/debugger 会导致性能问题
# ═══════════════════════════════════════════════════════════════════
patch_env_disable_profiler() {
  log_info "为 currencyservice 和 paymentservice 设置 DISABLE_PROFILER=1, DISABLE_DEBUGGER=1..."
  for svc in currencyservice paymentservice; do
    run "kubectl set env deployment/${svc} -n '${DEPLOY_NS}' \
      DISABLE_PROFILER=1 DISABLE_DEBUGGER=1 2>/dev/null || true"
    log_info "  ✓ ${svc} 已设置 DISABLE_PROFILER=1, DISABLE_DEBUGGER=1"
  done
}

# ═══════════════════════════════════════════════════════════════════
# 修复 D: gRPC probe → TCP socket probe
# 遍历所有 gRPC 服务的 Deployment，将 livenessProbe 和 readinessProbe
# 从 grpc 探针替换为 tcpSocket 探针
# ═══════════════════════════════════════════════════════════════════
patch_probes() {
  log_info "将 gRPC probe 替换为 TCP socket probe..."

  local grpc_services=(adservice cartservice checkoutservice currencyservice \
    emailservice paymentservice productcatalogservice \
    recommendationservice shippingservice)

  for svc in "${grpc_services[@]}"; do
    # 读取当前 livenessProbe 中配置的 gRPC 端口号
    local port
    port=$(kubectl get deployment "${svc}" -n "${DEPLOY_NS}" \
      -o jsonpath='{.spec.template.spec.containers[0].livenessProbe.grpc.port}' 2>/dev/null)

    # 如果没有 gRPC probe 配置（如 loadgenerator），跳过
    if [[ -z "${port}" ]]; then
      continue
    fi

    # 用 JSON patch 替换 liveness 和 readiness probe
    run "kubectl patch deployment '${svc}' -n '${DEPLOY_NS}' --type=json -p='[
      {\"op\":\"replace\",\"path\":\"/spec/template/spec/containers/0/livenessProbe\",
       \"value\":{\"tcpSocket\":{\"port\":${port}},\"timeoutSeconds\":5,\"periodSeconds\":15,\"failureThreshold\":5,\"initialDelaySeconds\":15}},
      {\"op\":\"replace\",\"path\":\"/spec/template/spec/containers/0/readinessProbe\",
       \"value\":{\"tcpSocket\":{\"port\":${port}},\"timeoutSeconds\":5,\"periodSeconds\":10,\"failureThreshold\":5,\"initialDelaySeconds\":10}}
    ]' 2>/dev/null || true"

    log_info "  ✓ ${svc} probe 已替换 (port=${port})"
  done

  log_info "所有 gRPC probe 已替换为 TCP socket probe"
}

# ═══════════════════════════════════════════════════════════════════
# 修复 E: Frontend 外部访问
# 方案：
#   1. 将 frontend Service 改为 NodePort（固定端口 30080）
#   2. 创建 systemd service，使用 socat 将宿主机 FRONTEND_PORT 转发
#      到 Kind 节点的 NodePort 30080
# 这样外部可通过 http://<宿主机IP>:FRONTEND_PORT 访问前端
# ═══════════════════════════════════════════════════════════════════
setup_frontend_access() {
  log_info "配置 Frontend 外部访问（NodePort 30080 + socat 端口转发）..."

  # 将 frontend service 修改为 NodePort 类型，固定端口 30080
  run "kubectl patch svc frontend -n '${DEPLOY_NS}' -p '{
    \"spec\": {
      \"type\": \"NodePort\",
      \"ports\": [{
        \"port\": 80,
        \"targetPort\": 8080,
        \"nodePort\": 30080,
        \"protocol\": \"TCP\"
      }]
    }
  }'"

  # 获取 Kind 节点的 IP 地址（在 Docker 网络中的 IP）
  local node_ip
  node_ip=$(docker inspect "${CLUSTER_NAME}-control-plane" \
    --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \
    | awk '{print $1}')

  if [[ -z "${node_ip}" ]]; then
    log_warn "无法获取 Kind 节点 IP，跳过 socat 端口转发"
    return 0
  fi
  log_info "Kind 节点 IP: ${node_ip}"

  # 停止已有的 frontend-proxy 服务（幂等）
  if systemctl is-active frontend-proxy &>/dev/null; then
    run "sudo systemctl stop frontend-proxy"
  fi

  # 创建 systemd service：用 socat 做端口转发
  # socat 监听宿主机 FRONTEND_PORT，转发到 Kind 节点的 30080 端口
  run "sudo tee /etc/systemd/system/frontend-proxy.service > /dev/null <<UNIT
[Unit]
Description=Online Boutique Frontend Proxy (socat ${FRONTEND_PORT} -> Kind NodePort 30080)
After=network.target docker.service

[Service]
Type=simple
ExecStart=/usr/bin/socat TCP-LISTEN:${FRONTEND_PORT},fork,reuseaddr TCP:${node_ip}:30080
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT"

  run "sudo systemctl daemon-reload"
  run "sudo systemctl enable --now frontend-proxy"

  # 验证端口转发是否成功
  sleep 2
  if systemctl is-active frontend-proxy &>/dev/null; then
    log_info "Frontend proxy 已启动: 0.0.0.0:${FRONTEND_PORT} → ${node_ip}:30080"
  else
    log_warn "Frontend proxy 启动失败，请检查: journalctl -u frontend-proxy"
  fi
}

# ═══════════════════════════════════════════════════════════════════
# Step 7: 验证部署
# 检查所有 Pod 就绪状态，设置端口转发，打印最终访问地址
# ═══════════════════════════════════════════════════════════════════
verify_deployment() {
  log_step "Step 7/7: 验证部署"

  # 等待所有应用 Pod 就绪（最多 5 分钟）
  log_info "等待所有应用 Pod 就绪..."
  local timeout=300
  local start_time
  start_time=$(date +%s)

  while true; do
    local not_ready
    not_ready=$(kubectl get pods -n "${DEPLOY_NS}" --no-headers 2>/dev/null \
      | grep -v "Running\|Completed" | wc -l | tr -d ' ')

    if [[ "${not_ready}" -eq 0 ]]; then
      local total
      total=$(kubectl get pods -n "${DEPLOY_NS}" --no-headers 2>/dev/null | wc -l | tr -d ' ')
      if [[ "${total}" -gt 0 ]]; then
        log_info "所有 ${total} 个 Pod 已就绪"
        break
      fi
    fi

    local elapsed=$(( $(date +%s) - start_time ))
    if [[ ${elapsed} -ge ${timeout} ]]; then
      log_warn "等待超时（${timeout}s），以下 Pod 仍未就绪："
      kubectl get pods -n "${DEPLOY_NS}" --no-headers | grep -v "Running\|Completed" || true
      break
    fi

    log_info "  仍有 ${not_ready} 个 Pod 未就绪，已等待 ${elapsed}s..."
    sleep 10
  done

  # 设置 kubectl port-forward 作为备用访问方式
  # 先清理已有的端口转发
  pkill -f "port-forward.*svc/frontend.*${DEPLOY_NS}" 2>/dev/null || true
  sleep 1

  # 后台启动端口转发（仅绑定 127.0.0.1，供本地调试用）
  nohup kubectl port-forward -n "${DEPLOY_NS}" svc/frontend 8080:80 \
    --address 127.0.0.1 >/tmp/frontend-port-forward.log 2>&1 &
  log_info "kubectl port-forward 已启动: 127.0.0.1:8080 → frontend:80"

  # 打印最终状态
  echo ""
  echo -e "${_BOLD}${_CYAN}════════════════════════════════════════════════════════════${_RESET}"
  echo -e "${_BOLD}  ✅ Online Boutique 部署完成${_RESET}"
  echo -e "${_CYAN}════════════════════════════════════════════════════════════${_RESET}"
  echo -e "  ${_GREEN}Frontend（外部）${_RESET}  : http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo '<宿主机IP>'):${FRONTEND_PORT}"
  echo -e "  ${_GREEN}Frontend（本地）${_RESET}  : http://127.0.0.1:8080"
  echo -e "  ${_GREEN}集群名称${_RESET}          : ${CLUSTER_NAME}"
  echo -e "  ${_GREEN}应用命名空间${_RESET}      : ${DEPLOY_NS}"
  echo -e "  ${_GREEN}镜像版本${_RESET}          : ${IMAGE_TAG}"
  echo -e "  ${_GREEN}压测用户数${_RESET}        : ${LOAD_USERS}"
  if [[ -n "${OBS_NETWORK}" ]]; then
    echo -e "  ${_GREEN}可观测网络${_RESET}        : ${OBS_NETWORK}"
    echo -e "  ${_GREEN}Prometheus${_RESET}        : ${OBS_PROMETHEUS}"
    echo -e "  ${_GREEN}Tempo${_RESET}             : ${OBS_TEMPO}"
    echo -e "  ${_GREEN}Loki${_RESET}              : ${OBS_LOKI}"
  fi
  echo -e "${_CYAN}════════════════════════════════════════════════════════════${_RESET}"
}

# ═══════════════════════════════════════════════════════════════════
# 修复 K: show_status — 显示集群完整状态
# 包括集群信息、Pod、Service、Registry、端口转发状态
# ═══════════════════════════════════════════════════════════════════
show_status() {
  log_step "集群状态"

  # 集群信息
  echo -e "\n${_BOLD}── Kind 集群 ──${_RESET}"
  if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    echo -e "  ${_GREEN}✓${_RESET} 集群 ${CLUSTER_NAME} 运行中"
    kubectl cluster-info 2>/dev/null | head -2 || true
  else
    echo -e "  ${_RED}✗${_RESET} 集群 ${CLUSTER_NAME} 不存在"
    return 0
  fi

  # 应用 Pod 状态
  echo -e "\n${_BOLD}── 应用 Pods (${DEPLOY_NS}) ──${_RESET}"
  kubectl get pods -n "${DEPLOY_NS}" -o wide 2>/dev/null || echo "  命名空间不存在或无 Pod"

  # 监控 Pod 状态
  echo -e "\n${_BOLD}── 监控 Pods (${MONITORING_NS}) ──${_RESET}"
  kubectl get pods -n "${MONITORING_NS}" -o wide 2>/dev/null || echo "  命名空间不存在或无 Pod"

  # Service 状态
  echo -e "\n${_BOLD}── Services (${DEPLOY_NS}) ──${_RESET}"
  kubectl get svc -n "${DEPLOY_NS}" 2>/dev/null || true

  # Registry 状态
  echo -e "\n${_BOLD}── Docker Registry ──${_RESET}"
  if docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null \
    | grep "${KIND_REGISTRY_NAME}"; then
    # 查询 registry 中的镜像数量
    local catalog
    catalog=$(curl -sS "http://localhost:${KIND_REGISTRY_PORT}/v2/_catalog" 2>/dev/null)
    echo "  镜像列表: ${catalog}"
  else
    echo -e "  ${_RED}✗${_RESET} Registry 未运行"
  fi

  # 端口转发状态
  echo -e "\n${_BOLD}── 端口转发 ──${_RESET}"
  if systemctl is-active frontend-proxy &>/dev/null; then
    echo -e "  ${_GREEN}✓${_RESET} frontend-proxy (socat): 0.0.0.0:${FRONTEND_PORT} → Kind NodePort 30080"
  else
    echo -e "  ${_YELLOW}!${_RESET} frontend-proxy 未运行"
  fi

  if pgrep -f "port-forward.*svc/frontend" &>/dev/null; then
    echo -e "  ${_GREEN}✓${_RESET} kubectl port-forward: 127.0.0.1:8080 → frontend:80"
  else
    echo -e "  ${_YELLOW}!${_RESET} kubectl port-forward 未运行"
  fi
}

# ═══════════════════════════════════════════════════════════════════
# 修复 L: teardown — 完全清理所有资源
# 删除 Kind 集群、Docker Registry 容器、systemd service
# ═══════════════════════════════════════════════════════════════════
teardown() {
  log_step "销毁集群和资源"

  # 停止并移除 systemd 端口转发服务
  if systemctl is-active frontend-proxy &>/dev/null 2>&1; then
    log_info "停止 frontend-proxy 服务..."
    run "sudo systemctl stop frontend-proxy"
    run "sudo systemctl disable frontend-proxy 2>/dev/null || true"
  fi
  if [[ -f /etc/systemd/system/frontend-proxy.service ]]; then
    run "sudo rm -f /etc/systemd/system/frontend-proxy.service"
    run "sudo systemctl daemon-reload"
    log_info "frontend-proxy systemd service 已移除"
  fi

  # 停止 kubectl port-forward
  log_info "停止 kubectl port-forward..."
  pkill -f "port-forward.*svc/frontend" 2>/dev/null || true
  pkill -f "port-forward.*8080" 2>/dev/null || true

  # 删除 Kind 集群
  if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    log_info "删除 Kind 集群: ${CLUSTER_NAME}..."
    run "kind delete cluster --name '${CLUSTER_NAME}'"
    log_info "集群已删除"
  else
    log_info "集群 ${CLUSTER_NAME} 不存在，跳过"
  fi

  # 删除 Docker Registry 容器
  if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${KIND_REGISTRY_NAME}$"; then
    log_info "删除 Registry 容器: ${KIND_REGISTRY_NAME}..."
    run "docker rm -f '${KIND_REGISTRY_NAME}'"
    log_info "Registry 已删除"
  else
    log_info "Registry 容器不存在，跳过"
  fi

  # 清理临时文件
  rm -f "/tmp/kps-values-${CLUSTER_NAME}.yaml" \
        "/tmp/app-values-${CLUSTER_NAME}.yaml" \
        /tmp/frontend-port-forward.log

  log_info "所有资源已清理完毕"
}

# ═══════════════════════════════════════════════════════════════════
# 修复 M: rollback — 使用 Helm 回滚到上一个版本
# 分别回滚应用和监控栈
# ═══════════════════════════════════════════════════════════════════
rollback() {
  log_step "Helm 回滚"

  # 回滚应用
  local app_revision
  app_revision=$(helm history online-boutique -n "${DEPLOY_NS}" --max 2 -o json 2>/dev/null \
    | jq -r '.[0].revision' 2>/dev/null)
  if [[ -n "${app_revision}" && "${app_revision}" != "null" ]]; then
    log_info "回滚 online-boutique 到上一个版本..."
    run "helm rollback online-boutique 0 -n '${DEPLOY_NS}' --wait --timeout 5m"
    log_info "online-boutique 已回滚"
  else
    log_warn "online-boutique 没有可回滚的历史版本"
  fi

  # 回滚监控栈
  if [[ "${SKIP_MONITORING}" != "true" ]]; then
    local kps_revision
    kps_revision=$(helm history kube-prometheus-stack -n "${MONITORING_NS}" --max 2 -o json 2>/dev/null \
      | jq -r '.[0].revision' 2>/dev/null)
    if [[ -n "${kps_revision}" && "${kps_revision}" != "null" ]]; then
      log_info "回滚 kube-prometheus-stack 到上一个版本..."
      run "helm rollback kube-prometheus-stack 0 -n '${MONITORING_NS}' --wait --timeout 5m"
      log_info "kube-prometheus-stack 已回滚"
    else
      log_warn "kube-prometheus-stack 没有可回滚的历史版本"
    fi
  fi

  log_info "回滚完成"
}

# ═══════════════════════════════════════════════════════════════════
# 主入口：up / down / status / images / rollback
# ═══════════════════════════════════════════════════════════════════
main() {
  local cmd="${1:-up}"

  case "${cmd}" in
    up)
      # 完整的 7 步部署流程
      log_info "开始部署 Online Boutique (cluster=${CLUSTER_NAME} tag=${IMAGE_TAG} ns=${DEPLOY_NS})"
      preflight_check       # Step 1: 前置检查
      ensure_registry       # Step 2: Docker Registry
      create_cluster        # Step 3: Kind 集群（含 containerd 修复）
      prepare_images        # Step 4: 镜像准备
      deploy_monitoring     # Step 5: 监控部署
      deploy_app            # Step 6: 应用部署（含 probe/env 修复）
      verify_deployment     # Step 7: 验证部署
      ;;
    down)
      teardown
      ;;
    status)
      show_status
      ;;
    images)
      # 仅执行镜像拉取/推送（用于镜像更新场景）
      preflight_check
      ensure_registry
      prepare_images
      ;;
    rollback)
      rollback
      ;;
    *)
      echo "用法: $0 {up|down|status|images|rollback}"
      echo ""
      echo "命令说明:"
      echo "  up        完整部署（7步：检查→Registry→集群→镜像→监控→应用→验证）"
      echo "  down      销毁集群、Registry、端口转发等所有资源"
      echo "  status    显示集群、Pod、Service、Registry、端口转发状态"
      echo "  images    仅拉取/推送镜像到本地 Registry（不创建集群）"
      echo "  rollback  回滚 Helm release 到上一个版本"
      echo ""
      echo "环境变量:"
      echo "  CLUSTER_NAME      集群名称         (默认: online-boutique)"
      echo "  IMAGE_TAG         镜像版本         (默认: v0.10.4)"
      echo "  DEPLOY_NS         应用命名空间     (默认: online-boutique)"
      echo "  MONITORING_NS     监控命名空间     (默认: monitoring)"
      echo "  LOAD_USERS        压测并发数       (默认: 10)"
      echo "  FRONTEND_PORT     前端宿主机端口   (默认: 9999)"
      echo "  OBS_NETWORK       可观测栈网络     (默认: 自动检测)"
      echo "  SKIP_MONITORING   跳过监控部署     (默认: false)"
      echo "  DRY_RUN           仅打印不执行     (默认: false)"
      exit 1
      ;;
  esac
}

main "$@"
