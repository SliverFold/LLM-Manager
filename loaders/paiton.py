"""Paiton loader — serve Paiton release models on the R9700 via the repo's Docker launchers.

Paiton is a plugin + per-model release servers tuned for the Radeon AI PRO R9700.
Each chat/LLM model in the paiton-vllm-plugin repo has a Docker launcher
(`run-*.sh` or `serve-docker.sh`) that builds the correct, performance-qualified
`docker run` command (pinned image, KV budgets, draft model, etc.). This loader
generates start/stop scripts that delegate to those launchers, parameterized by
port + container name.

The generated service is a Docker container; its status is checked via
`docker ps --filter name=<container>` (see app.py check_service_status).
"""
import os
from .base import Loader, _run, expand, load_platform_config, write_scripts, which


# The Paiton plugin repo (where the launchers live). Overridable via platform.json.
def _repo():
    cfg = load_platform_config()
    return expand(cfg.get('paiton_repo', '~/Desktop/AI/paiton-vllm-plugin'))


# Catalog of Paiton chat/LLM models that have Docker launchers in the repo.
# Keyed by display name (shown in the Add Service dropdown); build_service maps
# the selected name to this config.
#   type 'flags': launcher takes --name/--port flags (Qwen3.8 run-*.sh -> launch-rocm10.py).
#   type 'env':   launcher reads PAITON_* env vars for port/container (serve-docker.sh).
PAITON_MODELS = {
    'Qwen3.8 27B (big brain)': {
        'dir': 'Qwen3.8-MXFP4-DFlash2',
        'launcher': 'run-3bit.sh',
        'type': 'flags',
        'gpus': 1,
    },
    'GPT-OSS 20B': {
        'dir': 'GPT-OSS-20B',
        'launcher': 'serve-docker.sh',
        'type': 'env',
        'port_var': 'PAITON_PORT',
        'name_var': 'PAITON_CONTAINER',
        'gpus': 1,
    },
    'MiniCPM5 2B': {
        'dir': 'MiniCPM5-2B',
        'launcher': 'serve-docker.sh',
        'type': 'env',
        'port_var': 'PAITON_PORT',
        'name_var': 'PAITON_CONTAINER',
        'gpus': 1,
    },
    'Ornith 1.5 35B': {
        'dir': 'Ornith-1.5',
        'launcher': 'serve-docker.sh',
        'type': 'env',
        'port_var': 'PAITON_HOST_PORT',
        'name_var': 'PAITON_CONTAINER_NAME',
        'gpus': 1,
    },
    'Qwen3-Coder 30B': {
        'dir': 'Qwen3-Coder-30B',
        'launcher': 'serve-docker.sh',
        'type': 'env',
        'port_var': 'PAITON_HOST_PORT',
        'name_var': 'PAITON_CONTAINER_NAME',
        'gpus': 1,
    },
    'Qwen3.8 NEO CODER MAX': {
        'dir': 'Qwen3.8-NEO-CODER-MAX',
        'launcher': 'serve-docker.sh',
        'type': 'env',
        'port_var': 'PAITON_NEO_PORT',
        'name_var': None,  # container name is hardcoded paiton-qwen38-neo in the launcher
        'fixed_container': 'paiton-qwen38-neo',
        'gpus': 1,
    },
}


