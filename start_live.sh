#!/usr/bin/env bash
# Start the dashboard against a real Google Cloud project with live provisioning armed.
#
#   GCP_PROJECT=your-project-id PROVISIONING_TOKEN=choose-a-secret ./start_live.sh
#
# For the offline example, or a catalog from atlas_init.py, `python dashboard_backend.py` is enough.
set -e
cd "$(dirname "$0")"

: "${GCP_PROJECT:?set GCP_PROJECT to your project id}"
: "${PROVISIONING_TOKEN:?set PROVISIONING_TOKEN to a secret the console must present before it may write}"
export GCP_PROJECT PROVISIONING_TOKEN
export MODEL_ARMOR_TEMPLATE="${MODEL_ARMOR_TEMPLATE:-meridian-agent-armor}"
export ALLOW_LIVE_PROVISIONING="${ALLOW_LIVE_PROVISIONING:-1}"

echo "=================================================="
echo " Starting Live Agent Governance Dashboard"
echo " Project:       $GCP_PROJECT"
echo " Model Armor:   $MODEL_ARMOR_TEMPLATE"
echo " Provisioning:  Armed"
echo " Portal URL:    http://127.0.0.1:8090/"
echo " Console URL:   http://127.0.0.1:8090/console"
echo "=================================================="

python dashboard_backend.py
