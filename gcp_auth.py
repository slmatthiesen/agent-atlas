"""Shared GCP credential helpers.

Credentials are resolved once via Application Default Credentials and cached.
Earlier revisions shelled out to `gcloud auth print-access-token` on every
request, which added ~300ms per call and broke inside containers where the
gcloud CLI is not installed.
"""
import os
import threading

import google.auth
import google.auth.transport.requests
from google.auth import impersonated_credentials

REGION = os.getenv("GCP_REGION", "us-central1")
CLOUD_PLATFORM_SCOPE = ["https://www.googleapis.com/auth/cloud-platform"]

_NO_PROJECT_MESSAGE = """Could not determine which Google Cloud project to use.

Set one explicitly:
    export GCP_PROJECT=your-project-id          # Windows: $env:GCP_PROJECT="your-project-id"

…or make it your Application Default Credentials project:
    gcloud auth application-default login --project=your-project-id

Then provision the demo into it with:
    python bootstrap.py
"""


def _resolve_project_id() -> str:
    """Find the project from the environment, else from Application Default Credentials.

    Deliberately has no built-in default: silently falling back to whichever project the
    author happened to develop against is how someone ends up pointing at a project they
    do not own and getting confusing permission errors.
    """
    explicit = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if explicit:
        return explicit

    try:
        _, adc_project = google.auth.default(scopes=CLOUD_PLATFORM_SCOPE)
    except google.auth.exceptions.DefaultCredentialsError as exc:
        raise RuntimeError(f"{_NO_PROJECT_MESSAGE}\nUnderlying error: {exc}") from exc

    if not adc_project:
        raise RuntimeError(_NO_PROJECT_MESSAGE)
    return adc_project


PROJECT_ID = _resolve_project_id()

_lock = threading.Lock()
_base_creds = None
_impersonated_cache: dict[str, impersonated_credentials.Credentials] = {}


def get_base_credentials():
    """Application Default Credentials, resolved once and reused."""
    global _base_creds
    with _lock:
        if _base_creds is None:
            _base_creds, _ = google.auth.default(scopes=CLOUD_PLATFORM_SCOPE)
        return _base_creds


def get_access_token() -> str:
    """A valid access token for the base identity, refreshed only when expired."""
    creds = get_base_credentials()
    if not creds.valid:
        creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def get_impersonated_credentials(sa_email: str) -> impersonated_credentials.Credentials:
    """Credentials for `sa_email`, impersonated from the base identity.

    Each agent runs under its own service account so that IAM — not application
    logic — is what actually denies out-of-scope access.
    """
    # Resolved before taking the lock: get_base_credentials takes the same lock, and
    # acquiring it twice on one thread deadlocks.
    base = get_base_credentials()
    with _lock:
        if sa_email not in _impersonated_cache:
            _impersonated_cache[sa_email] = impersonated_credentials.Credentials(
                source_credentials=base,
                target_principal=sa_email,
                target_scopes=CLOUD_PLATFORM_SCOPE,
            )
        return _impersonated_cache[sa_email]


def agent_sa(name: str) -> str:
    """Service account email for an agent short name, e.g. 'sales' -> agent-sales@..."""
    return f"agent-{name}@{PROJECT_ID}.iam.gserviceaccount.com"
