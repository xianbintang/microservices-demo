REMOTE = root@47.83.217.162
REMOTE_DIR = /opt/obs-stack

.PHONY: deploy logs status down

deploy:
	ssh $(REMOTE) 'mkdir -p $(REMOTE_DIR)/prometheus/rules \
	  $(REMOTE_DIR)/alertmanager \
	  $(REMOTE_DIR)/loki \
	  $(REMOTE_DIR)/tempo \
	  $(REMOTE_DIR)/prometheus-alert \
	  $(REMOTE_DIR)/grafana/provisioning/datasources \
	  $(REMOTE_DIR)/grafana/provisioning/dashboards \
	  $(REMOTE_DIR)/grafana/dashboards'
	rsync -avz --delete --exclude='Makefile' . $(REMOTE):$(REMOTE_DIR)/
	rsync -avz ../monitoring/dashboards/*.json $(REMOTE):$(REMOTE_DIR)/grafana/dashboards/
	ssh $(REMOTE) "cd $(REMOTE_DIR) && docker compose pull && docker compose up -d"

logs:
	ssh $(REMOTE) "cd $(REMOTE_DIR) && docker compose logs -f --tail=50"

status:
	ssh $(REMOTE) "cd $(REMOTE_DIR) && docker compose ps"

down:
	ssh $(REMOTE) "cd $(REMOTE_DIR) && docker compose down"
