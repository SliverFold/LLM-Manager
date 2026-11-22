"""llama.cpp loader — standalone llama-server on GGUF files (ROCm/CUDA/CPU)."""
import os
import shutil
from .base import Loader, _run, expand, load_platform_config, scan_gguf_dirs, write_scripts, which


class LlamaCppLoader(Loader):
    key = 'llama_cpp'
    name = 'llama.cpp (llama-server)'
    requires_model = True
    param_schema = [
        {'name': 'context_length', 'label': 'Context length', 'type': 'int', 'default': 4096, 'min': 512, 'max': 262144},
        {'name': 'gpu_layers', 'label': 'GPU layers (-1 = all)', 'type': 'int', 'default': -1, 'min': -1, 'max': 512},
    ]

    def detect(self):
        binary = which('llama-server') or which('llama-server-macos')
        if binary:
            r = _run([binary, '--version'], timeout=10)
            version = r.stdout.strip().splitlines()[0] if r and r.stdout else None
            return {'installed': True, 'version': version, 'detail': f'binary: {binary}'}
        r = _run(['docker', 'images', '--format', '{{.Repository}}:{{.Tag}}'], timeout=15)
        images = [l for l in (r.stdout or '').splitlines() if 'llama' in l.lower() and ('ggml' in l.lower() or 'llamacpp' in l.lower() or 'llama.cpp' in l.lower())] if r else []
        if images:
            return {'installed': True, 'version': None, 'detail': f'docker image: {images[0]}'}
        return {'installed': False, 'version': None, 'detail': 'no llama-server binary or docker image'}

    def list_models(self):
        return scan_gguf_dirs()

    def build_service(self, key, model, params):
        gpus = params.get('gpus') or [0]
        port = params.get('port') or 8010
        ctx = int(params.get('context_length') or 4096)
        ngl = int(params.get('gpu_layers') if params.get('gpu_layers') is not None else -1)
        log_file = f'/home/{os.getlogin()}/logs/llamacpp_{key}.log'
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        # model may be a path or a bare name (resolve against gguf_dirs)
        model_path = model if os.path.isabs(model) or os.path.exists(model) else self._resolve(model)
        model_base = os.path.basename(model_path)
        hip = ','.join(map(str, gpus))

        if which('llama-server'):
            start = f"""#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$(dirname {log_file})"
HIP_VISIBLE_DEVICES={hip} nohup llama-server \\
    -m "{model_path}" \\
    --port {port} \\
    --host 0.0.0.0 \\
    -c {ctx} \\
    --gpu-layers {ngl} \\
    > {log_file} 2>&1 &
echo "llama-server {model_base} starting on port {port} (log: {log_file})"
"""
        else:
            image = self._first_docker_image()
            start = f"""#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$(dirname {log_file})"
docker rm -f mgr_{key} 2>/dev/null || true
docker run -d --name mgr_{key} \\
    --network=host --ipc=host \\
    --device /dev/kfd --device /dev/dri \\
    --group-add=video --cap-add=SYS_PTRACE --security-opt seccomp=unconfined \\
    -e HIP_VISIBLE_DEVICES={hip} \\
    -v "{model_path}":/models/model.gguf:ro \\
    {image} llama-server \\
        -m /models/model.gguf \\
        --port {port} \\
        --host 0.0.0.0 \\
        -c {ctx} \\
        --gpu-layers {ngl} \\
    > {log_file} 2>&1
echo "llama-server {model_base} starting on port {port} (log: {log_file})"
"""
        stop = f"""#!/usr/bin/env bash
set -euo pipefail
pkill -f "^llama-server.*{model_base.replace('.', '\\\\.')}" 2>/dev/null || true
docker rm -f mgr_{key} 2>/dev/null || true
echo "llama-server {key} stopped"
"""
        start_path, stop_path = write_scripts(start, stop, key)
        service = {
            'name': f'{model_base} (llama.cpp)',
            'start_script': start_path,
            'stop_script': stop_path,
            'process_pattern': f'llama-server.*{model_base}',
            'log_file': log_file,
            'loader': self.key,
            'generated': True,
            'default_params': {'gpus': gpus, 'port': port, 'context_length': ctx, 'gpu_layers': ngl},
        }
        return {'service': service, 'start_script': start_path, 'stop_script': stop_path}

    def _resolve(self, name):
        """Resolve a bare model name against the configured GGUF dirs."""
        for m in scan_gguf_dirs():
            if m['name'] == name or m['name'].startswith(name):
                return m['path']
        return name

    def _first_docker_image(self):
        r = _run(['docker', 'images', '--format', '{{.Repository}}:{{.Tag}}'], timeout=15)
        images = [l for l in (r.stdout or '').splitlines() if 'llama' in l.lower()] if r else []
        return images[0] if images else 'ggml/llama.cpp:latest'
