#!/usr/bin/env bash
# Runs on the server as the `deploy` user, after the workflow has synced files.
#
# Lives here rather than on the server so it is versioned and reviewable: the
# deployment steps are code, not commands somebody typed over SSH once.
#
# `deploy` may sudo exactly two things -- restart the API and reload nginx --
# so a leaked CI key cannot do anything else on the box.
set -euo pipefail

APP=/opt/aspire
export PYTHONDONTWRITEBYTECODE=1
# The default 4MB work_mem made the payer census sort spill to disk hundreds of
# times, and disk is this box's binding constraint.
export PGOPTIONS="-c work_mem=256MB -c maintenance_work_mem=512MB"

# DATABASE_URL lives here, readable through the aspire group. The password was
# generated on the server and exists nowhere else -- not in the repo, not in CI.
set -a
# shellcheck disable=SC1091
. /etc/aspire/api.env
set +a

echo "==> syncing dependencies"
# Without this, adding a package to requirements.txt deploys cleanly and then the
# API crashes on import. The frontend's npm ci runs in CI; this is its counterpart.
"$APP/venv/bin/pip" install -q --disable-pip-version-check \
    -r "$APP/backend/requirements.txt" \
    -r "$APP/sandbox-data/requirements.txt"

echo "==> migrating"
# This has to succeed before the new code serves traffic: the API refuses to
# start against a database behind its schema, and a database ahead of the code
# breaks it the same way. Failing here leaves the old version running.
cd "$APP/sandbox-data"
"$APP/venv/bin/python" manage.py upgrade

echo "==> restarting the API"
sudo -n /usr/bin/systemctl restart aspire-api.service

echo "==> waiting for readiness"
for attempt in $(seq 1 30); do
    if curl -fsS --max-time 5 http://127.0.0.1:8000/api/v1/ready > /dev/null 2>&1; then
        echo "ready after ${attempt}s"
        exit 0
    fi
    sleep 1
done

echo "the API did not become ready within 30s" >&2
systemctl status aspire-api.service --no-pager --lines=20 >&2 || true
exit 1
