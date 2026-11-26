#!/usr/bin/env bash
# vllm-model-manager: install OpenViking — long-term memory for Hermes.
#
# Sets up the full local stack:
#   1. OpenViking server (own venv, port 1934)
#   2. CPU embedding service (bge-small-en-v1.5 GGUF via llama.cpp, port 8091)
#   3. systemd user services for both (auto-restart)
#   4. Hermes openviking plugin + memory provider config
#
# Idempotent: existing config files and data are never overwritten.
# Optional args: $1 = VLM api_base (default http://127.0.0.1:8000/v1),
#                $2 = VLM model name (default Qwen3.8)
set -euo pipefail
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

OV_HOME="$HOME/.openviking"
OV_PORT=1934
EMBED_PORT=8091
MODEL_FILE="bge-small-en-v1.5-f16.gguf"
MODEL_URL="https://huggingface.co/CompendiumLabs/bge-small-en-v1.5-gguf/resolve/main/bge-small-en-v1.5-f16.gguf"
VLM_API_BASE="${1:-http://127.0.0.1:8000/v1}"
VLM_MODEL="${2:-Qwen3.8}"

log "=== OpenViking install ==="

# ---------------------------------------------------------------------------
# 1. venv + packages
# ---------------------------------------------------------------------------
mkdir -p "$OV_HOME"
if [ ! -x "$OV_HOME/venv/bin/python" ]; then
  log "Creating venv at $OV_HOME/venv …"
  python3 -m venv "$OV_HOME/venv"
else
  log "Venv already present: $OV_HOME/venv"
fi

log "Installing packages (openviking, openviking-sdk, llama-cpp-python) …"
"$OV_HOME/venv/bin/python" -m pip install openviking openviking-sdk llama-cpp-python
OV_VERSION=$("$OV_HOME/venv/bin/python" -c "import importlib.metadata as m; print(m.version('openviking'))" 2>/dev/null || echo "?")
log "OpenViking server: v$OV_VERSION"

# ---------------------------------------------------------------------------
# 2. Embedding model (bge-small-en-v1.5 f16 GGUF, ~67 MB)
# ---------------------------------------------------------------------------
mkdir -p "$OV_HOME/models"
if [ ! -f "$OV_HOME/models/$MODEL_FILE" ]; then
  log "Downloading embedding model (~67 MB) …"
  curl -fL --retry 3 -o "$OV_HOME/models/$MODEL_FILE.part" "$MODEL_URL"
  mv "$OV_HOME/models/$MODEL_FILE.part" "$OV_HOME/models/$MODEL_FILE"
else
  log "Embedding model present: $MODEL_FILE"
fi

# ---------------------------------------------------------------------------
# 3. Embedding service script (only if absent — never overwrite a tuned one)
# ---------------------------------------------------------------------------
if [ ! -f "$OV_HOME/embed_server.py" ]; then
  log "Writing $OV_HOME/embed_server.py …"
  cp "$(dirname "$0")/templates/embed_server.py" "$OV_HOME/embed_server.py"
else
  log "Embedding service script present (keeping existing)"
fi

# ---------------------------------------------------------------------------
# 4. Server config (only if absent — never overwrite an existing config)
# ---------------------------------------------------------------------------
if [ ! -f "$OV_HOME/ov.conf" ]; then
  log "Writing $OV_HOME/ov.conf …"
  API_KEY=$(openssl rand -hex 16)
  cat > "$OV_HOME/ov.conf" <<EOF
{
  "server": {
    "host": "127.0.0.1",
    "port": $OV_PORT,
    "auth_mode": "trusted",
    "root_api_key": "$API_KEY"
  },
  "storage": {
    "workspace": "$OV_HOME/workspace"
  },
  "embedding": {
    "dense": {
      "provider": "openai",
      "model": "bge-small-en-v1.5",
      "api_key": "***",
      "api_base": "http://127.0.0.1:$EMBED_PORT/v1",
      "dimension": 384
    }
  },
  "vlm": {
    "provider": "openai",
    "model": "$VLM_MODEL",
    "api_key": "***",
    "api_base": "$VLM_API_BASE",
    "temperature": 0.0,
    "max_retries": 2
  }
}
EOF
else
  log "Server config present (keeping existing)"
fi

# ---------------------------------------------------------------------------
# 5. CLI config (only if absent)
# ---------------------------------------------------------------------------
if [ ! -f "$OV_HOME/ovcli.conf" ]; then
  log "Writing $OV_HOME/ovcli.conf …"
  API_KEY=$(python3 -c "import json; print(json.load(open('$OV_HOME/ov.conf'))['server']['root_api_key'])")
  cat > "$OV_HOME/ovcli.conf" <<EOF
{
  "url": "http://127.0.0.1:$OV_PORT",
  "api_key": "***",
  "root_api_key": "$API_KEY",
  "account": "$(whoami)",
  "user": "$(whoami)"
}
EOF
else
  log "CLI config present (keeping existing)"
fi

# ---------------------------------------------------------------------------
# 6. systemd user services (write units only if absent)
# ---------------------------------------------------------------------------
mkdir -p "$HOME/.config/systemd/user"

