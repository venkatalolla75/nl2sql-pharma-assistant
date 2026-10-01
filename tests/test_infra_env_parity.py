"""
Regression test for a real deploy-breaking bug found in this session: the `backend`
service in `infra/docker-compose.aws.yml` (the production compose file, used on the EC2
instance) was missing `SCOPE_ROLE_PASSWORD` entirely — only the `loader` service there
had it, because an earlier edit's search string happened to be unique to the loader
block. Every analytics query failed on the live site with `KeyError: 'SCOPE_ROLE_PASSWORD'`
(app.db.scoped_cursor reads it via `os.environ[...]`), while login/auth (which uses
APP_DB_PASSWORD instead) kept working — a split that made it look like a database/auth
problem rather than a one-line env-var gap in the deploy config.

This runs as a plain text/regex check — no Docker, no YAML parser dependency — comparing
the `backend` service block in the local dev compose file (known-correct, exercised by
every other test in this suite) against the production one, so any var the backend
container actually needs can never again be present in one and missing from the other.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Every env var app.db / app.main actually read via os.environ[...] (required, not
# os.environ.get(...) with a default) for the backend service to function.
REQUIRED_BACKEND_VARS = [
    "POSTGRES_HOST",
    "POSTGRES_DB",
    "APP_DB_PASSWORD",
    "SCOPE_ROLE_PASSWORD",
    "SESSION_SECRET",
]


def _service_block(compose_text: str, service: str) -> str:
    """Returns the text of one top-level service's block (from its `  <service>:` line
    up to the next sibling service or end of file) - good enough for an env-var-name
    presence check without a full YAML parser."""
    pattern = re.compile(rf"^  {re.escape(service)}:\s*$\n(.*?)(?=^  \w+:\s*$|\Z)",
                          re.MULTILINE | re.DOTALL)
    match = pattern.search(compose_text)
    assert match, f"service '{service}' not found in compose file"
    return match.group(1)


# Intentionally local-dev-only: on EC2, boto3 picks up credentials from the IAM instance
# profile (infra/iam.tf's aws_iam_role.ec2) automatically — no explicit keys needed or
# wanted there. A laptop has no instance profile, so local dev passes them explicitly.
LOCAL_ONLY_VARS = {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"}


def test_aws_backend_has_every_var_the_local_backend_has():
    local_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    aws_text = (ROOT / "infra" / "docker-compose.aws.yml").read_text(encoding="utf-8")

    local_backend = _service_block(local_text, "backend")
    aws_backend = _service_block(aws_text, "backend")

    local_vars = set(re.findall(r"^\s+(\w+):\s*\$\{", local_backend, re.MULTILINE))
    aws_vars = set(re.findall(r"^\s+(\w+):\s*\$\{", aws_backend, re.MULTILINE))

    # SESSION_SECRET/APP_DB_PASSWORD/etc. are interpolated in both; APP_ENV/APP_DB_USER
    # are hardcoded literals in the aws file (not ${VAR} interpolated), so compare on the
    # interpolated-var subset both files actually share, plus an explicit required-list
    # check below (belt and suspenders - this is exactly the class of gap that shipped).
    missing_from_aws = local_vars - aws_vars - LOCAL_ONLY_VARS
    assert not missing_from_aws, (
        f"infra/docker-compose.aws.yml's backend service is missing env var(s) "
        f"{missing_from_aws} that docker-compose.yml's backend service has — this is "
        f"the exact class of bug that broke every live analytics query this session "
        f"(SCOPE_ROLE_PASSWORD was present in loader but not backend)."
    )


def test_aws_backend_has_every_required_var():
    aws_text = (ROOT / "infra" / "docker-compose.aws.yml").read_text(encoding="utf-8")
    aws_backend = _service_block(aws_text, "backend")
    for var in REQUIRED_BACKEND_VARS:
        assert re.search(rf"^\s+{var}:", aws_backend, re.MULTILINE), (
            f"infra/docker-compose.aws.yml's backend service is missing required var "
            f"{var!r}"
        )


def test_aws_loader_has_every_required_var():
    aws_text = (ROOT / "infra" / "docker-compose.aws.yml").read_text(encoding="utf-8")
    aws_loader = _service_block(aws_text, "loader")
    for var in ("POSTGRES_HOST", "POSTGRES_PASSWORD", "APP_DB_PASSWORD",
                "SCOPE_ROLE_PASSWORD", "DEMO_USER_PASSWORD"):
        assert re.search(rf"^\s+{var}:", aws_loader, re.MULTILINE), (
            f"infra/docker-compose.aws.yml's loader service is missing required var "
            f"{var!r}"
        )
