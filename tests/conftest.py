"""
Test config. Assumes the local Docker stack's `db` service is up and loaded
(docker compose up -d db && docker compose --profile loader run --rm loader), reachable
at localhost:5432 — i.e. run these against the same environment docker-compose.yml sets
up for local dev. Does NOT require the `backend` container itself: FastAPI's TestClient
runs the app in-process against that same Postgres.
"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "backend"))


def _load_dotenv():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)


_load_dotenv()
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("APP_DB_USER", "app_login")

from starlette.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

DEMO_PASSWORD = os.environ["DEMO_USER_PASSWORD"]

# email -> (role, territory_name, region_name)
USERS = {
    "exec": "sarah.chen@novapharma.com",
    "director_northeast": "jennifer.walsh@novapharma.com",
    "ram_ny_metro": "amy.nguyen@novapharma.com",
    "ram_new_england": "brian.murphy@novapharma.com",
}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def users():
    return dict(USERS)


@pytest.fixture
def login():
    def _login(email: str) -> TestClient:
        c = TestClient(app)
        r = c.post("/login", json={"email": email, "password": DEMO_PASSWORD})
        assert r.status_code == 200, f"login failed for {email}: {r.text}"
        return c

    return _login


def _aws_available() -> bool:
    try:
        import boto3

        boto3.client(
            "sts", region_name=os.environ.get("AWS_REGION", "us-east-1")
        ).get_caller_identity()
        return True
    except Exception:
        return False


AWS_AVAILABLE = _aws_available()
requires_bedrock = pytest.mark.skipif(
    not AWS_AVAILABLE,
    reason="AWS credentials not configured — see PLAN.md blockers. "
           "Run `aws configure` (or `aws sso login`) to enable LLM-dependent tests.",
)


from tests import report as _report  # noqa: E402


@pytest.fixture
def report():
    return _report


_PYTEST_OUTCOMES: list[tuple[str, str]] = []  # (nodeid, outcome)


def pytest_runtest_logreport(report):
    if report.when == "call" or (report.when == "setup" and report.outcome == "skipped"):
        _PYTEST_OUTCOMES.append((report.nodeid, report.outcome))


def pytest_sessionfinish(session, exitstatus):
    out_path = ROOT / "TESTS.md"
    out_path.write_text(
        _report.render_markdown(pytest_outcomes=_PYTEST_OUTCOMES), encoding="utf-8"
    )
    print(f"\nWrote {out_path} ({len(_report.RESULTS)} rich cases, "
          f"{len(_PYTEST_OUTCOMES)} total pytest results)")
