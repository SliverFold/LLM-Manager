"""LM Studio loader — lms CLI (server on :45987 by default)."""
import json
import os
import re
import time
import shutil
from .base import Loader, _run, expand, load_platform_config, write_scripts, which


class LMStudioLoader(Loader):
    key = 'lmstudio'
    name = 'LM Studio'
    requires_model = True   # select which model to load in the new server
    fixed_port = 45987
    param_schema = [
        {'name': 'context_length', 'label': 'Max Context Length (tokens)', 'type': 'int', 'default': 102400, 'min': 256, 'max': 262144},
        {'name': 'kv_cache_quant', 'label': 'KV Cache Quantization', 'type': 'select', 'default': 'q8_0', 'options': ['q8_0', 'q5_1', 'q5_0', 'q4_1', 'iq4_nl', 'q4_0', 'f16']},
    ]

    def detect(self):
        binary = which('lms')
        if binary:
            r = _run(['lms', 'version'], timeout=15)
            version = None
            if r and r.stdout:
                # lms reports a commit hash, not an X.Y.Z version
                m = re.search(r'CLI commit: (\S+)', r.stdout) or re.search(r'(\d+\.\d+\.\d+)', r.stdout)
                version = m.group(1) if m else None
            return {'installed': True, 'version': version, 'detail': f'binary: {binary}'}
        return {'installed': False, 'version': None, 'detail': 'no lms binary'}

    def list_models(self):
        # `lms ls` prints to STDERR in some environments, STDOUT in others.
        # RACE: the first call after the local model service is down starts
        # it and returns an EMPTY table ("Error: No running LM Studio") —
        # retry once after a short wait.
        r = _run(['lms', 'ls'], timeout=15)
        out = ((r.stderr or '') + (r.stdout or '')) if r else ''
        models = self._parse_lms_ls(out)
        if not models:
            time.sleep(1)
            r = _run(['lms', 'ls'], timeout=15)
            out = ((r.stderr or '') + (r.stdout or '')) if r else ''
            models = self._parse_lms_ls(out)
        return models

    @staticmethod
    def _parse_lms_ls(out):
        models = []
        for line in out.splitlines():
            line = line.strip()
            # name (optionally " (N variant)"), then any params/arch columns,
            # then "<num> <unit>" size and a device column at the end.
            m = re.match(r'^([\w.@\-/]+)(?:\s\(\d+\s+variant\))?\s+.*?\s+([\d.]+)\s+(GB|MB|KB|TB)\s+\S+\s*$', line, re.IGNORECASE)
            if not m:
                continue
            size = float(m.group(2))
            unit = m.group(3).lower()
            if unit.startswith('mb'):
                size_gb = size / 1024.0
            elif unit.startswith('kb'):
                size_gb = size / 1024.0 / 1024.0
            else:
                size_gb = size  # GB or TB
            models.append({
                'name': m.group(1),
                'path': None,
                'size_gb': round(size_gb, 2),
                'format': 'gguf',
                'source': 'lmstudio',
            })
        return models

    def build_service(self, key, model, params):
        port = self.fixed_port
        log_file = f'/home/{os.getlogin()}/logs/lmstudio.log'
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        ctx = int(params.get('context_length') or 102400)
        kv = params.get('kv_cache_quant') or 'q8_0'
        # Generate the LM Studio engine config file (KV cache quantization type for
        # the llama.cpp engine). The format matches LM Studio's own per-model default
        # configs (~/.lmstudio/.internal/user-concrete-model-default-config/...).
        # Flash Attention must be on for V-cache quantization.
        kv_fields = [
            {'key': 'llm.load.llama.kCacheQuantizationType', 'value': {'checked': True, 'value': kv}},
            {'key': 'llm.load.llama.vCacheQuantizationType', 'value': {'checked': True, 'value': kv}},
        ]
        if kv != 'f16':
            kv_fields.append({'key': 'llm.load.llama.flashAttention', 'value': True})
        kv_config = {'preset': '', 'operation': {'fields': []}, 'load': {'fields': kv_fields}}
        cfg = load_platform_config()
        scripts_dir = expand(cfg.get('generated_scripts_dir', '~/Desktop/AI/vllm-model-manager-/scripts/generated'))
        os.makedirs(scripts_dir, exist_ok=True)
        kv_config_path = os.path.join(scripts_dir, f'mgr_{key}_kv.json')
        with open(kv_config_path, 'w') as f:
            json.dump(kv_config, f, indent=2)
        # If a model is specified, load it after the server starts.
        load_cmd = f'lms load "{model}" --context-length {ctx} --engine-config-file {kv_config_path} 2>&1 || echo "Model load failed"\n' if model else ''
        # Start the headless daemon, server, and load the model.
        start = f"""#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$(dirname {log_file})"
# Check if the server is already running (match "running" but not "not running")
if lms server status 2>&1 | grep -qi "running" && ! lms server status 2>&1 | grep -qi "not running"; then
  echo "LM Studio server already running"
  {load_cmd}
  exit 0
fi
# Start the headless daemon (no GUI)
lms daemon up
# Start the server (with CORS enabled so the browser can connect)
lms server start -p {port} --cors > {log_file} 2>&1
echo "LM Studio server starting on port {port}"
{load_cmd}
"""
        stop = f"""#!/usr/bin/env bash
set -euo pipefail
# Stop the server (unloads any loaded models with it).
lms server stop 2>/dev/null || true
# Kill the llama-server backend process (serves the model on a random port).
# This is separate from the LM Studio server and is NOT killed by `lms server stop`.
# Match the model path to avoid killing other llama-server processes (e.g. small brain).
LLAMA_PIDS=$(pgrep -f "llama-server.*\\.lmstudio/models" 2>/dev/null || true)
if [ -n "$LLAMA_PIDS" ]; then
    echo "$LLAMA_PIDS" | xargs kill 2>/dev/null || true
fi
# Shut down the headless daemon (or close the GUI app in GUI mode)
lms daemon down 2>/dev/null || true
# Also kill the GUI app if it's still running (GUI mode fallback)
GUI_PIDS=$(ps aux | grep "lm-studio --run-as-service" | grep -v grep | awk '{{print $2}}' || true)
if [ -n "$GUI_PIDS" ]; then
    echo "$GUI_PIDS" | xargs kill -9 2>/dev/null || true
fi
echo "LM Studio stopped (server + daemon + backend)"
"""
        start_path, stop_path = write_scripts(start, stop, key)
        service = {
            'name': f'LM Studio{" (" + model + ")" if model else ""} (port {port})',
            'start_script': start_path,
            'stop_script': stop_path,
            'process_pattern': f'llama-server.*{model}' if model else 'llama-server',
            'log_file': log_file,
            'loader': self.key,
            'generated': True,
            'default_params': {'gpus': params.get('gpus') or [], 'port': port, 'context_length': ctx, 'kv_cache_quant': kv},
        }
        return {'service': service, 'start_script': start_path, 'stop_script': stop_path}
