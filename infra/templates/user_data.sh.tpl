#!/bin/bash
set -euxo pipefail
exec > >(tee /var/log/user-data.log) 2>&1

# --- Docker + Compose/buildx plugins + git + python3 (Amazon Linux 2023) ---
dnf install -y docker git python3
systemctl enable --now docker
usermod -aG docker ec2-user

# docker-buildx-plugin isn't in the AL2023 repos, so `docker compose build` (which
# shells out to buildx) fails without this — fetch the CLI plugin binary directly,
# same as the compose plugin below.
mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

BUILDX_TAG=$(python3 -c "import json,urllib.request; print(json.load(urllib.request.urlopen('https://api.github.com/repos/docker/buildx/releases/latest'))['tag_name'])")
curl -SL "https://github.com/docker/buildx/releases/download/$${BUILDX_TAG}/buildx-$${BUILDX_TAG}.linux-amd64" \
  -o /usr/local/lib/docker/cli-plugins/docker-buildx
chmod +x /usr/local/lib/docker/cli-plugins/docker-buildx

# --- Fetch app code ---
mkdir -p /opt/app
git clone --branch ${repo_ref} --depth 1 ${repo_url} /opt/app
cd /opt/app

# --- Regenerate the full dataset locally (stdlib-only, deterministic SEED=42) ---
python3 schema/generate_data.py

# --- Runtime config (never committed — written here from Terraform-managed values) ---
cat > /opt/app/.env <<ENVEOF
POSTGRES_HOST=${rds_endpoint}
POSTGRES_PORT=5432
POSTGRES_DB=${db_name}
POSTGRES_USER=${rds_username}
POSTGRES_PASSWORD=${rds_password}
APP_DB_PASSWORD=${app_db_password}
DEMO_USER_PASSWORD=${demo_user_password}
SESSION_SECRET=${session_secret}
AWS_REGION=${aws_region}
BEDROCK_MODEL_ID=${bedrock_model_id}
STATEMENT_TIMEOUT_MS=8000
ENVEOF
chmod 600 /opt/app/.env

# --- Wait for RDS to accept TCP connections ---
until timeout 3 bash -c "cat < /dev/null > /dev/tcp/${rds_endpoint}/5432" 2>/dev/null; do
  echo "waiting for RDS at ${rds_endpoint}:5432 ..."
  sleep 5
done

COMPOSE="docker compose --project-directory /opt/app -f /opt/app/infra/docker-compose.aws.yml --env-file /opt/app/.env"

# --- Load the full dataset into RDS (idempotent-ish: ON CONFLICT DO NOTHING for users;
#     tables are created IF NOT EXISTS, but re-running COPY would duplicate sales rows,
#     so this only runs once per instance via the marker file below) ---
if [ ! -f /opt/app/.data-loaded ]; then
  $COMPOSE run --rm loader
  touch /opt/app/.data-loaded
fi

# --- Start the app ---
$COMPOSE up -d backend

echo "user-data complete"
