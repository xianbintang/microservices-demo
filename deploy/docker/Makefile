REMOTE = root@47.83.217.162
REMOTE_DIR = /opt/obs-stack
GRAFANA_URL ?= http://47.83.217.162:3000

.PHONY: deploy logs status down backup-grafana setup-oncall nuke

deploy:
	ssh $(REMOTE) 'mkdir -p $(REMOTE_DIR)/prometheus \
	  $(REMOTE_DIR)/loki \
	  $(REMOTE_DIR)/tempo \
	  $(REMOTE_DIR)/alarm-service'
	mkdir -p ./alarm-service
	cp ../../src/alarm-service/server.py ./alarm-service/server.py
	cp ../../src/alarm-service/Dockerfile ./alarm-service/Dockerfile
	cp ../../.trae/skills/feishu-messenger/feishu_api.py ./alarm-service/feishu_api.py
	cp ../../.env ./alarm-service/.env
	@echo "==> 部署前自动备份 Grafana（如果正在运行）..."
	-GRAFANA_URL=$(GRAFANA_URL) ./backup-grafana.sh 2>/dev/null || true
	rsync -avz --delete --exclude='Makefile' . $(REMOTE):$(REMOTE_DIR)/
	ssh $(REMOTE) "cd $(REMOTE_DIR) && docker compose pull; cd $(REMOTE_DIR) && docker compose build alarm-service && docker compose up -d"
	@echo ""
	@echo "==> 等待容器启动后初始化 OnCall 插件..."
	ssh $(REMOTE) "cd $(REMOTE_DIR) && bash setup-oncall.sh"

logs:
	ssh $(REMOTE) "cd $(REMOTE_DIR) && docker compose logs -f --tail=50"

status:
	ssh $(REMOTE) "cd $(REMOTE_DIR) && docker compose ps"

# 安全停机：只停容器，不删 volumes，数据保留
down:
	ssh $(REMOTE) "cd $(REMOTE_DIR) && docker compose down"

backup-grafana:
	GRAFANA_URL=$(GRAFANA_URL) ./backup-grafana.sh

setup-oncall:
	ssh $(REMOTE) "cd $(REMOTE_DIR) && bash setup-oncall.sh"

# 危险操作：删除所有容器和数据卷（需要手动输入确认）
nuke:
	@echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
	@echo "  WARNING: 即将删除所有容器 **以及数据卷**"
	@echo "  Grafana dashboards / alert rules / 数据源等将永久丢失"
	@echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
	@read -p "  输入 YES 确认: " confirm && [ "$$confirm" = "YES" ] || (echo "已取消"; exit 1)
	@echo "==> 删除前先备份 Grafana..."
	-GRAFANA_URL=$(GRAFANA_URL) ./backup-grafana.sh 2>/dev/null || true
	ssh $(REMOTE) "cd $(REMOTE_DIR) && docker compose down -v --remove-orphans"
	@echo "==> 已彻底清除。如需恢复，备份在 grafana/backups/ 目录下。"
