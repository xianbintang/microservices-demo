---
name: "mcp-grafana-setup"
description: "Installs and configures the mcp-grafana MCP server for this repo. Invoke when user asks to set up MCP Grafana or configure .mcp.json."
---

# MCP Grafana 安装与配置

## 适用场景
- 用户要求“安装/配置 mcp-grafana”
- 需要生成或更新 `.mcp.json`

## 执行步骤

### 1. 检查 Grafana 可访问
```bash
curl -sS --noproxy localhost -u admin:admin http://localhost:3000/api/health
```

### 2. 写入 .mcp.json（用户名密码方式）
```bash
cat > .mcp.json << MCPJSON
{
  "mcpServers": {
    "grafana": {
      "command": "mcp-grafana",
      "args": [],
      "env": {
        "GRAFANA_URL": "http://localhost:3000",
        "GRAFANA_USERNAME": "admin",
        "GRAFANA_PASSWORD": "admin",
        "GRAFANA_ORG_ID": "1"
      }
    }
  }
}
MCPJSON
```

### 3. 加入 .gitignore
```bash
grep -q "^\.mcp\.json" .gitignore 2>/dev/null || printf "\n# MCP config (contains secrets)\n.mcp.json\n" >> .gitignore
```

## 验证
```bash
python3 - << 'PY'
import json
with open('.mcp.json') as f:
    d=json.load(f)
print('✅ .mcp.json configured')
print('  GRAFANA_URL:', d['mcpServers']['grafana']['env']['GRAFANA_URL'])
print('  USER:', d['mcpServers']['grafana']['env']['GRAFANA_USERNAME'])
PY
```