if [ ! -f "$HOME/.config/systemd/user/openviking-embed.service" ]; then
  log "Writing openviking-embed.service …"
  cat > "$HOME/.config/systemd/user/openviking-embed.service" <<EOF
[Unit]
Description=OpenViking embedding service (bge-small-en-v1.5 GGUF on CPU)
After=network.target

[Service]
ExecStart=$OV_HOME/venv/bin/python3 $OV_HOME/embed_server.py
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF
fi

if [ ! -f "$HOME/.config/systemd/user/openviking-server.service" ]; then
  log "Writing openviking-server.service …"
  cat > "$HOME/.config/systemd/user/openviking-server.service" <<EOF
[Unit]
Description=OpenViking server (context database for AI agents)
After=network.target openviking-embed.service
Wants=openviking-embed.service

[Service]
ExecStart=$OV_HOME/venv/bin/openviking-server --config $OV_HOME/ov.conf
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF
fi

systemctl --user daemon-reload
log "Starting embedding service …"
systemctl --user enable --now openviking-embed.service

log "Waiting for embedding service health …"
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$EMBED_PORT/health" 2>/dev/null | grep -q '"ready": true'; then
    break
  fi
  sleep 2
done
curl -fsS "http://127.0.0.1:$EMBED_PORT/health" >/dev/null || { log "ERROR: embedding service did not become healthy"; exit 1; }
log "Embedding service healthy"

log "Starting OpenViking server …"
systemctl --user enable --now openviking-server.service

log "Waiting for OpenViking server health …"
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$OV_PORT/health" 2>/dev/null | grep -q '"healthy": true'; then
    break
  fi
  sleep 2
done
curl -fsS "http://127.0.0.1:$OV_PORT/health" >/dev/null || { log "ERROR: OpenViking server did not become healthy"; exit 1; }
log "OpenViking server healthy"

# ---------------------------------------------------------------------------
# 7. Hermes integration
# ---------------------------------------------------------------------------
export PATH="$HOME/.local/bin:$HOME/.hermes/bin:$HOME/.hermes/hermes-agent/.hermes/bin:$PATH"
command -v hermes >/dev/null 2>&1 || { log "ERROR: hermes not found — install Hermes first"; exit 1; }

PLUGINS_LIST=$(hermes plugins list 2>/dev/null || true)
if echo "$PLUGINS_LIST" | grep -q 'openviking'; then
  log "Hermes openviking plugin already installed"
else
  log "Installing Hermes openviking plugin …"
  hermes plugins install openviking --enable --yes-deps
fi

# Memory provider env vars (never overwrite existing values)
ENV_FILE="$HOME/.hermes/.env"
touch "$ENV_FILE"
for kv in \
  "OPENVIKING_ENDPOINT=http://127.0.0.1:$OV_PORT" \
  "OPENVIKING_API_KEY=$(python3 -c "import json; print(json.load(open('$OV_HOME/ov.conf'))['server']['root_api_key'])")" \
  "OPENVIKING_ACCOUNT=$(whoami)" \
  "OPENVIKING_USER=$(whoami)"; do
  key="${kv%%=*}"
  if grep -q "^${key}=" "$ENV_FILE"; then
    log "$key already set in .env (keeping existing)"
  else
    echo "$kv" >> "$ENV_FILE"
    log "$key set in .env"
  fi
done

# memory: provider: openviking in config.yaml (line-based edit — keeps comments)
"$OV_HOME/venv/bin/python" - <<'PYEOF'
import pathlib, re
p = pathlib.Path.home() / ".hermes" / "config.yaml"
lines = p.read_text().splitlines()
out = []
i, n = 0, len(lines)
done = False
while i < n:
    line = lines[i]
    if re.match(r'^memory:\s*$', line):
        out.append(line)
        j = i + 1
        found = False
        while j < n:
            if re.match(r'^\S', lines[j]) and not lines[j].lstrip().startswith('#'):
                break  # real top-level key — end of the memory block
            m = re.match(r'^  provider:\s*(\S+)', lines[j])
            if m:
                if m.group(1).strip('"\'') == 'openviking':
                    out.append(lines[j])
                else:
                    out.append('  provider: openviking')
                found = True
                break
            out.append(lines[j])
            j += 1
        if not found:
            out.append('  provider: openviking')
            found = True
            i = j  # j sits at the next top-level key (or EOF) — continue there
        else:
            i = j + 1  # lines[j] was consumed (replaced or kept)
        done = True
        continue
    out.append(line)
    i += 1
if not done:
    out.append('')
    out.append('memory:')
    out.append('  provider: openviking')
    print('added memory: provider: openviking (no memory block found)')
else:
    print('memory provider: openviking')
p.write_text('\n'.join(out) + '\n')
PYEOF

log "=== OpenViking install complete ==="
log "Server: http://127.0.0.1:$OV_PORT  |  Embeddings: http://127.0.0.1:$EMBED_PORT"
log "Restart the Hermes gateway to load the memory provider (button in the UI)."
