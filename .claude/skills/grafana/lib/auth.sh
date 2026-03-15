#!/bin/bash
# Grafana 认证信息

export GRAFANA_URL="${GRAFANA_URL:-http://47.83.217.162:3000}"
export GRAFANA_TOKEN="${GRAFANA_TOKEN:-}"  # 从环境变量读取，不要硬编码
