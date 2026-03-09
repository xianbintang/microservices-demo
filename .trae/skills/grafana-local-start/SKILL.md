---
name: "grafana-local-start"
description: "Starts or fixes local Grafana access for this repo. Invoke when user asks to start/restart Grafana or reports Grafana page cannot load."
---

# Grafana 本地启动与修复

## 适用场景
- 用户要求“本地启动/重启 Grafana”
- Grafana 页面一直转、静态资源加载失败、ERR_CONNECTION_RESET
- port-forward 频繁断开或端口被占用

## 操作步骤

### 1. 端口与控制面可用性检查
```bash
make -f Makefile.kind port-forward
```

### 2. 可达性验证
```bash
curl -sS -o /dev/null -w "HTTP %{http_code} in %{time_total}s\n" --max-time 5 http://127.0.0.1:3000/login
curl -sS -o /dev/null -w "HTTP %{http_code} in %{time_total}s\n" --max-time 5 http://127.0.0.1:3000/public/build/manifest.json
```

### 3. 若仍失败
```bash
tail -n 50 /tmp/grafana-port-forward.log
kubectl get pod -n monitoring -l app.kubernetes.io/name=grafana
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana --tail=80
```

## 期望结果
- /login 返回 HTTP 200
- /public/build/manifest.json 返回 302
- 浏览器可打开 Grafana 页面

## 访问方式
- 地址: http://localhost:3000
- 账号: admin
- 密码: admin123

