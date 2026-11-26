"""vLLM loader — direct `vllm serve` or docker images (ROCm/CUDA)."""
import os
import shutil
from .base import Loader, _run, expand, load_platform_config, scan_hf_cache, write_scripts, which


class VllmLoader(Loader):
    key = 'vllm'
    name = 'vLLM'
    requires_model = True
    param_schema = [
        {'name': 'tensor_parallel_size', 'label': 'Tensor Parallel Size', 'type': 'int', 'default': 1, 'min': 1, 'max': 16},
        {'name': 'gpu_memory_utilization', 'label': 'GPU VRAM utilization', 'type': 'float', 'default': 0.9, 'min': 0.1, 'max': 1.0, 'step': 0.05},
        {'name': 'max_model_len', 'label': 'Max Context Length (tokens)', 'type': 'int', 'default': 102400, 'min': 256, 'max': 262144},
        {'name': 'dtype', 'label': 'Data type', 'type': 'select', 'default': 'auto', 'options': ['auto', 'float16', 'bfloat16', 'float32']},
        {'name': 'image', 'label': 'Docker image (if no vllm binary)', 'type': 'select', 'default': '', 'options': []},
    ]

    def detect(self):
        binary = which('vllm')
        if binary:
            r = _run(['vllm', '--version'], timeout=15)
            version = r.stdout.strip().splitlines()[-1] if r and r.stdout else None
            return {'installed': True, 'version': version, 'detail': f'binary: {binary}'}
        # docker images
        r = _run(['docker', 'images', '--format', '{{.Repository}}:{{.Tag}}'], timeout=15)
        images = [l for l in (r.stdout or '').splitlines() if 'vllm' in l.lower()] if r else []
        if images:
            return {'installed': True, 'version': None, 'detail': f'{len(images)} docker image(s): {images[0]}'}
        return {'installed': False, 'version': None, 'detail': 'no vllm binary or docker image'}

    def list_models(self):
        return scan_hf_cache()

    def build_service(self, key, model, params):
        gpus = params.get('gpus') or [0]
        port = params.get('port') or 8000
        tp = int(params.get('tensor_parallel_size') or 1)
        gmu = float(params.get('gpu_memory_utilization') or 0.9)
        mml = int(params.get('max_model_len') or 102400)
        dtype = params.get('dtype') or 'auto'
        log_file = f'/home/{os.getlogin()}/logs/vllm_{key}.log'
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        cuda_devices = ','.join(map(str, gpus))

        image = params.get('image') or ''
        if which('vllm'):
            start = f"""#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$(dirname {log_file})"
CUDA_VISIBLE_DEVICES={cuda_devices} nohup vllm serve "{model}" \\
    --tensor-parallel-size {tp} \\
    --port {port} \\
    --host 0.0.0.0 \\
    --gpu-memory-utilization {gmu} \\
    --max-model-len {mml} \\
    --dtype {dtype} \\
    > {log_file} 2>&1 &
echo "vllm {model} starting on port {port} (log: {log_file})"
"""
        else:
            if not image:
                image = self._first_docker_image()
            start = f"""#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$(dirname {log_file})"
docker rm -f mgr_{key} 2>/dev/null || true
docker run -d --name mgr_{key} \\
    --network=host --ipc=host \\
    --device /dev/kfd --device /dev/dri \\
    --group-add=video --cap-add=SYS_PTRACE --security-opt seccomp=unconfined \\
    -e CUDA_VISIBLE_DEVICES={cuda_devices} \\
    -e VLLM_NO_USAGE_STATS=1 \\
    -v {expand('~/.cache/huggingface')}/:/root/.cache/huggingface \\
    {image} vllm serve {model} \\
        --tensor-parallel-size {tp} \\
        --port {port} \\
        --host 0.0.0.0 \\
        --gpu-memory-utilization {gmu} \\
        --max-model-len {mml} \\
        --dtype {dtype} \\
    > {log_file} 2>&1
echo "vllm {model} starting on port {port} (log: {log_file})"
"""
        stop = f"""#!/usr/bin/env bash
set -euo pipefail
pkill -f "^vllm serve.*{model.replace('/', '\\\\/')}" 2>/dev/null || true
docker rm -f mgr_{key} 2>/dev/null || true
echo "vllm {key} stopped"
"""
        start_path, stop_path = write_scripts(start, stop, key)
        service = {
            'name': f'{model} (vLLM)',
            'start_script': start_path,
            'stop_script': stop_path,
            'process_pattern': f'vllm serve.*{model}',
            'log_file': log_file,
            'loader': self.key,
            'generated': True,
            'default_params': {
                'gpus': gpus, 'port': port, 'tensor_parallel_size': tp,
                'gpu_memory_utilization': gmu, 'max_model_len': mml, 'dtype': dtype,
            },
        }
        return {'service': service, 'start_script': start_path, 'stop_script': stop_path}

    def _first_docker_image(self):
        r = _run(['docker', 'images', '--format', '{{.Repository}}:{{.Tag}}'], timeout=15)
        images = [l for l in (r.stdout or '').splitlines() if 'vllm' in l.lower()] if r else []
        return images[0] if images else 'vllm/vllm-openai:latest'
