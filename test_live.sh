#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

export GCP_PROJECT="${GCP_PROJECT:-gcp-agent-panel}"

echo "=================================================="
echo " Running Live Finance Containment Tests"
echo " Project: $GCP_PROJECT"
echo "=================================================="

python test_finance_containment.py
