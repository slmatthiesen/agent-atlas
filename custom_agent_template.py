"""
Custom Agent Plugin Template for GCP Enterprise Multi-Agent Platform

Use this template to add your own custom agent microservices to the platform.
Every agent runs under its own dedicated GCP Service Account identity with
strict least-privilege IAM permissions.
"""

import os
import sys
import time
import json
import uuid
import subprocess
from google.cloud import firestore
import google.oauth2.credentials
from google.auth import impersonated_credentials

from gcp_auth import PROJECT_ID  # resolves from GCP_PROJECT or ADC

def get_base_creds():
    """Fetches base credentials from active gcloud environment."""
    token = subprocess.check_output("gcloud auth print-access-token", shell=True, text=True).strip()
    return google.oauth2.credentials.Credentials(token)

def get_agent_credentials(agent_sa_email: str):
    """Impersonates dedicated agent Service Account for IAM Zero-Trust containment."""
    base_creds = get_base_creds()
    return impersonated_credentials.Credentials(
        source_credentials=base_creds,
        target_principal=agent_sa_email,
        target_scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )

def run_custom_agent(task_payload: dict) -> dict:
    """
    Example Custom Agent Implementation:
    1. Impersonate dedicated Service Account
    2. Query authorized GCP resources
    3. Execute business logic & return structured response payload
    """
    sa_email = f"agent-custom@{PROJECT_ID}.iam.gserviceaccount.com"
    creds = get_agent_credentials(sa_email)
    
    # Connect to Firestore under agent-custom identity
    db = firestore.Client(project=PROJECT_ID, credentials=creds)
    
    task_id = f"TASK-{uuid.uuid4().hex[:6].upper()}"
    query_input = task_payload.get("input", "Analyze inventory telemetry")
    
    print(f"[{sa_email}] Processing task {task_id}: {query_input}")
    
    # Return structured resolution payload
    return {
        "status": "COMPLETED",
        "task_id": task_id,
        "agent_identity": sa_email,
        "executed_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "resolution": f"Custom agent processed input: '{query_input}' successfully."
    }

if __name__ == "__main__":
    result = run_custom_agent({"input": "Perform custom compliance check"})
    print(json.dumps(result, indent=2))
