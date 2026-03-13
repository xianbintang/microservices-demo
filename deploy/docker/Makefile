REMOTE = root@47.83.217.162
REMOTE_DIR = /opt/obs-stack
GRAFANA_URL ?= http://47.83.217.162:3000

.PHONY: deploy logs status down backup-grafana

deploy:
	ssh $(REMOTE) 'mkdir -p $(REMOTE_DIR)/prometheus/rules \
	  $(REMOTE_DIR)/alertmanager \
	  $(REMOTE_DIR)/loki \
	  $(REMOTE_DIR)/tempo \
	  $(REMOTE_DIR)/prometheus-alert'
	rsync -avz --delete --exclude='Makefile' . $(REMOTE):$(REMOTE_DIR)/
	ssh $(REMOTE) "cd $(REMOTE_DIR) && docker compose pull && docker compose up -d"

logs:
	ssh $(REMOTE) "cd $(REMOTE_DIR) && docker compose logs -f --tail=50"

status:
	ssh $(REMOTE) "cd $(REMOTE_DIR) && docker compose ps"

down:
	ssh $(REMOTE) "cd $(REMOTE_DIR) && docker compose down"

backup-grafana:
	GRAFANA_URL=$(GRAFANA_URL) ./backup-grafana.sh
