#!/usr/bin/env bash
set -e

# Change to the script's directory (C:/Projects/steven/gcp)
cd "$(dirname "$0")"

export GCP_PROJECT="${GCP_PROJECT:-gcp-agent-panel}"
export MODEL_ARMOR_TEMPLATE="${MODEL_ARMOR_TEMPLATE:-meridian-agent-armor}"
export ALLOW_LIVE_PROVISIONING="${ALLOW_LIVE_PROVISIONING:-1}"
export PROVISIONING_TOKEN="${PROVISIONING_TOKEN:-steven-live-demo-token}"

echo "=================================================="
echo " Starting Live Agent Governance Dashboard"
echo " Project:       $GCP_PROJECT"
echo " Model Armor:   $MODEL_ARMOR_TEMPLATE"
echo " Provisioning:  Armed (Token: $PROVISIONING_TOKEN)"
echo " Portal URL:    http://127.0.0.1:8090/"
echo " Console URL:   http://127.0.0.1:8090/console"
echo "=================================================="

python dashboard_backend.py