class PaitonLoader(Loader):
    key = 'paiton'
    name = 'Paiton'
    requires_model = True
    # No loader-wide params (port is the dialog's separate field; model-specific
    # config like Qwen3.8 weights/mode uses the repo launcher's defaults).
    param_schema = []

    def detect(self):
        repo = _repo()
        if not os.path.isdir(os.path.join(repo, 'paiton_vllm_plugin')):
            return {'installed': False, 'version': None, 'detail': f'no Paiton repo at {repo}'}
        if not which('docker'):
            return {'installed': False, 'version': None, 'detail': 'docker not found'}
        r = _run(['docker', 'images', 'ghcr.io/eliovp/paiton-vllm-plugin', '--format', '{{.Tag}}'], timeout=10)
        tags = [l for l in (r.stdout or '').splitlines() if l.strip()] if r else []
        return {
            'installed': True,
            'version': f'{len(tags)} image(s)' if tags else 'repo present',
            'detail': f'repo: {repo}',
        }

    def list_models(self):
        repo = _repo()
        models = []
        for name, cfg in PAITON_MODELS.items():
            models.append({
                'name': name,
                'path': os.path.join(repo, 'models', cfg['dir']),
                'size_gb': 0.0,
                'format': 'paiton',
                'source': 'paiton_repo',
            })
        return models

    def build_service(self, key, model, params):
        cfg = PAITON_MODELS.get(model)
        if not cfg:
            raise ValueError(f'Unknown Paiton model: {model!r}')
        port = int(params.get('port') or 8000)
        gpus = params.get('gpus') or [0]
        repo = _repo()
        # Container name: the service key (unique per service), unless the launcher
        # hardcodes it (NEO).
        container = cfg.get('fixed_container') or key
        log_file = f'/home/{os.getlogin()}/logs/paiton_{key}.log'
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        launcher = os.path.join(repo, 'models', cfg['dir'], cfg['launcher'])

        if cfg['type'] == 'flags':
            # Qwen3.8: the launcher needs the PAITON_* checkpoint/cache dirs set,
            # and takes --name/--port flags (run-3bit.sh -> launch-rocm10.py --detach).
            start = f"""#!/usr/bin/env bash
set -euo pipefail
ROOT="{repo}"
export PAITON_TARGET_DIR="$ROOT/model-cache/qwen38-nvfp4"
export PAITON_DRAFT_DIR="$ROOT/model-cache/qwen38-dflash2"
export PAITON_W3ROT_DIR="$ROOT/model-cache/qwen38-w3rot-int3"
export PAITON_CACHE_DIR="$ROOT/runtime-cache/qwen38-rocm10-20261107"
LOG="{log_file}"
mkdir -p "$(dirname "$LOG")"
docker rm -f {container} 2>/dev/null || true
bash "{launcher}" --name {container} --port {port} --detach --compile-cache
pkill -f "docker logs -f {container}" 2>/dev/null || true
nohup docker logs -f {container} >> "$LOG" 2>&1 &
echo "paiton {model} starting on port {port} (log: $LOG)"
"""
        else:
            # env type: the launcher reads PAITON_* env vars for port/container and
            # runs `docker run` in the foreground, so background it with nohup.
            env_prefix = cfg['port_var'] + '=' + str(port)
            if cfg.get('name_var'):
                env_prefix += ' ' + cfg['name_var'] + '=' + container
            start = f"""#!/usr/bin/env bash
set -euo pipefail
ROOT="{repo}"
LOG="{log_file}"
mkdir -p "$(dirname "$LOG")"
docker rm -f {container} 2>/dev/null || true
{env_prefix} nohup bash "{launcher}" >> "$LOG" 2>&1 &
echo "paiton {model} starting on port {port} (log: $LOG)"
"""

        stop = f"""#!/usr/bin/env bash
set -euo pipefail
docker stop {container} 2>/dev/null || true
docker rm -f {container} 2>/dev/null || true
pkill -f "docker logs -f {container}" 2>/dev/null || true
echo "paiton {model} stopped"
"""

        start_path, stop_path = write_scripts(start, stop, key)
        service = {
            'name': f'{model} (Paiton)',
            'start_script': start_path,
            'stop_script': stop_path,
            'process_pattern': container,
            'container_name': container,
            'log_file': log_file,
            'loader': self.key,
            'generated': True,
            'default_params': {
                'gpus': gpus,
                'port': port,
            },
        }
        return {'service': service, 'start_script': start_path, 'stop_script': stop_path}
