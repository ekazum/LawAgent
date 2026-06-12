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
