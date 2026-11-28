"""Strata loader — serve Strata models as Docker containers (ghcr.io/niko1221/strata).

Strata is a local AI engine (chat, code, images) with an OpenAI- and
Anthropic-compatible API. The Docker image bundles a prebuilt engine for the
card; `rocm-gfx120x` covers both local cards (R9700 + RX 9070, both gfx1201).
The container listens on 8080 inside, is bound to 127.0.0.1:<port> on the host,
and every request needs a bearer API key (GET /health is keyless).

The generated service is a Docker container; its status is checked via
`docker ps --filter name=<container>` (see app.py check_service_status).
"""
import os
import secrets
from .base import Loader, _run, expand, load_platform_config, write_scripts, which

IMAGE = 'ghcr.io/niko1221/strata'
IMAGE_TAG = '0.2.20-rocm-gfx120x'  # AMD RDNA4 (gfx1200/gfx1201): R9700 + RX 9070

# Catalog of models servable from the container. Keyed by display name (shown
# in the Add Service dropdown); build_service maps the name to (family, model).
# Sizes are the download estimate (MODELS.md).
STRATA_MODELS = {
    # Qwen3.8-Flash-Next (ISTA-DASLab original packs)
    'Qwen3.8-Flash-Next Q2_0': {'family': 'qwen', 'model': 'Q2_0', 'size': '~66 GB', 'bits': '2-bit'},
    'Qwen3.8-Flash-Next IQ2_XS': {'family': 'qwen', 'model': 'IQ2_XS', 'size': '~70 GB', 'bits': '2-bit'},
    'Qwen3.8-Flash-Next IQ3_XXS': {'family': 'qwen', 'model': 'IQ3_XXS', 'size': '~76 GB', 'bits': '3-bit'},
    'Qwen3.8-Flash-Next IQ3_S': {'family': 'qwen', 'model': 'IQ3_S', 'size': '~80 GB', 'bits': '3-bit'},
    'Qwen3.8-Flash-Next Coder': {'family': 'coder', 'model': 'IQ1_M', 'size': '~60 GB', 'bits': '1-bit (code)'},
    # Qwen3.8-Flash-Next (Unsloth 4-8 bit)
    'Qwen3.8-Flash-Next UD-IQ4_XS (Unsloth)': {'family': 'unsloth', 'model': 'UD-IQ4_XS', 'size': '~94 GB', 'bits': '4-bit'},
    'Qwen3.8-Flash-Next UD-Q4_K_XL (Unsloth)': {'family': 'unsloth', 'model': 'UD-Q4_K_XL', 'size': '~111 GB', 'bits': '4-bit'},
    'Qwen3.8-Flash-Next UD-Q5_K_XL (Unsloth)': {'family': 'unsloth', 'model': 'UD-Q5_K_XL', 'size': '~158 GB', 'bits': '5-bit'},
    'Qwen3.8-Flash-Next UD-Q6_K_XL (Unsloth)': {'family': 'unsloth', 'model': 'UD-Q6_K_XL', 'size': '~169 GB', 'bits': '6-bit'},
    'Qwen3.8-Flash-Next Q8_0 (Unsloth)': {'family': 'unsloth', 'model': 'Q8_0', 'size': '~188 GB', 'bits': '8-bit'},
    # Qwen3.8-Flash-Next (Gyro)
    'Qwen3.8-Flash-Next Gyro-S': {'family': 'gyro', 'model': 'Gyro-S', 'size': '~59 GB', 'bits': 'Gyro-S'},
    'Qwen3.8-Flash-Next Gyro-M': {'family': 'gyro', 'model': 'Gyro-M', 'size': '~92 GB', 'bits': 'Gyro-M'},
    # Qwen3.6-35B-A3B (Unsloth)
    'Qwen3.6-35B-A3B UD-Q4_K_XL': {'family': 'qwen36', 'model': 'UD-Q4_K_XL', 'size': '~23 GB', 'bits': '4-bit'},
    'Qwen3.6-35B-A3B UD-Q6_K_XL': {'family': 'qwen36', 'model': 'UD-Q6_K_XL', 'size': '~33 GB', 'bits': '6-bit'},
    'Qwen3.6-35B-A3B Q8_0': {'family': 'qwen36', 'model': 'Q8_0', 'size': '~38 GB', 'bits': '8-bit'},
    # Tencent Hy4-Flash (Strata native .strata)
    'Hy4-Flash SQ-64': {'family': 'hy4-flash', 'model': 'SQ-64', 'size': '~130 GB', 'bits': 'SQ-64'},
    'Hy4-Flash SQ-96': {'family': 'hy4-flash', 'model': 'SQ-96', 'size': '~157 GB', 'bits': 'SQ-96'},
    'Hy4-Flash SQ-128': {'family': 'hy4-flash', 'model': 'SQ-128', 'size': '~181 GB', 'bits': 'SQ-128'},
    # Inkling-2-Mini (Strata native .strata)
    'Inkling-2-Mini SQ-10': {'family': 'inkling-2-mini', 'model': 'SQ-10', 'size': '~10.5 GB', 'bits': 'SQ-10'},
    'Inkling-2-Mini SQ-15': {'family': 'inkling-2-mini', 'model': 'SQ-15', 'size': '~14.3 GB', 'bits': 'SQ-15'},
    'Inkling-2-Mini SQ-20': {'family': 'inkling-2-mini', 'model': 'SQ-20', 'size': '~19.3 GB', 'bits': 'SQ-20'},
    # Inkling-2-Mini (Unsloth GGUF)
    'Inkling-2-Mini UD-IQ1_S': {'family': 'inkling-2-mini', 'model': 'UD-IQ1_S', 'size': '~7.8 GB', 'bits': '1-bit'},
    'Inkling-2-Mini UD-IQ1_M': {'family': 'inkling-2-mini', 'model': 'UD-IQ1_M', 'size': '~8 GB', 'bits': '1-bit'},
    'Inkling-2-Mini UD-IQ2_XXS': {'family': 'inkling-2-mini', 'model': 'UD-IQ2_XXS', 'size': '~8.5 GB', 'bits': '2-bit'},
    'Inkling-2-Mini UD-Q2_K_XL': {'family': 'inkling-2-mini', 'model': 'UD-Q2_K_XL', 'size': '~9.1 GB', 'bits': '2-bit'},
    'Inkling-2-Mini UD-IQ3_XXS': {'family': 'inkling-2-mini', 'model': 'UD-IQ3_XXS', 'size': '~11.7 GB', 'bits': '3-bit'},
    'Inkling-2-Mini UD-Q3_K_XL': {'family': 'inkling-2-mini', 'model': 'UD-Q3_K_XL', 'size': '~14 GB', 'bits': '3-bit'},
    'Inkling-2-Mini UD-IQ4_XS': {'family': 'inkling-2-mini', 'model': 'UD-IQ4_XS', 'size': '~15.7 GB', 'bits': '4-bit'},
    'Inkling-2-Mini UD-Q4_K_M': {'family': 'inkling-2-mini', 'model': 'UD-Q4_K_M', 'size': '~16.6 GB', 'bits': '4-bit'},
    'Inkling-2-Mini UD-Q4_K_XL': {'family': 'inkling-2-mini', 'model': 'UD-Q4_K_XL', 'size': '~17.6 GB', 'bits': '4-bit'},
    'Inkling-2-Mini UD-Q8_K_XL': {'family': 'inkling-2-mini', 'model': 'UD-Q8_K_XL', 'size': '~22.9 GB', 'bits': '8-bit'},
}


