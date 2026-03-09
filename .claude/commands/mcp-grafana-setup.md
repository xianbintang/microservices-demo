---
description: 配置 mcp-grafana MCP 服务器，使 Claude 可以直接查询 Grafana 数据源、搜索日志、获取告警等。用法：/mcp-grafana-setup [GRAFANA_URL] [TOKEN]
---

## 任务

配置 mcp-grafana MCP 服务器，创建 Grafana Service Account Token 并写入 `.mcp.json`。

## 参数解析

- 无参数：使用默认配置（`http://localhost:3000`，admin/admin 凭证）
- `GRAFANA_URL`：指定 Grafana 地址（如 `http://grafana.example.com:3000`）
- `TOKEN`：指定已有的 Service Account Token（跳过创建步骤）

---

## 执行步骤

### 1. 检查 Grafana 可访问性

```bash
GRAFANA_URL="${1:-http://localhost:3000}"
curl -s --noproxy localhost -u admin:admin "${GRAFANA_URL}/api/health" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Grafana {d.get(\"version\", \"unknown\")} OK')"
```

若失败，检查：
- 端口转发是否运行（kind 环境）：`kubectl port-forward svc/kube-prometheus-stack-grafana -n monitoring 3000:80 &`
- Grafana Pod 是否 Running：`kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana`

### 2. 创建 Service Account

```bash
# 检查是否已存在
SA_ID=$(curl -s --noproxy localhost -u admin:admin "${GRAFANA_URL}/api/serviceaccounts/search?query=mcp-grafana" | \
  python3 -c "import json,sys; accounts=json.load(sys.stdin).get('serviceAccounts',[]); print(accounts[0]['id'] if accounts else '')")

if [ -n "$SA_ID" ]; then
  echo "Service Account mcp-grafana 已存在 (id=$SA_ID)"
else
  curl -s --noproxy localhost -u admin:admin -X POST \
    "${GRAFANA_URL}/api/serviceaccounts" \
    -H "Content-Type: application/json" \
    -d '{"name": "mcp-grafana", "role": "Admin"}' | \
    python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Created SA id={d[\"id\"]}')"
fi
```

### 3. 创建/获取 Token

```bash
SA_ID=$(curl -s --noproxy localhost -u admin:admin "${GRAFANA_URL}/api/serviceaccounts/search?query=mcp-grafana" | \
  python3 -c "import json,sys; accounts=json.load(sys.stdin).get('serviceAccounts',[]); print(accounts[0]['id'] if accounts else '')")

# 检查已有 token
TOKEN_NAME="mcp-grafana-token"
EXISTING_TOKEN=$(curl -s --noproxy localhost -u admin:admin "${GRAFANA_URL}/api/serviceaccounts/${SA_ID}/tokens" | \
  python3 -c "import json,sys; tokens=json.load(sys.stdin); t=[x for x in tokens if x['name']=='$TOKEN_NAME']; print(t[0]['name'] if t else '')" 2>/dev/null || echo "")

if [ -n "$EXISTING_TOKEN" ]; then
  echo "Token '$TOKEN_NAME' 已存在，需删除后重建"
  curl -s --noproxy localhost -u admin:admin -X DELETE \
    "${GRAFANA_URL}/api/serviceaccounts/${SA_ID}/tokens/$(curl -s --noproxy localhost -u admin:admin "${GRAFANA_URL}/api/serviceaccounts/${SA_ID}/tokens" | python3 -c "import json,sys; tokens=json.load(sys.stdin); t=[x for x in tokens if x['name']=='$TOKEN_NAME']; print(t[0]['id'])")"
fi

# 创建新 token
GRAFANA_TOKEN=$(curl -s --noproxy localhost -u admin:admin -X POST \
  "${GRAFANA_URL}/api/serviceaccounts/${SA_ID}/tokens" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"$TOKEN_NAME\"}" | \
  python3 -c "import json,sys; print(json.load(sys.stdin).get('key',''))")

echo "Token: ${GRAFANA_TOKEN:0:20}..."
```

### 4. 写入 .mcp.json

```bash
cat > .mcp.json << 'MCPJSON'
{
  "mcpServers": {
    "grafana": {
      "command": "uvx",
      "args": ["mcp-grafana"],
      "env": {
        "GRAFANA_URL": "GRAFANA_URL_PLACEHOLDER",
        "GRAFANA_SERVICE_ACCOUNT_TOKEN": "TOKEN_PLACEHOLDER"
      }
    }
  }
}
MCPJSON

# 替换占位符
sed -i '' "s|GRAFANA_URL_PLACEHOLDER|${GRAFANA_URL}|g" .mcp.json
sed -i '' "s|TOKEN_PLACEHOLDER|${GRAFANA_TOKEN}|g" .mcp.json

echo "已写入 .mcp.json"
```

### 5. 加入 .gitignore（如未存在）

```bash
grep -q "^\.mcp\.json" .gitignore 2>/dev/null || echo -e "\n# MCP config (contains tokens)\n.mcp.json" >> .gitignore
echo "已确保 .mcp.json 在 .gitignore 中"
```

### 6. 验证配置

```bash
cat .mcp.json | python3 -c "import json,sys; d=json.load(sys.stdin); print('✅ .mcp.json 配置验证：'); print(f'  GRAFANA_URL: {d[\"mcpServers\"][\"grafana\"][\"env\"][\"GRAFANA_URL\"]}'); print(f'  TOKEN: {d[\"mcpServers\"][\"grafana\"][\"env\"][\"GRAFANA_SERVICE_ACCOUNT_TOKEN\"][:20]}...')"
```

---

## 输出

```
✅ mcp-grafana 配置完成！

配置文件：.mcp.json
Grafana URL：http://localhost:3000
Service Account：mcp-grafana (Admin)

使用方法：
1. 重启 Claude Code 以加载 MCP 服务器
2. 运行 /mcp 查看 Grafana 工具列表
3. 测试：让 Claude 查询 Grafana 数据源或搜索日志
```

---

## 注意事项

- `.mcp.json` 包含敏感 token，已自动加入 `.gitignore`
- Token 具有 Admin 权限，请妥善保管
- 如需重新生成 token，删除旧 token 后重新运行此 skill
- kind 环境需确保端口转发运行中（端口 3000）