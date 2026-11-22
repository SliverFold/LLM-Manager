"""Ollama loader — one server, many GGUF models (OpenAI API on :11434)."""
import os
import re
import shutil
import urllib.request
from .base import Loader, _run, expand, write_scripts, which


class OllamaLoader(Loader):
    key = 'ollama'
    name = 'Ollama'
    requires_model = False   # the service is the server; model is optional (pull at start)
    fixed_port = 11434
    param_schema = []

    def detect(self):
        binary = which('ollama')
        if binary:
            r = _run(['ollama', '-v'], timeout=10)
            version = None
            if r and r.stdout:
                m = re.search(r'client version is (\S+)', r.stdout) or re.search(r'([\d.]+)', r.stdout)
                version = m.group(1) if m else None
            return {'installed': True, 'version': version, 'detail': f'binary: {binary}'}
        r = _run(['docker', 'images', 'ollama/ollama', '--quiet'], timeout=10)
        if r and r.stdout.strip():
            return {'installed': True, 'version': None, 'detail': 'docker image: ollama/ollama'}
        return {'installed': False, 'version': None, 'detail': 'no ollama binary or docker image'}

    def list_models(self):
        """List models via API, CLI, or the local model store (manifests)."""
        models = []
        # 1) API (if the server is running)
        try:
            with urllib.request.urlopen('http://localhost:11434/api/tags', timeout=3) as r:
                data = r.read()
            import json
            for m in json.loads(data).get('models', []):
                models.append({
                    'name': m.get('name'),
                    'path': None,
                    'size_gb': round(m.get('size', 0) / 1024 ** 3, 1),
                    'format': 'gguf',
                    'source': 'ollama_api',
                })
        except Exception:
            pass
        # 2) fallback: `ollama list` (works without the server if a store exists)
        if not models:
            r = _run(['ollama', 'list'], timeout=10)
            if r and r.stdout:
                for line in r.stdout.splitlines()[1:]:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        models.append({
                            'name': parts[0],
                            'path': None,
                            'size_gb': 0.0,
                            'format': 'gguf',
                            'source': 'ollama_cli',
                        })
        # 3) fallback: scan the default install location (~/.ollama/models/manifests)
        if not models:
            import glob
            seen = set()
            for manifest in glob.glob(os.path.join(expand('~/.ollama/models/manifests/registry.ollama.ai/library/*/*'))):
                name = os.path.basename(os.path.dirname(manifest))
                if name not in seen:
                    seen.add(name)
                    models.append({
                        'name': name,
                        'path': None,
                        'size_gb': 0.0,
                        'format': 'gguf',
                        'source': 'ollama_store',
                    })
        return models

    def build_service(self, key, model, params):
        port = self.fixed_port
        log_file = f'/home/{os.getlogin()}/logs/ollama.log'
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        home = expand('~')

        if which('ollama'):
            pull = f'ollama pull "{model}" || true\n' if model else ''
            start = f"""#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$(dirname {log_file})"
if curl -s -m 2 http://localhost:{port}/api/version >/dev/null 2>&1; then
  echo "ollama already running"
  exit 0
fi
{pull}nohup ollama serve > {log_file} 2>&1 &
echo "ollama starting on port {port} (log: {log_file})"
"""
        else:
            pull = f'docker exec ollama-server ollama pull "{model}" || true\n' if model else ''
            start = f"""#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$(dirname {log_file})"
if curl -s -m 2 http://localhost:{port}/api/version >/dev/null 2>&1; then
  echo "ollama already running"
  exit 0
fi
docker rm -f ollama-server 2>/dev/null || true
docker run -d --name ollama-server --network host \
    -v {home}/.ollama:/root/.ollama \
    ollama/ollama > {log_file} 2>&1
{pull}echo "ollama starting on port {port} (log: {log_file})"
"""
        stop = f"""#!/usr/bin/env bash
set -euo pipefail
pkill -f "^ollama serve" 2>/dev/null || true
docker rm -f ollama-server 2>/dev/null || true
echo "ollama stopped"
"""
        start_path, stop_path = write_scripts(start, stop, key)
        service = {
            'name': f'Ollama (port {port})' + (f' + {model}' if model else ''),
            'start_script': start_path,
            'stop_script': stop_path,
            'process_pattern': 'ollama serve|ollama/ollama',
            'log_file': log_file,
            'loader': self.key,
            'generated': True,
            'default_params': {'gpus': params.get('gpus') or [], 'port': port},
        }
        return {'service': service, 'start_script': start_path, 'stop_script': stop_path}