class StrataLoader(Loader):
    key = 'strata'
    name = 'Strata'
    requires_model = True
    param_schema = [
        {'name': 'context', 'label': 'Context', 'type': 'select', 'default': 'auto',
         'options': ['auto', '8k', '16k', '32k', '64k', '128k', '256k']},
        {'name': 'vision', 'label': 'Picture reading', 'type': 'select', 'default': 'on',
         'options': ['on', 'off', 'gpu', 'cpu']},
        {'name': 'kv', 'label': 'KV cache format', 'type': 'select', 'default': 'int8',
         'options': ['int8', 'q4_0', 'k8v4', 'fp16']},
        {'name': 'parallel', 'label': 'Parallel requests', 'type': 'int', 'default': 1, 'min': 1, 'max': 8},
    ]

    def detect(self):
        out = {'installed': False, 'version': None, 'detail': ''}
        if not which('docker'):
            out['detail'] = 'docker not found'
            return out
        r = _run(['docker', 'images', IMAGE, '--format', '{{.Tag}}'], timeout=10)
        tags = [l for l in (r.stdout or '').splitlines() if l.strip()] if r else []
        if tags:
            out['installed'] = True
            out['version'] = tags[0]
            out['detail'] = f'image {IMAGE}:{tags[0]}'
        else:
            out['detail'] = 'docker present, no Strata image (Install pulls it)'
        return out

    def list_models(self):
        models = []
        for name, cfg in STRATA_MODELS.items():
            models.append({
                'name': name,
                'path': None,
                'size_gb': 0.0,
                'format': 'strata',
                'source': 'strata_catalog',
            })
        return models

    def build_service(self, key, model, params):
        cfg = STRATA_MODELS.get(model)
        if not cfg:
            raise ValueError(f'Unknown Strata model: {model!r}')
        port = int(params.get('port') or 8080)
        gpus = params.get('gpus') or [0]
        gpu_spec = ','.join(str(g) for g in gpus)
        container = key
        volume = f'strata-data-{key}'
        log_file = f'/home/{os.getlogin()}/logs/strata_{key}.log'
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        # Per-service API key: written once at generation time (the start script
        # reads it), so the key survives container recreation and can be used by
        # clients (Hermes, strata connect, the manager's chat page). Re-generation
        # (changed params) must keep the existing key — clients already use it.
        scripts_dir = expand(load_platform_config().get(
            'generated_scripts_dir', '~/Desktop/AI/vllm-model-manager-/scripts/generated'))
        os.makedirs(scripts_dir, exist_ok=True)
        key_file = os.path.join(scripts_dir, f'strata_{key}.key')
        existing_key = (params.get('existing_key')
                        or (open(key_file).read().strip() if os.path.exists(key_file) else ''))
        api_key = existing_key or secrets.token_hex(24)
        with open(key_file, 'w') as f:
            f.write(api_key)
        os.chmod(key_file, 0o600)

        # Optional env vars (omit the auto defaults so Strata picks for the card).
        env_lines = []
        context = params.get('context') or 'auto'
        if context and context != 'auto':
            env_lines.append(f'      -e CONTEXT="{context}" \\')
        vision = params.get('vision') or 'on'
        if vision != 'on':
            env_lines.append(f'      -e VISION="{vision}" \\')
        kv = params.get('kv') or 'int8'
        if kv != 'int8':
            env_lines.append(f'      -e KV="{kv}" \\')
        parallel = int(params.get('parallel') or 1)
        env_lines.append(f'      -e PARALLEL="{parallel}" \\')
        # Build the docker run lines as a list: every line except the last ends
        # with a continuation backslash (a blank line after a backslash would
        # terminate the command and drop the image argument).
        run_lines = [
            f'docker run -d --name {container} \\',
            f'  --device /dev/kfd --device /dev/dri \\',
            f'  "${{GROUP_ARGS[@]}}" \\',
            f'  -p 127.0.0.1:{port}:8080 \\',
            f'  --ulimit memlock=-1:-1 --shm-size 2g --stop-timeout 120 \\',
            f'  -v {volume}:/data \\',
            f'  -e FAMILY={cfg["family"]} \\',
            f'  -e MODEL={cfg["model"]} \\',
            f'  -e API_KEY="$API_KEY" \\',
            f'  -e GPU="{gpu_spec}" \\',
        ] + env_lines
        run_lines.append(f'  {IMAGE}:{IMAGE_TAG}')
        run_block = '\n'.join(run_lines)

        start = f"""#!/usr/bin/env bash
set -euo pipefail
LOG="{log_file}"
mkdir -p "$(dirname "$LOG")"
docker rm -f {container} 2>/dev/null || true
API_KEY="$(cat "{key_file}")"
RENDER_GID="$(getent group render | cut -d: -f3)"
GROUP_ARGS=(--group-add video)
[ -n "$RENDER_GID" ] && GROUP_ARGS+=(--group-add "$RENDER_GID")
{run_block}
pkill -f "docker logs -f {container}" 2>/dev/null || true
nohup docker logs -f {container} >> "$LOG" 2>&1 &
echo "strata {model} starting on port {port} (log: $LOG)"
"""

        stop = f"""#!/usr/bin/env bash
set -euo pipefail
docker stop --time 120 {container} 2>/dev/null || true
docker rm {container} 2>/dev/null || true
pkill -f "docker logs -f {container}" 2>/dev/null || true
echo "strata {model} stopped"
"""

        start_path, stop_path = write_scripts(start, stop, key)
        service = {
            'name': f'{model} (Strata)',
            'start_script': start_path,
            'stop_script': stop_path,
            'container_name': container,
            'log_file': log_file,
            'loader': self.key,
            'generated': True,
            'api_key': api_key,
            'default_params': {
                'gpus': gpus,
                'port': port,
                'context': context,
                'vision': vision,
                'kv': kv,
                'parallel': parallel,
            },
        }
        return {'service': service, 'start_script': start_path, 'stop_script': stop_path}
