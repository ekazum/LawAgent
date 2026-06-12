#!/bin/sh
# Runs ON the VM. Extracts the uploaded tarball and (re)starts the stack.
# Secrets come from GCP Secret Manager via the VM's service account.
set -e
cd "$HOME"
mkdir -p lawagent
[ -f lawagent.tar.gz ] && tar xzf lawagent.tar.gz -C lawagent
cd lawagent
sudo ANTHROPIC_API_KEY="$(gcloud secrets versions access latest --secret anthropic-api-key)" \
     APP_USERS="$(gcloud secrets versions access latest --secret app-users)" \
     docker compose --profile cloud up -d --build "$@"

# compose won't recreate caddy when only the bind-mounted Caddyfile content
# changed, so reload it explicitly (fall back to a restart if reload fails).
sudo docker compose --profile cloud exec -T caddy caddy reload --config /etc/caddy/Caddyfile \
    || sudo docker compose --profile cloud restart caddy
