#!/usr/bin/env python3
"""
LLM Model Manager
A web management system for managing and monitoring LLM model services
"""

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import subprocess
import os
import glob
import shutil
import psutil
import json
import time
import re
import urllib.request
from datetime import datetime, date
from pathlib import Path

from loaders import all_loaders, get_loader
from loaders.base import next_free_port, make_service_key

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

# Per-service state for computing live token rates (rolling window of samples)
from collections import deque
VLLM_STATE = {}

def _parse_prom(text):
    """Parse Prometheus text format. Returns (scalars, buckets):
    scalars = {name: value} and {name: {'sum': x, 'count': y}} for histograms;
    buckets = {name: [(le, count), ...]} for histogram _bucket lines."""
    out = {}
    buckets = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        m = re.match(r'^([a-zA-Z_][\w:]*)(?:\{([^}]*?)\})? (-?[0-9a-fA-F.]*(?:[eE][+-]?\d+)?)$', line)
        if not m:
            continue
        name, labels, raw = m.groups()
        try:
            val = float(raw)
        except ValueError:
            continue
        if name.endswith('_bucket'):
            base = name[:-7]
            le_m = re.search(r'le="([^"]+)"', labels or '')
            if le_m:
                le = float('inf') if le_m.group(1) == '+Inf' else float(le_m.group(1))
                buckets.setdefault(base, []).append((le, val))
        elif name.endswith('_sum'):
            out.setdefault(name[:-4], {})['sum'] = val
        elif name.endswith('_count'):
            out.setdefault(name[:-6], {})['count'] = val
        else:
            out[name] = val
    return out, buckets

# Load service config from the config file
CONFIG_FILE = Path(__file__).parent / 'config' / 'services.json'

def load_services_config():
    """Load the service configuration"""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

SERVICES = load_services_config()

def _rocm_smi():
    """Resolve rocm-smi to an absolute path — systemd user services get a minimal PATH (/usr/bin:/bin) that lacks /opt/rocm/bin."""
    p = shutil.which('rocm-smi')
    if p:
        return p
    for cand in ('/opt/rocm/bin/rocm-smi', '/usr/bin/rocm-smi', '/usr/local/bin/rocm-smi'):
        if os.path.exists(cand):
            return cand
    return 'rocm-smi'

def _gpu_metrics_rocm():
    """AMD: combined rocm-smi JSON (util/temp/power/VRAM). Returns dict card -> metrics or None."""
    try:
        result = subprocess.run(
            [_rocm_smi(), '--showuse', '--showtemp', '--showpower', '--showmeminfo', 'vram', '--showclocks', '--json'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except Exception as e:
        print(f"rocm-smi metrics failed: {e}")
    return None

def _gpu_names_rocm():
    try:
        result = subprocess.run(
            [_rocm_smi(), '--showproductname', '--json'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except Exception as e:
        print(f"rocm-smi names failed: {e}")
    return {}

def get_gpu_info():
    """Get GPU info (AMD rocm-smi first, nvidia-smi as fallback)"""
    metrics = _gpu_metrics_rocm()
    if metrics:
        names = _gpu_names_rocm()
        gpus = []
        for card, m in metrics.items():
            def f(key, default=0.0):
                try:
                    return float(m.get(key, default))
                except (TypeError, ValueError):
                    return default
            # sclk = shader/core clock (what the kernel amdgpu hwmon freq1 + KDE system
            # monitor report; fclk is the fabric clock — a different, lower domain on
            # gfx1201/R9700, so it disagreed with the system monitor)
            try:
                match = re.search(r'\((\d+)Mhz\)', str(m.get('sclk clock speed:', '')))
                clock_mhz = float(match.group(1)) if match else 0.0
            except (ValueError, TypeError):
                clock_mhz = 0.0
            # mclk = VRAM memory clock
            try:
                mmatch = re.search(r'\((\d+)Mhz\)', str(m.get('mclk clock speed:', '')))
                mem_clock_mhz = float(mmatch.group(1)) if mmatch else 0.0
            except (ValueError, TypeError):
                mem_clock_mhz = 0.0
            try:
                idx = int(card.replace('card', ''))
            except ValueError:
                idx = len(gpus)
            gpus.append({
                'index': idx,
                'name': names.get(card, {}).get('Card Series', f'AMD GPU {idx}'),
                'utilization': f('GPU use (%)'),
                'memory_used': f('VRAM Total Used Memory (B)') / 1024 ** 2,
                'memory_total': f('VRAM Total Memory (B)') / 1024 ** 2,
                'temperature': f('Temperature (Sensor junction) (C)'),  # hotspot
                'memory_temperature': f('Temperature (Sensor memory) (C)'),  # VRAM
                'power_draw': f('Average Graphics Package Power (W)'),
                'power_limit': 0,
                'clock_mhz': clock_mhz,
                'mem_clock_mhz': mem_clock_mhz
            })
        if gpus:
            return gpus
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit,clocks.graphics,clocks.mem',
             '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0:
            return []

        gpus = []
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 10:
                    gpus.append({
                        'index': int(parts[0]),
                        'name': parts[1],
                        'utilization': float(parts[2]) if parts[2] != '[N/A]' else 0,
                        'memory_used': float(parts[3]) if parts[3] != '[N/A]' else 0,
                        'memory_total': float(parts[4]) if parts[4] != '[N/A]' else 0,
                        'temperature': float(parts[5]) if parts[5] != '[N/A]' else 0,
                        'memory_temperature': 0,  # no separate VRAM sensor on NVIDIA
                        'power_draw': float(parts[6]) if parts[6] != '[N/A]' else 0,
                        'power_limit': float(parts[7]) if parts[7] != '[N/A]' else 0,
                        'clock_mhz': float(parts[8]) if parts[8] != '[N/A]' else 0,
                        'mem_clock_mhz': float(parts[9]) if parts[9] != '[N/A]' else 0
                    })
        return gpus
    except Exception as e:
        print(f"Failed to get GPU info: {e}")
        return []

def get_process_gpu_usage(pid):
    """Get GPU usage for a specific process (AMD: rocm-smi --showpids, nvidia-smi as fallback)"""
    try:
        result = subprocess.run(
            [_rocm_smi(), '--showpids'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                parts = [p.strip() for p in line.split('\t')]
                if len(parts) >= 4 and parts[0] == str(pid):
                    try:
                        return float(parts[3]) / 1024 ** 2  # VRAM USED, bytes -> MB
                    except ValueError:
                        return None
            return 0
    except Exception as e:
        print(f"rocm-smi pids failed: {e}")
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-compute-apps=pid,used_memory', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0:
            return None

        for line in result.stdout.strip().split('\n'):
            if line.strip():
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 2 and parts[0] == str(pid):
                    return float(parts[1])
        return None
    except Exception as e:
        print(f"Failed to get process GPU usage: {e}")
        return None

def check_service_status(service_key):
    """Check service status"""
    service = SERVICES[service_key]

    try:
        # Docker-container services (Paiton): check the container's state via docker ps,
        # then use the container's PID for CPU/memory/GPU stats.
        container_name = service.get('container_name')
        if container_name:
            r = subprocess.run(
                ['docker', 'ps', '--filter', f'name={container_name}', '--format', '{{.State}}'],
                capture_output=True, text=True, timeout=10
            )
            if r.returncode == 0 and 'running' in r.stdout:
                r2 = subprocess.run(
                    ['docker', 'inspect', container_name, '--format', '{{.State.Pid}}'],
                    capture_output=True, text=True, timeout=10
                )
                try:
                    pid = int(r2.stdout.strip() or 0)
                except ValueError:
                    pid = 0
                if pid:
                    proc = psutil.Process(pid)
                    cpu_percent = proc.cpu_percent(interval=0.1)
                    memory_info = proc.memory_info()
                    memory_mb = memory_info.rss / 1024 / 1024
                    port = service.get('port', service.get('default_params', {}).get('port', 8000))
                    port_check = subprocess.run(
                        ['curl', '-s', f'http://localhost:{port}/health'],
                        capture_output=True, timeout=2
                    )
                    port_accessible = port_check.returncode == 0
                    gpu_memory = get_process_gpu_usage(pid)
                    return {
                        'status': 'running',
                        'pid': pid,
                        'cpu_percent': cpu_percent,
                        'memory_mb': memory_mb,
                        'port_accessible': port_accessible,
                        'gpu_memory_mb': gpu_memory,
                        'uptime': datetime.fromtimestamp(proc.create_time()).strftime('%Y-%m-%d %H:%M:%S'),
                        'uptime_seconds': int(time.time() - proc.create_time())
                    }
                return {'status': 'running', 'port_accessible': False}
            return {'status': 'stopped'}

        # Process-based services: check if the process is running
        result = subprocess.run(
            ['pgrep', '-f', service['process_pattern']],
            capture_output=True,
            text=True
        )

        if result.returncode == 0 and result.stdout.strip():
            pid = int(result.stdout.strip().split('\n')[0])

            # Get process info
            try:
                proc = psutil.Process(pid)
                cpu_percent = proc.cpu_percent(interval=0.1)
                memory_info = proc.memory_info()
                memory_mb = memory_info.rss / 1024 / 1024

                # Check if the port is accessible
                port = service.get('port', service.get('default_params', {}).get('port', 8000))
                port_check = subprocess.run(
                    ['curl', '-s', f'http://localhost:{port}/health'],
                    capture_output=True,
                    timeout=2
                )
                port_accessible = port_check.returncode == 0

                # Get this process's GPU usage
                gpu_memory = get_process_gpu_usage(pid)

                return {
                    'status': 'running',
                    'pid': pid,
                    'cpu_percent': cpu_percent,
                    'memory_mb': memory_mb,
                    'port_accessible': port_accessible,
                    'gpu_memory_mb': gpu_memory,
                    'uptime': datetime.fromtimestamp(proc.create_time()).strftime('%Y-%m-%d %H:%M:%S'),
                    'uptime_seconds': int(time.time() - proc.create_time())
                }
            except psutil.NoSuchProcess:
                return {'status': 'stopped'}
        else:
            return {'status': 'stopped'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

@app.route('/')
def index():
    """API info"""
    return jsonify({
        'name': 'LLM Model Manager API',
        'version': '1.0.0',
        'endpoints': {
            'services': '/api/services',
            'gpu': '/api/gpu',
            'system': '/api/system',
            'start': '/api/service/{service_key}/start',
            'stop': '/api/service/{service_key}/stop',
            'logs': '/api/service/{service_key}/logs'
        },
        'frontend': 'http://{}:3000'.format(request.host.split(':')[0])
    })

def save_services_config():
    """Save the service config to file"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(SERVICES, f, indent=4, ensure_ascii=False)

@app.route('/api/services')
def get_services():
    """Get status of all services"""
    services_status = {}

    for key, service in SERVICES.items():
        status = check_service_status(key)
        default_params = service.get('default_params', {})
        services_status[key] = {
            'name': service['name'],
            'port': default_params.get('port', service.get('port', 8000)),
            'gpus': default_params.get('gpus', service.get('gpus', [])),
            'default_params': default_params,
            'loader': service.get('loader'),
            'model': service.get('model'),
            **status
        }

    return jsonify(services_status)

@app.route('/api/gpu')
def get_gpu():
    """Get GPU info"""
    gpu_info = get_gpu_info()
    return jsonify(gpu_info)

@app.route('/api/service/<service_key>/config', methods=['GET'])
def get_service_config(service_key):
    """Get a service's default config"""
    if service_key not in SERVICES:
        return jsonify({'success': False, 'message': 'Service not found'}), 404

    service = SERVICES[service_key]
    default_params = service.get('default_params', {
        'gpus': service.get('gpus', [0]),
        'port': service.get('port', 8000),
        'tensor_parallel_size': 1,
        'gpu_memory_utilization': 0.9,
        'max_model_len': 102400,
        'dtype': 'auto'
    })

    return jsonify({
        'success': True,
        'config': default_params,
        'model_path': service.get('model_path', ''),
        'extra_args': service.get('extra_args', '')
    })

@app.route('/api/service/<service_key>/config', methods=['POST'])
def save_service_config(service_key):
    """Save a service's default config"""
    if service_key not in SERVICES:
        return jsonify({'success': False, 'message': 'Service not found'}), 404

    data = request.get_json(silent=True) or {}
    params = data.get('params', {})

    if params:
        SERVICES[service_key]['default_params'] = {
            'gpus': params.get('gpus', [0]),
            'port': params.get('port', 8000),
            'tensor_parallel_size': params.get('tensorParallelSize', params.get('tensor_parallel_size', 1)),
            'gpu_memory_utilization': params.get('gpuUtil', params.get('gpu_memory_utilization', 0.9)),
            'max_model_len': params.get('maxModelLen', params.get('max_model_len', 102400)),
            'dtype': params.get('dtype', 'auto')
        }
        save_services_config()

    return jsonify({'success': True, 'message': 'Configuration saved'})

@app.route('/api/service/<service_key>/start', methods=['POST'])
def start_service(service_key):
    """Start a service (supports dynamic parameters)"""
    if service_key not in SERVICES:
        return jsonify({'success': False, 'message': 'Service not found'}), 404

    service = SERVICES[service_key]

    # Check if it is already running
    status = check_service_status(service_key)
    if status['status'] == 'running':
        return jsonify({'success': False, 'message': 'Service already running'})

    # Get request parameters, falling back to defaults
    data = request.get_json(silent=True) or {}
    default_params = service.get('default_params', {})

    # Parameter validation
    VALID_DTYPES = {'auto', 'float16', 'bfloat16', 'float32'}

    gpus = data.get('gpus', default_params.get('gpus', [0]))
    if not isinstance(gpus, list) or not all(isinstance(g, int) and 0 <= g < 16 for g in gpus):
        return jsonify({'success': False, 'message': 'Invalid GPU parameter'}), 400

    port = int(data.get('port', default_params.get('port', 8000)))
    if not (1024 <= port <= 65535):
        return jsonify({'success': False, 'message': 'Port out of range (1024-65535)'}), 400

    tensor_parallel_size = int(data.get('tensorParallelSize', data.get('tensor_parallel_size', default_params.get('tensor_parallel_size', 1))))
    if not (1 <= tensor_parallel_size <= 16):
        return jsonify({'success': False, 'message': 'tensor_parallel_size out of range (1-16)'}), 400

    gpu_memory_utilization = float(data.get('gpuUtil', data.get('gpu_memory_utilization', default_params.get('gpu_memory_utilization', 0.9))))
    if not (0.1 <= gpu_memory_utilization <= 1.0):
        return jsonify({'success': False, 'message': 'gpu_memory_utilization out of range (0.1-1.0)'}), 400

    max_model_len = int(data.get('maxModelLen', data.get('max_model_len', default_params.get('max_model_len', 102400))))
    if not (256 <= max_model_len <= 262144):
        return jsonify({'success': False, 'message': 'max_model_len out of range (256-262144)'}), 400

    dtype = str(data.get('dtype', default_params.get('dtype', 'auto')))
    if dtype not in VALID_DTYPES:
        return jsonify({'success': False, 'message': f'Invalid dtype, must be one of {VALID_DTYPES}'}), 400

    parallel_mode = str(data.get('parallelMode', data.get('parallel_mode', default_params.get('parallel_mode', 'tp'))))
    if parallel_mode not in {'tp', 'pp'}:
        return jsonify({'success': False, 'message': 'parallel_mode must be "tp" or "pp"'}), 400

    save_as_default = data.get('saveAsDefault', False)

    # Save as default config — only persist the fields that apply to this service's loader,
    # so a non-vLLM service (ollama/lmstudio/llama_cpp) doesn't get vLLM fields
    # (tensor_parallel_size, dtype, ...) baked into its default_params.
    if save_as_default:
        loader_key = service.get('loader') or 'vllm'
        new_params = {'gpus': gpus, 'port': port}
        if loader_key == 'vllm':
            new_params.update({
                'tensor_parallel_size': tensor_parallel_size,
                'gpu_memory_utilization': gpu_memory_utilization,
                'max_model_len': max_model_len,
                'dtype': dtype,
            })
            if parallel_mode and (service.get('default_params', {}) or {}).get('parallel_mode') is not None:
                new_params['parallel_mode'] = parallel_mode
        # preserve any loader-specific fields already in default_params (e.g. context_length)
        for k, v in (service.get('default_params', {}) or {}).items():
            if k not in new_params:
                new_params[k] = v
        SERVICES[service_key]['default_params'] = new_params
        save_services_config()

    # Check if there is a model_path (new config format)
    model_path = service.get('model_path')

    if model_path:
        # Build the vLLM start command dynamically
        cuda_devices = ','.join(map(str, gpus))
        log_file = service.get('log_file', f'/tmp/vllm_{service_key}.log')
        extra_args = service.get('extra_args', '')

        cmd = f'''
source /root/miniconda3/etc/profile.d/conda.sh 2>/dev/null || true
conda activate base 2>/dev/null || true
mkdir -p $(dirname {log_file})
CUDA_VISIBLE_DEVICES={cuda_devices} nohup vllm serve {model_path} \
    --tensor-parallel-size {tensor_parallel_size} \
    --port {port} \
    --host 0.0.0.0 \
    --gpu-memory-utilization {gpu_memory_utilization} \
    --max-model-len {max_model_len} \
    --dtype {dtype} \
    {extra_args} \
    > {log_file} 2>&1 &
echo "Starting service, log: {log_file}"
'''
        try:
            result = subprocess.run(
                ['bash', '-c', cmd],
                capture_output=True,
                text=True,
                timeout=30
            )
            return jsonify({
                'success': True,
                'message': 'Service started',
                'output': result.stdout,
                'params': {
                    'gpus': gpus,
                    'port': port,
                    'tensor_parallel_size': tensor_parallel_size,
                    'gpu_memory_utilization': gpu_memory_utilization,
                    'max_model_len': max_model_len,
                    'dtype': dtype
                }
            })
        except subprocess.TimeoutExpired:
            return jsonify({'success': True, 'message': 'Service is starting in the background'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    else:
        # Backward compat: use start_script
        start_script = service.get('start_script')
        if not start_script:
            return jsonify({'success': False, 'message': 'Service config missing model_path or start_script'})

        try:
            env = os.environ.copy()
            # The manager's own environment (systemd unit) carries PORT=9000/HOST=0.0.0.0
            # for the Flask app. Start scripts use ${PORT:-8000}-style defaults, so an
            # inherited PORT would make vLLM try to bind the manager's port and crash
            # with "Address already in use". Strip ambient PORT/HOST and pass the
            # service's port explicitly instead.
            env.pop('PORT', None)
            env.pop('HOST', None)
            env['PARALLEL_MODE'] = parallel_mode
            env['PORT'] = str(port)
            result = subprocess.run(
                ['bash', start_script],
                capture_output=True,
                text=True,
                timeout=300,
                env=env
            )

            if result.returncode == 0:
                return jsonify({'success': True, 'message': 'Service started', 'output': result.stdout})
            else:
                return jsonify({'success': False, 'message': 'Failed to start service', 'error': result.stderr})
        except subprocess.TimeoutExpired:
            return jsonify({'success': False, 'message': 'Start timed out'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})

@app.route('/api/service/<service_key>/stop', methods=['POST'])
def stop_service(service_key):
    """Stop a service"""
    if service_key not in SERVICES:
        return jsonify({'success': False, 'message': 'Service not found'}), 404

    service = SERVICES[service_key]

    # Check if it is running
    status = check_service_status(service_key)
    if status['status'] != 'running':
        return jsonify({'success': False, 'message': 'Service is not running'})

    try:
        # Run the stop script
        result = subprocess.run(
            ['bash', service['stop_script']],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            return jsonify({'success': True, 'message': 'Service stopped', 'output': result.stdout})
        else:
            return jsonify({'success': False, 'message': 'Failed to stop service', 'error': result.stderr})
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'message': 'Stop timed out'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/service/<service_key>/remove', methods=['POST'])
def remove_service(service_key):
    """Remove a service: stop it (if running), delete its entry from services.json,
    and delete its generated start/stop scripts (for generated services)."""
    if service_key not in SERVICES:
        return jsonify({'success': False, 'message': 'Service not found'}), 404
    service = SERVICES[service_key]

    # Stop the service first (if running)
    status = check_service_status(service_key)
    if status.get('status') == 'running':
        try:
            subprocess.run(['bash', service['stop_script']], capture_output=True, text=True, timeout=30)
        except Exception as e:
            return jsonify({'success': False, 'message': f'Failed to stop service before removing: {e}'})

    # Delete generated start/stop scripts (only for generated services; hand-written
    # services use scripts in ~/Desktop/AI that the user may want to keep)
    deleted_scripts = []
    if service.get('generated'):
        for script in (service.get('start_script'), service.get('stop_script')):
            if script and os.path.exists(script):
                try:
                    os.remove(script)
                    deleted_scripts.append(script)
                except Exception:
                    pass

    # Remove from the in-memory registry + persist to services.json
    del SERVICES[service_key]
    save_services_config()

    # Drop the bound Hermes chat profile for removed Strata services (best-effort).
    if service_key.startswith('strata_'):
        try:
            profile = _hermes_profile_for_service(service_key)
            if profile:
                subprocess.run(['hermes', 'profile', 'delete', profile, '-y'],
                               capture_output=True, text=True, timeout=30, env=_hermes_env())
        except Exception:
            pass

    return jsonify({
        'success': True,
        'message': 'Service removed',
        'deleted_scripts': deleted_scripts,
    })

@app.route('/api/stop_all', methods=['POST'])
def stop_all():
    """Stop ALL services (unload every model). Used by the top-of-page 'Unload all' button.

    Iterates every service in services.json, runs its stop_script if running, and returns
    a per-service result. Idempotent — already-stopped services are reported as such.
    """
    results = {}
    for key, service in SERVICES.items():
        status = check_service_status(key)
        if status.get('status') == 'running':
            try:
                result = subprocess.run(
                    ['bash', service['stop_script']],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                ok = result.returncode == 0
                results[key] = {'success': ok, 'message': 'stopped' if ok else result.stderr}
            except Exception as e:
                results[key] = {'success': False, 'message': str(e)}
        else:
            results[key] = {'success': True, 'message': 'not running'}
    return jsonify({'success': True, 'results': results})

@app.route('/api/hermes/switch', methods=['POST'])
def switch_hermes_port():
    """Switch Hermes to point at a specific vLLM port (so the user can keep
    talking to the agent while the big brain is stopped for a dual-card cutover).
    
    Example: POST /api/hermes/switch {"port": 8002}
    """
    data = request.get_json(silent=True) or {}
    port = data.get('port')
    if not port or not (1024 <= int(port) <= 65535):
        return jsonify({'success': False, 'message': 'Invalid port'}), 400

    port = int(port)
    base_url = f'http://127.0.0.1:{port}/v1'

    # 1. Update the Hermes config (the manager's minimal PATH lacks the hermes CLI;
    #    add its bin dir explicitly)
    try:
        env = os.environ.copy()
        env['PATH'] = env.get('PATH', '') + os.pathsep + os.path.expanduser('~/.hermes/hermes-agent/.hermes/bin')
        result = subprocess.run(
            ['hermes', 'config', 'set', 'model.base_url', base_url],
            capture_output=True, text=True, timeout=10, env=env
        )
        if result.returncode != 0:
            return jsonify({'success': False, 'message': f'Failed to set config: {result.stderr}'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

    # 2. Restart the Hermes gateway (from the manager's backend, not the gateway itself)
    try:
        result = subprocess.run(
            ['systemctl', '--user', 'restart', 'hermes-gateway'],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return jsonify({
                'success': False,
                'message': f'Config set to {base_url}, but gateway restart failed: {result.stderr}'
            })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

    return jsonify({
        'success': True,
        'message': f'Hermes switched to port {port} ({base_url}). Gateway restarting.',
        'port': port,
        'base_url': base_url
    })

@app.route('/api/hermes/current', methods=['GET'])
def get_hermes_current():
    """Return the port Hermes is currently pointed at (model.base_url in its config)."""
    import re
    try:
        env = os.environ.copy()
        env['PATH'] = env.get('PATH', '') + os.pathsep + os.path.expanduser('~/.hermes/hermes-agent/.hermes/bin')
        result = subprocess.run(
            ['hermes', 'config', 'get', 'model.base_url'],
            capture_output=True, text=True, timeout=10, env=env
        )
        if result.returncode != 0:
            return jsonify({'success': False, 'message': f'Failed to read config: {result.stderr}'})
        base_url = result.stdout.strip()
        m = re.search(r':(\d{2,5})', base_url)
        if not m:
            return jsonify({'success': False, 'message': f'No port found in base_url: {base_url}'})
        return jsonify({'success': True, 'port': int(m.group(1)), 'base_url': base_url})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/hermes/webapp-link', methods=['GET'])
def get_hermes_webapp_link():
    """Mint a fresh one-use sign-in link for the Hermes Webapp (port 9120) so the
    manager UI can open it in a new tab and sign that browser in.

    The Webapp authenticates each browser with a one-use launch ticket
    (``/webapp/launch#ticket=*** valid ~60s), minted by the running gateway. A
    plain new tab at the base URL has no session token and shows "Sign in to
    Hermes". We ask ``hermes webapp`` for a fresh link and hand it back; the
    button opens it immediately (well inside the 60s window).

    Optional ?profile=<name> param mints the link for that profile (default:
    the active/default profile).

    Optional ?service=<service_key> param (preferred, used by the per-service
    chat buttons) resolves the right profile from the service's loader — big ->
    default, lmstudio -> small-brain, strata_* -> a per-service profile that is
    created on first use and bound to that service's model/port/key.
    """
    profile = request.args.get('profile', '')
    service_key = request.args.get('service', '')
    if service_key:
        service = SERVICES.get(service_key)
        if service is None:
            return jsonify({'success': False, 'message': f'Unknown service: {service_key}'}), 400
        try:
            if service_key.startswith('strata_'):
                profile = _ensure_strata_hermes_profile(service_key, service)
            else:
                profile = _hermes_profile_for_service(service_key)
        except Exception as e:
            return jsonify({'success': False, 'message': f'Could not prepare the chat profile: {e}'}), 500
    try:
        env = os.environ.copy()
        env['PATH'] = env.get('PATH', '') + os.pathsep + os.path.expanduser('~/.hermes/hermes-agent/.hermes/bin')
        cmd = ['hermes', 'webapp', '--no-open', '--skip-build']
        if profile:
            cmd = ['hermes', '-p', profile, 'webapp', '--no-open', '--skip-build']
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=20, env=env
        )
        output = (result.stdout or '') + (result.stderr or '')
        # Preferred: the one-use launch link (http://127.0.0.1:9120/webapp/launch#ticket=...
        m = re.search(r'https?://\S+/webapp/launch#[^\s]+', output)
        if not m:
            # Fallback: a plain sign-in URL (Webapp behind dashboard sign-in)
            m = re.search(r'https?://\S+', output)
        if not m:
            return jsonify({'success': False, 'message': f'No webapp link found: {output.strip()[:300]}'}), 500
        return jsonify({'success': True, 'url': m.group(0)})
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'message': 'Timed out minting the webapp link'}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/manager/restart', methods=['POST'])
def restart_manager():
    """Restart the manager backend (vllm-manager-backend) to reload config (e.g. services.json).

    The backend loads config/services.json only at import, so an on-disk edit is invisible
    until the backend restarts. This endpoint triggers that restart. The backend is a user
    systemd service, so the systemctl call is detached (start_new_session) to survive the
    backend being killed by its own restart.
    """
    try:
        subprocess.Popen(
            ['systemctl', '--user', 'restart', 'vllm-manager-backend'],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return jsonify({'success': True, 'message': 'Manager backend restarting. The UI will reconnect in a few seconds.'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to restart manager: {e}'}), 500


# --- LLM Manager self-updater (GitHub) ---
REPO_DIR = Path(__file__).resolve().parent
VERSION_FILE = REPO_DIR / 'VERSION'

def _git(args, timeout=30):
    """Run a git command in the repo dir. Returns (ok, output)."""
    try:
        r = subprocess.run(['git'] + args, cwd=str(REPO_DIR),
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)

def _manager_version():
    """Current manager version (line 1 of the repo VERSION file; default 0.5.0)."""
    try:
        lines = VERSION_FILE.read_text().strip().splitlines()
        return (lines[0].strip() if lines else '') or '0.5.0'
    except Exception:
        return '0.5.0'

def _manager_version_date():
    """Date the current version was first pushed (line 2 of VERSION; '')."""
    try:
        lines = VERSION_FILE.read_text().strip().splitlines()
        return lines[1].strip() if len(lines) > 1 else ''
    except Exception:
        return ''

def _bump_version():
    """Bump the patch version in the VERSION file (0.5.0 -> 0.5.1) and
    stamp it with today's date (when this version first lands)."""
    parts = _manager_version().split('.')
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except ValueError:
        return _manager_version()
    new = '.'.join(parts)
    try:
        VERSION_FILE.write_text(new + '\n' + date.today().isoformat() + '\n')
    except Exception:
        pass
    return new

@app.route('/api/manager/version')
def manager_version():
    """The manager version + date shown in the sidebar footer."""
    return jsonify({'version': _manager_version(), 'date': _manager_version_date()})

@app.route('/api/updater/check')
def updater_check():
    """Compare the local checkout against origin/main on GitHub.

    Returns the local commit, whether updates are available, the list of
    new upstream commits (newest first), and a diffstat summary."""
    ok, out = _git(['fetch', '--quiet', 'origin', 'main'], timeout=60)
    if not ok:
        return jsonify({'success': False, 'message': f'git fetch failed: {out[:300]}'}), 500
    ok, local = _git(['rev-parse', 'HEAD'])
    ok_remote, remote = _git(['rev-parse', 'origin/main'])
    if not (ok and ok_remote):
        return jsonify({'success': False, 'message': 'This is not a git checkout with a HEAD — run the updater from the repo clone.'}), 500
    if local == remote:
        return jsonify({'success': True, 'up_to_date': True, 'commit': local[:8], 'version': _manager_version()})
    ok, commits = _git(['log', '--pretty=format:%h %s', 'HEAD..origin/main'])
    ok, diffstat = _git(['diff', '--stat', 'HEAD..origin/main'])
    ok, behind = _git(['rev-list', '--count', 'HEAD..origin/main'])
    ok, ahead = _git(['rev-list', '--count', 'origin/main..HEAD'])
    return jsonify({
        'success': True,
        'up_to_date': False,
        'commit': local[:8],
        'remote_commit': remote[:8],
        'behind': int(behind or 0),
        'ahead': int(ahead or 0),
        'commits': commits.splitlines(),
        'diffstat': diffstat.splitlines(),
        'version': _manager_version(),
    })

@app.route('/api/updater/apply', methods=['POST'])
def updater_apply():
    """Apply updates: git pull --ff-only, rebuild + redeploy the frontend,
    then restart the backend service (detached — it kills this process)."""
    # Discard any local (uncommitted) version bump so the pull can't conflict
    # with it; we re-bump after the pull.
    _git(['checkout', '--', 'VERSION'])
    ok, out = _git(['pull', '--ff-only', '--quiet', 'origin', 'main'], timeout=120)
    if not ok:
        return jsonify({'success': False, 'message': f'git pull failed (fast-forward only): {out[:300]}'}), 400
    # Bump the patch version to mark this local update (0.5.0 -> 0.5.1 -> 0.5.2 ...).
    version = _bump_version()
    # Rebuild + redeploy the frontend (build.sh restarts the frontend service).
    try:
        r = subprocess.run(['bash', 'build.sh'], cwd=str(REPO_DIR / 'frontend'),
                           capture_output=True, text=True, timeout=600)
        build_out = (r.stdout + r.stderr).strip()
    except Exception as e:
        build_out = str(e)
    # Restart the backend service so it loads the new code. Detached: the
    # restart kills this process, so the response must already be on its way.
    try:
        subprocess.Popen(
            ['systemctl', '--user', 'restart', 'vllm-manager-backend'],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass
    return jsonify({'success': True, 'message': 'Update applied — the UI is reloading.', 'version': version, 'build': build_out[-500:]})

def _resolve_log_file(service):
    """Resolve a service's log file, with loader-specific fallbacks.
    LM Studio (llmster daemon) writes rolling date logs to
    ~/.lmstudio/server-logs/YYYY/*.log — its configured log_file is never
    written by the start script, so fall back to the newest of those."""
    lf = service.get('log_file')
    if lf and os.path.exists(lf):
        return lf
    if (service.get('loader') or '').lower() == 'lmstudio':
        try:
            newest = max(
                glob.glob(os.path.expanduser('~/.lmstudio/server-logs/*/*.log')),
                key=os.path.getmtime, default=None)
            if newest:
                return newest
        except Exception:
            pass
    return lf

@app.route('/api/service/<service_key>/logs')
def get_logs(service_key):
    """Get service logs"""
    if service_key not in SERVICES:
        return jsonify({'success': False, 'message': 'Service not found'}), 404

    service = SERVICES[service_key]
    lines = request.args.get('lines', 100, type=int)
    log_file = _resolve_log_file(service)

    try:
        if log_file and os.path.exists(log_file):
            result = subprocess.run(
                ['tail', '-n', str(lines), log_file],
                capture_output=True,
                text=True,
                timeout=5
            )
            return jsonify({'success': True, 'logs': result.stdout})
        else:
            return jsonify({'success': False, 'message': 'Log file does not exist'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

def _vllm_metrics_payload(service_key):
    """Build the vLLM metrics payload (dict) for a running service. Returns (payload, error)."""
    service = SERVICES[service_key]
    port = service.get('default_params', {}).get('port', 8000)
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/metrics', timeout=3) as r:
            data, buckets = _parse_prom(r.read().decode())
    except Exception as e:
        return None, f'Failed to fetch vLLM metrics: {e}'

    gen = data.get('vllm:generation_tokens_total', 0)
    prompt = data.get('vllm:prompt_tokens_total', 0)
    # Prefix-cache hits: these prompt tokens were NOT prefilled (loaded from
    # the KV cache), so they must be excluded from every prefill-speed
    # calculation. Counting them inflates the rate by the cache-hit ratio —
    # with 96% hits, a real ~2K tok/s showed up as ~52K tok/s.
    cached = data.get('vllm:prompt_tokens_cached_total', 0)
    fresh_prompt = prompt - cached

    # Live rates from consecutive polls + rolling windows for hi/lo
    now = time.time()
    prev = VLLM_STATE.get(service_key, {}).get('prev')
    live_rate = None
    live_prefill = None
    if prev and now > prev['ts']:
        dt = now - prev['ts']
        live_rate = (gen - prev['gen']) / dt
        live_prefill = (fresh_prompt - prev.get('fresh_prompt', 0)) / dt
    state = VLLM_STATE.setdefault(service_key, {
        'gen_samples': deque(maxlen=150),
        'prefill_samples': deque(maxlen=150),
    })
    if live_rate is not None:
        state['gen_samples'].append(live_rate)
    if live_prefill is not None:
        state['prefill_samples'].append(live_prefill)
    live_max = max(state['gen_samples']) if state['gen_samples'] else None
    live_min = min(state['gen_samples']) if state['gen_samples'] else None
    prefill_max = max(state['prefill_samples']) if state['prefill_samples'] else None
    prefill_min = min(state['prefill_samples']) if state['prefill_samples'] else None
    VLLM_STATE[service_key]['prev'] = {'ts': now, 'gen': gen, 'prompt': prompt, 'fresh_prompt': fresh_prompt}

    e2e = data.get('vllm:e2e_request_latency_seconds', {})
    ttft = data.get('vllm:time_to_first_token_seconds', {})
    e2e_sum = e2e.get('sum') or 0
    ttft_sum = ttft.get('sum') or 0

    # Avg generation throughput = total generated tokens / pure generation (decode) time.
    # e2e - TTFT strips the prefill phase so the average is not diluted by prefill;
    # the numerator is generation tokens only (never prompt/prefill tokens).
    gen_time = e2e_sum - ttft_sum
    if gen_time > 0:
        avg_rate = gen / gen_time
    elif e2e_sum:
        avg_rate = gen / e2e_sum
    else:
        avg_rate = None

    # TTFT (prefill speed): avg + histogram min/max
    ttft_avg = ttft.get('sum', 0) / ttft['count'] if ttft.get('count') else None
    # Avg prefill speed = total FRESH (non-cached) prompt tokens / total prefill time
    prefill_avg = fresh_prompt / ttft_sum if ttft_sum else None
    ttft_min, ttft_max = None, None
    b = sorted(buckets.get('vllm:time_to_first_token_seconds', []))
    total = ttft.get('count', 0)
    if b and total:
        prev_le = 0.0
        for le, c in b:
            if c > 0 and ttft_min is None:
                ttft_min = prev_le  # lower bound of first non-empty bucket
            if le == float('inf'):
                break
            if c < total:
                ttft_max = le  # upper bound of last non-empty finite bucket
            prev_le = le

    # Prefix-cache hit rate (cached is fetched above, before the prefill math)
    cache_pct = cached / prompt * 100 if prompt else None

    return {
        'prompt_tokens': int(prompt),
        'generation_tokens': int(gen),
        'live_tokens_per_sec': round(live_rate, 1) if live_rate is not None else None,
        'live_max': round(live_max, 1) if live_max is not None else None,
        'live_min': round(live_min, 1) if live_min is not None else None,
        'prefill_avg': round(prefill_avg, 0) if prefill_avg is not None else None,
        'live_prefill': round(live_prefill, 0) if live_prefill is not None else None,
        'prefill_max': round(prefill_max, 0) if prefill_max is not None else None,
        'prefill_min': round(prefill_min, 0) if prefill_min is not None else None,
        'avg_tokens_per_sec': round(avg_rate, 1) if avg_rate is not None else None,
        'ttft_avg_s': round(ttft_avg, 2) if ttft_avg is not None else None,
        'ttft_min_s': round(ttft_min, 2) if ttft_min is not None else None,
        'ttft_max_s': round(ttft_max, 2) if ttft_max is not None else None,
        'cache_hit_pct': round(cache_pct, 1) if cache_pct is not None else None,
        'requests_running': int(data.get('vllm:num_requests_running', 0)),
        'requests_waiting': int(data.get('vllm:num_requests_waiting', 0)),
    }, None


def _ollama_metrics(port):
    """Ollama live stats: loaded models + VRAM (/api/ps) and version (/api/version)."""
    out = {'loader': 'ollama', 'loaded_models': []}
    try:
        with urllib.request.urlopen(f'http://localhost:{port}/api/ps', timeout=3) as r:
            ps = json.loads(r.read().decode())
        for m in ps.get('models', []):
            out['loaded_models'].append({
                'name': m.get('name'),
                'size_gb': round(m.get('size', 0) / 1024 ** 3, 2),
                'vram_gb': round(m.get('size_vram', 0) / 1024 ** 3, 2),
            })
    except Exception as e:
        out['detail'] = f'/api/ps unavailable: {e}'
    try:
        with urllib.request.urlopen(f'http://localhost:{port}/api/version', timeout=3) as r:
            out['version'] = json.loads(r.read().decode()).get('version')
    except Exception:
        pass
    return out


def _lmstudio_metrics(service):
    """LM Studio live stats: loaded models + throughput metrics from the metrics-proxy CSV."""
    port = service.get('default_params', {}).get('port', 45987)
    out = {'loader': 'lmstudio', 'loaded_models': []}
    # Loaded models from the local server's /v1/models (OpenAI-compatible)
    try:
        with urllib.request.urlopen(f'http://localhost:{port}/v1/models', timeout=3) as r:
            models = json.loads(r.read().decode()).get('data', [])
        for m in models:
            out['loaded_models'].append({'name': m.get('id')})
    except Exception as e:
        out['detail'] = f'local server /v1/models unavailable: {e}'
    # Throughput metrics from the metrics-proxy CSV
    csv_file = '/home/j/logs/metrics_lmstudio.csv'
    try:
        import csv
        with open(csv_file) as f:
            rows = list(csv.DictReader(f))
        if rows:
            # Most recent request
            last = rows[-1]
            out['live_tokens_per_sec'] = float(last.get('tokens_per_second', 0) or 0)
            out['requests_running'] = 0
            out['requests_waiting'] = 0
            # Averages over the last 10 requests
            recent = rows[-10:]
            tps_vals = [float(r.get('tokens_per_second', 0) or 0) for r in recent]
            out['avg_tokens_per_sec'] = sum(tps_vals) / len(tps_vals) if tps_vals else 0
            out['total_requests'] = len(rows)
    except Exception:
        pass
    return out


def _llama_cpp_metrics(service):
    """llama.cpp live stats: the service runs a single model; report its name (no token throughput)."""
    out = {'loader': 'llama_cpp', 'loaded_models': []}
    name = service.get('name', '')
    model = name.replace(' (llama.cpp)', '').strip()
    if model:
        out['loaded_models'].append({'name': model})
    out['detail'] = 'llama.cpp exposes no token throughput; VRAM is shown in the card'
    return out


@app.route('/api/service/<service_key>/vllm_metrics')
def get_vllm_metrics(service_key):
    """Fetch live vLLM Prometheus metrics for a service (per-GPU throughput)."""
    if service_key not in SERVICES:
        return jsonify({'success': False, 'message': 'Service not found'}), 404
    status = check_service_status(service_key)
    if not status or status.get('status') != 'running':
        return jsonify({'success': False, 'message': 'Service is not running'})
    payload, err = _vllm_metrics_payload(service_key)
    if err:
        return jsonify({'success': False, 'message': err})
    return jsonify({'success': True, 'loader': 'vllm', **payload})


def _strata_metrics(service):
    """Live stats for a Strata service (OpenAI-compatible API, bearer key)."""
    port = service.get('default_params', {}).get('port', 8080)
    key = service.get('api_key', '')
    req = urllib.request.Request(
        f'http://127.0.0.1:{port}/v1/models',
        headers={'Authorization': f'Bearer {key}'}
    )
    with urllib.request.urlopen(req, timeout=3) as r:
        data = json.loads(r.read())
    models = [m.get('id') for m in data.get('data', []) if m.get('id')]
    return {'loader': 'strata', 'models': models, 'detail': models[0] if models else ''}


def _hermes_env():
    """Env for calling the hermes CLI from the manager backend."""
    env = os.environ.copy()
    env['PATH'] = env.get('PATH', '') + os.pathsep + os.path.expanduser('~/.hermes/hermes-agent/.hermes/bin')
    return env


def _hermes_profile_for_service(service_key):
    """Map a manager service key to the Hermes profile whose chat talks to that
    service's model (the manager's per-service chat buttons open a Hermes Webapp
    tab bound to the right profile):
      big        -> '' (the active/default profile — Qwen3.8-27B on :8000)
      lmstudio   -> 'small-brain' (Qwen3.8-27B Q2 on LM Studio :45987)
      strata_*   -> 'strata-<family>-<model>' (one profile per Strata service)
    """
    if service_key == 'big':
        return ''
    if service_key == 'lmstudio':
        return 'small-brain'
    if service_key.startswith('strata_'):
        return 'strata-' + service_key[len('strata_'):].replace('_', '-')
    return ''


def _strata_model_id(service_key, service):
    """The model ID Strata serves for this service: live from /v1/models when the
    service is running, else derived from the key (strata_<family>_<model> ->
    <family>-<model>, e.g. strata_inkling_2_mini_sq_15 -> inkling-2-mini-sq-15)."""
    port = service.get('default_params', {}).get('port')
    api_key = service.get('api_key', '')
    if port:
        try:
            req = urllib.request.Request(
                f'http://127.0.0.1:{port}/v1/models',
                headers={'Authorization': f'Bearer {api_key}'}
            )
            with urllib.request.urlopen(req, timeout=3) as r:
                data = json.loads(r.read())
            ids = [m.get('id') for m in data.get('data', []) if m.get('id')]
            if ids:
                return ids[0]
        except Exception:
            pass  # service not running — fall back to the key-derived name
    return service_key[len('strata_'):].replace('_', '-')


def _ensure_strata_hermes_profile(service_key, service):
    """Create + configure a Hermes profile for a Strata service on first use, so the
    chat button can open a Hermes chat bound to this service's model. Idempotent:
    existing profiles are left untouched."""
    profile = _hermes_profile_for_service(service_key)
    if not profile:
        return profile
    pdir = Path.home() / '.hermes' / 'profiles' / profile
    if (pdir / 'config.yaml').exists():
        return profile
    env = _hermes_env()
    r = subprocess.run(['hermes', 'profile', 'create', profile, '--no-alias'],
                       capture_output=True, text=True, timeout=60, env=env)
    if r.returncode != 0:
        raise RuntimeError(f'hermes profile create failed: {(r.stdout + r.stderr).strip()[:300]}')
    port = service.get('default_params', {}).get('port')
    api_key = service.get('api_key', '')
    # NOTE: model.context_length is pinned to 0 (not omitted) — 0 = "use whatever
    # the model reports" (auto-detect from the live /v1/models). A static value
    # would override the detection and go stale whenever the service's context
    # param changes. The fresh-profile template defaults to 245K, so it must be
    # explicitly zeroed.
    settings = [
        ('model.default', _strata_model_id(service_key, service)),
        ('model.provider', 'custom'),
        ('model.base_url', f'http://127.0.0.1:{port}/v1' if port else ''),
        ('model.api_key', '${HERMES_MODEL_API_KEY}'),
        ('model.context_length', '0'),
    ]
    for key, val in settings:
        if not val:
            continue
        subprocess.run(['hermes', '-p', profile, 'config', 'set', key, val],
                       capture_output=True, text=True, timeout=30, env=env)
    if api_key:
        env_file = pdir / '.env'
        line = f'HERMES_MODEL_API_KEY={api_key}'
        try:
            text = env_file.read_text() if env_file.exists() else ''
            if 'HERMES_MODEL_API_KEY' in text:
                text = re.sub(r'^HERMES_MODEL_API_KEY=.*$', line, text, flags=re.M)
            else:
                text = (text + ('\n' if text and not text.endswith('\n') else '')) + line + '\n'
            env_file.write_text(text)
        except Exception as e:
            raise RuntimeError(f'could not write profile .env: {e}')
    return profile


@app.route('/api/service/<service_key>/metrics')
def get_service_metrics(service_key):
    """Unified live stats for any service — dispatches on the service's loader.

    vllm -> rich throughput; ollama/lmstudio -> loaded models + VRAM; llama_cpp -> model name.
    """
    if service_key not in SERVICES:
        return jsonify({'success': False, 'message': 'Service not found'}), 404
    service = SERVICES[service_key]
    loader_key = service.get('loader') or 'vllm'
    status = check_service_status(service_key)
    if not status or status.get('status') != 'running':
        return jsonify({'success': False, 'message': 'Service is not running', 'loader': loader_key})
    try:
        if loader_key in ('vllm', 'paiton'):
            payload, err = _vllm_metrics_payload(service_key)
            if err:
                return jsonify({'success': False, 'message': err, 'loader': loader_key})
            return jsonify({'success': True, 'loader': loader_key, **payload})
        if loader_key == 'strata':
            return jsonify({'success': True, **_strata_metrics(service)})
        if loader_key == 'ollama':
            port = service.get('default_params', {}).get('port', 11434)
            return jsonify({'success': True, **_ollama_metrics(port)})
        if loader_key == 'lmstudio':
            return jsonify({'success': True, **_lmstudio_metrics(service)})
        if loader_key == 'llama_cpp':
            return jsonify({'success': True, **_llama_cpp_metrics(service)})
        return jsonify({'success': True, 'loader': loader_key,
                        'detail': f'No live metrics for loader {loader_key}'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e), 'loader': loader_key})

@app.route('/api/service/<service_key>/chat')
def get_service_chat(service_key):
    """Serve a minimal self-contained web chat that talks to the service's model
    (OpenAI-compatible /v1/chat/completions on the service's port)."""
    if service_key not in SERVICES:
        return jsonify({'success': False, 'message': 'Service not found'}), 404
    service = SERVICES[service_key]
    port = service.get('default_params', {}).get('port', 8000)
    name = service.get('name', service_key)
    loader = service.get('loader', '')
    return render_template('chat.html', port=port, name=name, loader=loader,
                           api_key=service.get('api_key', ''))

@app.route('/api/system')
def get_system_info():
    """Get system info"""
    try:
        # Non-blocking CPU sample (delta since the previous call). interval=1
        # would block every /api/system poll for a full second, which made the
        # dashboard's 1/2/3s refresh buttons feel like a fixed ~3s.
        cpu_percent = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        # CPU name + live clock from /proc/cpuinfo
        cpu_name = ''
        cpu_mhz = 0.0
        try:
            with open('/proc/cpuinfo') as f:
                for line in f:
                    if line.startswith('model name'):
                        cpu_name = line.split(':', 1)[1].strip()
                    elif line.startswith('cpu MHz'):
                        try:
                            cpu_mhz = float(line.split(':', 1)[1].strip())
                        except ValueError:
                            pass
        except Exception:
            pass

        # CPU temperature: k10temp hwmon (millidegrees), fallback = first non-wifi thermal zone
        cpu_temp = 0.0
        try:
            import glob, os
            for hw in glob.glob('/sys/class/hwmon/hwmon*'):
                try:
                    with open(os.path.join(hw, 'name')) as f:
                        if f.read().strip() == 'k10temp':
                            with open(os.path.join(hw, 'temp1_input')) as f:
                                cpu_temp = int(f.read().strip()) / 1000.0
                            break
                except Exception:
                    continue
            if cpu_temp == 0.0:
                for tz in glob.glob('/sys/class/thermal/thermal_zone*'):
                    try:
                        with open(os.path.join(tz, 'type')) as f:
                            t = f.read().strip()
                        if 'wifi' not in t.lower():
                            with open(os.path.join(tz, 'temp')) as f:
                                cpu_temp = int(f.read().strip()) / 1000.0
                            break
                    except Exception:
                        continue
        except Exception:
            pass

        # System RAM (DRAM) temperature: only present on some platforms (server BMCs,
        # some laptop ECs). Search thermal zones + hwmon chips for a ram/dram/memory
        # sensor; None (-> null) when not exposed so the UI can show nothing.
        ram_temp = None
        try:
            import glob, os
            def _match(name):
                n = name.lower()
                return ('ram' in n) or ('dram' in n) or ('memory' in n)
            for hw in glob.glob('/sys/class/hwmon/hwmon*'):
                try:
                    with open(os.path.join(hw, 'name')) as f:
                        if _match(f.read().strip()):
                            for t in glob.glob(os.path.join(hw, 'temp*_input')):
                                with open(t) as f:
                                    ram_temp = int(f.read().strip()) / 1000.0
                                    break
                            break
                except Exception:
                    continue
            if ram_temp is None:
                for tz in glob.glob('/sys/class/thermal/thermal_zone*'):
                    try:
                        with open(os.path.join(tz, 'type')) as f:
                            if _match(f.read().strip()):
                                with open(os.path.join(tz, 'temp')) as f:
                                    ram_temp = int(f.read().strip()) / 1000.0
                                break
                    except Exception:
                        continue
        except Exception:
            pass

        return jsonify({
            'cpu_percent': cpu_percent,
            'cpu_name': cpu_name,
            'cpu_mhz': cpu_mhz,
            'cpu_temp_c': cpu_temp,
            'ram_temp_c': ram_temp,
            'memory_percent': memory.percent,
            'memory_used_gb': memory.used / 1024 / 1024 / 1024,
            'memory_total_gb': memory.total / 1024 / 1024 / 1024,
            'disk_percent': disk.percent,
            'disk_used_gb': disk.used / 1024 / 1024 / 1024,
            'disk_total_gb': disk.total / 1024 / 1024 / 1024
        })
    except Exception as e:
        return jsonify({'error': str(e)})

# --- Loaders (hardware/loader-agnostic core) ---

@app.route('/api/loaders')
def get_loaders():
    """Detection status + capabilities of every registered model loader."""
    out = {}
    for loader in all_loaders():
        try:
            d = loader.detect()
        except Exception as e:
            d = {'installed': False, 'version': None, 'detail': f'detect failed: {e}'}
        out[loader.key] = {
            'name': loader.name,
            'installed': d['installed'],
            'version': d.get('version'),
            'detail': d.get('detail'),
            'param_schema': loader.param_schema,
            'requires_model': loader.requires_model,
            'fixed_port': loader.fixed_port,
        }
    return jsonify(out)

@app.route('/api/models')
def get_models():
    """All models across all loaders, tagged with source + format.

    Uses the unified scan_all_model_dirs() (filesystem scan of all known
    locations) + live loader APIs (ollama /api/tags, lms ls) + existing
    services. Each model is tagged with:
      - source: where it was found
      - format: 'safetensors' | 'gguf' | 'weights'
      - loaders: which loaders can load it
    """
    from loaders.base import scan_all_model_dirs
    models = []
    seen = set()

    def _add(m):
        key = (m['name'], m.get('source', ''), m.get('loader', ''))
        if key not in seen:
            seen.add(key)
            models.append(m)

    # 1) Unified filesystem scan (all known locations)
    for m in scan_all_model_dirs():
        # Convert 'loaders' list to a single 'loader' tag for the frontend
        # (the frontend filters by the selected loader).
        for loader_key in m.get('loaders', []):
            _add({
                'name': m['name'],
                'path': m.get('path'),
                'size_gb': m.get('size_gb', 0.0),
                'format': m.get('format', 'weights'),
                'source': m.get('source', 'unknown'),
                'loader': loader_key,
            })

    # 2) Live loader APIs (ollama /api/tags, lms ls) — catches models not on disk
    for loader in all_loaders():
        try:
            if not loader.detect()['installed']:
                continue
            for m in loader.list_models():
                m = dict(m)
                m['loader'] = loader.key
                _add(m)
        except Exception:
            pass

    # 3) Existing services (so you can re-add a removed service or duplicate)
    for key, svc in SERVICES.items():
        loader_key = svc.get('loader')
        if not loader_key:
            continue
        model_path = svc.get('model_path', '')
        model_name = model_path.rstrip('/').split('/')[-1] if model_path else svc.get('name', '')
        if not model_name:
            continue
        _add({
            'name': model_name,
            'path': model_path or None,
            'size_gb': None,
            'format': 'service',
            'source': 'service',
            'loader': loader_key,
            'from_service': key,
        })

    return jsonify(models)

@app.route('/api/models/browse')
def browse_models():
    """List model files/dirs inside a directory (for the manual model picker).

    ?dir=<abs path> — returns model files (.gguf/.safetensors/.bin) and
    subdirectories so the UI can navigate the filesystem to find a model
    that the automatic scan didn't cover.
    """
    import os
    d = request.args.get('dir') or os.path.expanduser('~')
    d = os.path.expanduser(d.strip())
    if not os.path.isdir(d):
        return jsonify({'success': False, 'message': f'Not a directory: {d}'}), 400
    files, dirs = [], []
    try:
        for name in sorted(os.listdir(d)):
            p = os.path.join(d, name)
            if os.path.isdir(p):
                dirs.append({'name': name, 'path': p})
            elif name.endswith(('.gguf', '.safetensors', '.bin')):
                try:
                    size = os.path.getsize(p)
                except OSError:
                    size = 0
                files.append({
                    'name': name, 'path': p,
                    'size_gb': round(size / 1024 ** 3, 2),
                })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    parent = os.path.dirname(d) if d != os.path.expanduser('~') else None
    return jsonify({'success': True, 'dir': d, 'parent': parent, 'files': files, 'dirs': dirs})

@app.route('/api/services/generate', methods=['POST'])
def generate_service():
    """Generate a service entry + start/stop scripts from loader + model + params.

    Body: {loader, model?, gpus?, port?, params?}
    Writes into config/services.json (marked generated:true) and returns the key.
    The backend must be restarted to pick up the new service (config-reload gotcha).
    """
    data = request.get_json(silent=True) or {}
    loader = get_loader(data.get('loader'))
    if not loader:
        return jsonify({'success': False, 'message': f"Unknown loader: {data.get('loader')}"}), 400
    if not loader.detect()['installed']:
        return jsonify({'success': False, 'message': f"{loader.name} is not installed on this machine"}), 400
    model = data.get('model') or None
    if loader.requires_model and not model:
        return jsonify({'success': False, 'message': 'model is required for this loader'}), 400
    gpus = data.get('gpus') or []
    port = loader.fixed_port if loader.fixed_port else int(data.get('port') or next_free_port())
    key = make_service_key(loader.key, model or loader.key)
    existing = set(SERVICES.keys())
    if key in existing:
        i = 2
        while f'{key}_{i}' in existing:
            i += 1
        key = f'{key}_{i}'
    result = loader.build_service(key, model, {
        'gpus': gpus,
        'port': port,
        **(data.get('params') or {}),
    })
    # Store the model name in the service config so the card can display it.
    if model:
        result['service']['model'] = model
    SERVICES[key] = result['service']
    save_services_config()
    # Strata services get a bound Hermes chat profile at creation time (the chat
    # button resolves to it later; creation failure never blocks service creation —
    # the button creates it on first use as a fallback).
    if key.startswith('strata_'):
        try:
            _ensure_strata_hermes_profile(key, result['service'])
        except Exception as e:
            return jsonify({
                'success': True,
                'key': key,
                'service': result['service'],
                'note': 'Restart the manager backend to activate the new service.',
                'warning': f'Service created, but the Hermes chat profile could not be prepared: {e}',
            })
    return jsonify({
        'success': True,
        'key': key,
        'service': result['service'],
        'note': 'Restart the manager backend to activate the new service.',
    })

# --- Autostart (systemd user units) ---

MANAGER_UNITS = ['vllm-manager-backend', 'vllm-manager-frontend']

@app.route('/api/autostart')
def get_autostart():
    out = {}
    for u in MANAGER_UNITS:
        enabled = subprocess.run(['systemctl', '--user', 'is-enabled', f'{u}.service'],
                                capture_output=True, text=True, timeout=10)
        active = subprocess.run(['systemctl', '--user', 'is-active', f'{u}.service'],
                               capture_output=True, text=True, timeout=10)
        out[u] = {
            'enabled': enabled.stdout.strip() == 'enabled',
            'active': active.stdout.strip() == 'active',
        }
    return jsonify(out)

@app.route('/api/autostart', methods=['POST'])
def set_autostart():
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get('enabled'))
    verb = 'enable' if enabled else 'disable'
    r = subprocess.run(['systemctl', '--user', verb] + [f'{u}.service' for u in MANAGER_UNITS],
                       capture_output=True, text=True, timeout=15)
    return jsonify({'success': r.returncode == 0, 'output': (r.stdout + r.stderr).strip()})

# --- ComfyUI per-image generation tracking (queue-diff across polls) ---
# The card polls /api/comfyui/status every 2s; each poll diffs the queue so
# completed prompts yield a queue->done time. State resets on backend restart.
COMFYUI_STATE = {
    'gen_times': deque(maxlen=50),  # seconds per completed image (last 50)
    'total_images': 0,
    'seen': {},                     # prompt_id -> first-seen epoch (pending or running)
}

@app.route('/api/comfyui/status')
def get_comfyui_status():
    """Proxy the ComfyUI API (liveness, queue, device) + track per-image gen time.
    Finds ANY running ComfyUI server (headless or GUI) on whatever port it
    listens on — not hardcoded to :8188."""
    import requests
    port, _pid = _find_comfyui_server()
    result = {
        'running': False, 'queue_running': 0, 'queue_pending': 0, 'devices': [],
        'avg_gen_s': None, 'last_gen_s': None, 'total_images': 0, 'current_gen_s': None,
        'port': port,
    }
    if port is None:
        return jsonify(result)
    base = f'http://127.0.0.1:{port}'
    try:
        # ComfyUI >= 0.45 removed /api/health — use /api/queue for liveness
        queue_resp = requests.get(f'{base}/api/queue', timeout=3)
        result['running'] = queue_resp.status_code == 200
    except Exception:
        queue_resp = None

    if not result['running'] or queue_resp is None:
        return jsonify(result)

    try:
        queue = queue_resp.json()
    except Exception:
        queue = {}
    running = queue.get('queue_running', [])
    pending = queue.get('queue_pending', [])
    result['queue_running'] = len(running)
    result['queue_pending'] = len(pending)

    # --- queue-diff: prompts that left the queue since we first saw them ---
    now = time.time()
    active_ids = [item[0] for item in running + pending]
    for pid in active_ids:
        COMFYUI_STATE['seen'].setdefault(pid, now)
    for pid in list(COMFYUI_STATE['seen']):
        if pid not in active_ids:
            gen_s = now - COMFYUI_STATE['seen'].pop(pid)
            if gen_s < 600:  # >10min = stale id (ComfyUI/backend restart), don't count
                COMFYUI_STATE['gen_times'].append(gen_s)
                COMFYUI_STATE['total_images'] += 1
    if COMFYUI_STATE['gen_times']:
        result['avg_gen_s'] = round(sum(COMFYUI_STATE['gen_times']) / len(COMFYUI_STATE['gen_times']), 1)
        result['last_gen_s'] = round(COMFYUI_STATE['gen_times'][-1], 1)
    if running:
        pid = running[0][0]
        if pid in COMFYUI_STATE['seen']:
            result['current_gen_s'] = round(now - COMFYUI_STATE['seen'][pid], 1)
    result['total_images'] = COMFYUI_STATE['total_images']

    try:
        sys_stats = requests.get(f'{base}/api/system_stats', timeout=3).json()
        for d in sys_stats.get('devices', []):
            result['devices'].append({'name': d.get('name', '')})
    except Exception:
        pass

    return jsonify(result)

# --- ComfyUI stop (kill button) ---
def _comfyui_cmdline_match(cmd):
    """True if a process cmdline looks like a ComfyUI server — headless
    (python main.py from a ComfyUI checkout) or the GUI desktop app
    (standalone env / desktop launcher)."""
    if not cmd:
        return False
    if 'main.py' in cmd and ('ComfyUI' in cmd or 'comfyui' in cmd):
        return True
    if 'comfyui-desktop' in cmd or 'comfyui-standalone' in cmd:
        return True
    if 'ComfyUI-Installs' in cmd:
        return True
    return False

def _find_comfyui_server():
    """Find a running ComfyUI server (ANY launch mode: headless or GUI):
    (port, pid) or (None, None). Primary: a TCP listener whose process
    cmdline matches; fallback: process scan (port unknown -> default 8188)."""
    try:
        for conn in psutil.net_connections(kind='tcp'):
            if conn.laddr and conn.pid and conn.status == 'LISTEN':
                try:
                    p = psutil.Process(conn.pid)
                    cmd = ' '.join(p.cmdline() or [])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                if _comfyui_cmdline_match(cmd):
                    return conn.laddr.port, conn.pid
    except Exception:
        pass
    for p in psutil.process_iter(['pid', 'cmdline']):
        try:
            cmd = ' '.join(p.info.get('cmdline') or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if _comfyui_cmdline_match(cmd):
            return 8188, p.pid
    return None, None

def _find_comfyui_pids():
    """PIDs of any running ComfyUI (headless or GUI): every listener on a
    matching port + every process whose cmdline matches (covers the GUI
    launcher and its child server)."""
    pids = set()
    try:
        for conn in psutil.net_connections(kind='tcp'):
            if conn.laddr and conn.pid and conn.status == 'LISTEN':
                try:
                    p = psutil.Process(conn.pid)
                    cmd = ' '.join(p.cmdline() or [])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                if _comfyui_cmdline_match(cmd):
                    pids.add(conn.pid)
    except Exception:
        pass
    for p in psutil.process_iter(['pid', 'cmdline']):
        try:
            cmd = ' '.join(p.info.get('cmdline') or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if _comfyui_cmdline_match(cmd):
            pids.add(p.pid)
    return sorted(pids)

@app.route('/api/comfyui/stop', methods=['POST'])
def stop_comfyui():
    """Stop the headless ComfyUI server (SIGTERM, then SIGKILL if needed)."""
    pids = _find_comfyui_pids()
    if not pids:
        return jsonify({'ok': False, 'error': 'ComfyUI not running', 'pids': []})
    for pid in pids:
        try:
            psutil.Process(pid).terminate()
        except psutil.NoSuchProcess:
            pass
    time.sleep(3)  # grace period
    for pid in pids:
        try:
            p = psutil.Process(pid)
            if p.status() == psutil.STATUS_ZOMBIE:
                continue
            p.kill()
        except psutil.NoSuchProcess:
            pass
    return jsonify({'ok': True, 'killed': pids})


@app.route('/api/comfyui/start', methods=['POST'])
def start_comfyui():
    """Start the headless ComfyUI server on the chosen GPU.

    Body: {gpu: <int index>, dir?: <checkout path, default ~/ComfyUI-plain>}.
    Mirrors the ~/Desktop/AI/comfyui-9700.sh / -9070.sh launchers (same flags,
    same log file) but takes the GPU index from the request instead of
    hardcoding it. Works on AMD (HIP_VISIBLE_DEVICES) and NVIDIA
    (CUDA_VISIBLE_DEVICES) — both are set.
    """
    body = request.get_json(silent=True) or {}
    gpu = body.get('gpu')
    if isinstance(gpu, bool) or not isinstance(gpu, int) or gpu < 0:
        return jsonify({'success': False, 'message': 'gpu must be a non-negative integer index'}), 400

    pids = _find_comfyui_pids()
    if pids:
        return jsonify({'success': False, 'message': f'ComfyUI is already running (pid {pids[0]}) — stop it first'}), 400

    # Default port 8188 must be free (or already a ComfyUI we missed).
    try:
        for conn in psutil.net_connections(kind='tcp'):
            if conn.laddr and conn.laddr.port == 8188 and conn.status == 'LISTEN' and conn.pid:
                try:
                    cmd = ' '.join(psutil.Process(conn.pid).cmdline() or [])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    cmd = ''
                if not _comfyui_cmdline_match(cmd):
                    return jsonify({'success': False, 'message': 'Port 8188 is in use by another process'}), 400
    except Exception:
        pass

    comfy_dir = Path(os.path.expanduser(body.get('dir') or '~/ComfyUI-plain'))
    if not (comfy_dir / 'main.py').exists():
        return jsonify({'success': False, 'message': f'No ComfyUI checkout at {comfy_dir} — install it first'}), 400
    venv_python = comfy_dir / '.venv' / 'bin' / 'python'
    if not venv_python.exists():
        return jsonify({'success': False, 'message': f'No venv at {comfy_dir} — install ComfyUI first'}), 400

    cmd = [
        str(venv_python), '-s', '-u', str(comfy_dir / 'main.py'),
        '--disable-assets', '--reserve-vram', '3',
    ]
    # Comfy Desktop instance model paths (same as the launch scripts)
    desktop_paths = Path.home() / '.local' / 'share' / 'comfyui-desktop-2' / 'instance-model-paths'
    if desktop_paths.is_dir():
        yamls = sorted(desktop_paths.glob('*.yaml'))
        if yamls:
            cmd += ['--extra-model-paths-config', str(yamls[-1])]
    # Shared input/output dirs (same as the launch scripts)
    shared = Path.home() / 'ComfyUI-Shared'
    if shared.is_dir():
        cmd += ['--input-directory', str(shared / 'input'), '--output-directory', str(shared / 'output')]

    env = dict(os.environ)
    env['HIP_VISIBLE_DEVICES'] = str(gpu)      # AMD ROCm
    env['CUDA_VISIBLE_DEVICES'] = str(gpu)     # NVIDIA
    env['GPU_RESOURCE_CACHE_SIZE'] = '0'       # ROCm DynamicVRAM state fix
    # Never leak the manager's Python env into ComfyUI — it is a different
    # venv, and PYTHONPATH/VIRTUAL_ENV from here would break its imports.
    for var in ('PYTHONPATH', 'VIRTUAL_ENV', 'PYTHONUNBUFFERED'):
        env.pop(var, None)

    log_dir = Path.home() / 'logs'
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / 'comfyui.log'
    try:
        with open(log_file, 'ab') as lf:
            proc = subprocess.Popen(
                cmd, stdout=lf, stderr=subprocess.STDOUT,
                env=env, cwd=str(comfy_dir),
                start_new_session=True,  # detached — survives backend restarts
            )
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to launch ComfyUI: {e}'}), 500

    return jsonify({'success': True, 'pid': proc.pid, 'gpu': gpu, 'dir': str(comfy_dir),
                    'message': f'ComfyUI starting on GPU {gpu} (pid {proc.pid}) — the UI polls the server, give it ~10s'})

@app.route('/api/comfyui/logs')
def get_comfyui_logs():
    """Tail the headless ComfyUI log (launch scripts tee output to this file)."""
    log_file = '/home/j/logs/comfyui.log'
    lines = request.args.get('lines', 200, type=int)
    try:
        if os.path.exists(log_file):
            result = subprocess.run(
                ['tail', '-n', str(lines), log_file],
                capture_output=True,
                text=True,
                timeout=5
            )
            return jsonify({'success': True, 'logs': result.stdout})
        else:
            return jsonify({'success': False, 'message': 'No log file yet — launch ComfyUI via the Start button on the ComfyUI card (or ~/Desktop/AI/comfyui-9070.sh / -9700.sh); output is captured there'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# --- Installer (vLLM + Hermes webapp) ---
import installer

@app.route('/api/installer/status')
def get_installer_status():
    """Detection state: system (GPU vendor, python, uv), vLLM, Hermes, ComfyUI, running jobs."""
    venv = request.args.get('venv') or os.path.expanduser('~/vllm-venv')
    comfy_dir = request.args.get('comfy_dir') or os.path.expanduser('~/ComfyUI-plain')
    with installer.JOBS_LOCK:
        jobs = [dict(j) for j in installer.JOBS.values()]
    return jsonify({
        'system': installer.detect_system(),
        'docker': installer.detect_docker(),
        'vllm': installer.detect_vllm(venv),
        'paiton': installer.detect_paiton(venv),
        'qwen': installer.detect_qwen(venv),
        'paiton_docker': installer.detect_paiton_docker(),
        'strata': installer.detect_strata(),
        'hermes': installer.detect_hermes(),
        'comfyui': installer.detect_comfyui(comfy_dir),
        'lmstudio': installer.detect_lmstudio(),
        'openviking': installer.detect_openviking(),
        'jobs': jobs,
    })

@app.route('/api/installer/vllm', methods=['POST'])
def install_vllm():
    """Start a vLLM install job. Body: {venv?, channel?: 'nightly'|'stable'}."""
    body = request.get_json(silent=True) or {}
    job_id, err = installer.start_job('vllm', body)
    if err:
        return jsonify({'success': False, 'message': err}), 400
    return jsonify({'success': True, 'job': job_id, 'log_file': installer.JOBS[job_id]['log_file']})

@app.route('/api/installer/hermes', methods=['POST'])
def install_hermes():
    """Start a Hermes + webapp install job."""
    job_id, err = installer.start_job('hermes', {})
    if err:
        return jsonify({'success': False, 'message': err}), 400
    return jsonify({'success': True, 'job': job_id, 'log_file': installer.JOBS[job_id]['log_file']})

@app.route('/api/installer/comfyui', methods=['POST'])
def install_comfyui():
    """Start a ComfyUI install job. Body: {dir?}."""
    body = request.get_json(silent=True) or {}
    job_id, err = installer.start_job('comfyui', body)
    if err:
        return jsonify({'success': False, 'message': err}), 400
    return jsonify({'success': True, 'job': job_id, 'log_file': installer.JOBS[job_id]['log_file']})

@app.route('/api/installer/lmstudio', methods=['POST'])
def install_lmstudio():
    """Start an LM Studio + Beledarian Suite install job (any Linux distro)."""
    job_id, err = installer.start_job('lmstudio', {})
    if err:
        return jsonify({'success': False, 'message': err}), 400
    return jsonify({'success': True, 'job': job_id, 'log_file': installer.JOBS[job_id]['log_file']})

@app.route('/api/installer/openviking', methods=['POST'])
def install_openviking():
    """Start an OpenViking install job (Hermes long-term memory: server + embeddings + plugin)."""
    job_id, err = installer.start_job('openviking', {})
    if err:
        return jsonify({'success': False, 'message': err}), 400
    return jsonify({'success': True, 'job': job_id, 'log_file': installer.JOBS[job_id]['log_file']})

@app.route('/api/installer/update', methods=['POST'])
def update_tool():
    """Start an update job — re-runs the idempotent install script in place.
    Body: {kind: 'vllm'|'hermes'|'comfyui'|'lmstudio'|'openviking', venv?, channel?, dir?}.

    vLLM re-resolves the latest vendor-correct PyTorch wheels (ROCm from AMD,
    CUDA from NVIDIA) + the latest vLLM; Hermes runs `hermes update`; ComfyUI
    does `git pull` + refreshes deps; LM Studio updates the Beledarian Suite;
    OpenViking re-pips the packages.
    """
    body = request.get_json(silent=True) or {}
    kind = body.get('kind')
    if kind not in ('vllm', 'hermes', 'comfyui', 'lmstudio', 'openviking', 'strata'):
        return jsonify({'success': False, 'message': 'kind must be vllm, hermes, comfyui, lmstudio, openviking, or strata'}), 400
    job_id, err = installer.start_update_job(kind, body)
    if err:
        return jsonify({'success': False, 'message': err}), 400
    return jsonify({'success': True, 'job': job_id, 'log_file': installer.JOBS[job_id]['log_file']})

@app.route('/api/installer/strata', methods=['POST'])
def install_strata():
    """Install Strata: pull the AMD Docker image + install the terminal CLI.
    Body: {tag?: image tag to pull (update flow)}. AMD ROCm only (R9700 + RX 9070, both gfx1201)."""
    body = request.get_json(silent=True) or {}
    job_id, err = installer.start_strata_job(body)
    if err:
        return jsonify({'success': False, 'message': err}), 409
    return jsonify({'success': True, 'job': job_id, 'log_file': installer.JOBS[job_id]['log_file']})


@app.route('/api/installer/strata/check', methods=['GET'])
def check_strata_update():
    """Check for a newer Strata release: latest GitHub release (with notes) +
    the newest published ROCm gfx120x Docker image tag, compared to what is
    installed. Used by the Strata card's "Check for updates" button."""
    try:
        return jsonify(installer.check_strata_update())
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/installer/strata/models', methods=['GET'])
def strata_models():
    """The Strata model catalog (for the card's model download selector):
    display name, family/model, size + bits, and whether a service for it
    already exists (its volume may already hold the download)."""
    from loaders.strata import STRATA_MODELS
    from loaders.base import make_service_key
    models = []
    for name, cfg in STRATA_MODELS.items():
        key = make_service_key('strata', name)
        models.append({
            'name': name,
            'family': cfg['family'],
            'model': cfg['model'],
            'size': cfg.get('size', ''),
            'bits': cfg.get('bits', ''),
            'service': key in SERVICES,
        })
    return jsonify({'success': True, 'models': models})


@app.route('/api/installer/strata/download', methods=['POST'])
def download_strata_model():
    """Download a Strata model into the volume the service for it would use,
    WITHOUT leaving a service running (temporary container, stopped as soon as
    the files are downloaded and verified). Body: {model: display name}."""
    body = request.get_json(silent=True) or {}
    job_id, err = installer.start_strata_download_job(body)
    if err:
        return jsonify({'success': False, 'message': err}), 409
    return jsonify({'success': True, 'job': job_id, 'log_file': installer.JOBS[job_id]['log_file']})


@app.route('/api/installer/paiton', methods=['POST'])
def install_paiton():
    """Install/refresh a Paiton release model as a Docker container.
    Body: {model?: slug, port?}. Pulls the pinned Paiton image for the chosen
    model (Qwen3.8 also downloads its pinned weights) and recreates the container.
    AMD ROCm only.
    """
    body = request.get_json(silent=True) or {}
    job_id, err = installer.start_paiton_job(body)
    if err:
        return jsonify({'success': False, 'message': err}), 409
    return jsonify({'success': True, 'job': job_id, 'log_file': installer.JOBS[job_id]['log_file']})


@app.route('/api/installer/paiton-download', methods=['POST'])
def download_paiton():
    """Download the Paiton model weights for the chosen model (pull image + download
    weights, NO container start). Body: {model?: slug}. AMD ROCm only.
    """
    body = request.get_json(silent=True) or {}
    job_id, err = installer.start_paiton_download_job(body)
    if err:
        return jsonify({'success': False, 'message': err}), 409
    return jsonify({'success': True, 'job': job_id, 'log_file': installer.JOBS[job_id]['log_file']})


@app.route('/api/installer/paiton/stop', methods=['POST'])
def stop_paiton_endpoint():
    """Stop all running Paiton containers."""
    success, message = installer.stop_paiton()
    return jsonify({'success': success, 'message': message})


@app.route('/api/installer/paiton/restart', methods=['POST'])
def restart_paiton_endpoint():
    """Restart all running Paiton containers (stop + start)."""
    success, message = installer.restart_paiton()
    return jsonify({'success': success, 'message': message})


@app.route('/api/installer/paiton/uninstall', methods=['POST'])
def uninstall_paiton_endpoint():
    """Remove all Paiton containers (stopped and running)."""
    success, message = installer.uninstall_paiton()
    return jsonify({'success': success, 'message': message})


@app.route('/api/installer/paiton/check', methods=['GET'])
def check_paiton_update_endpoint():
    """Check for newer Paiton upstream (new commits on the paiton-vllm-plugin
    repo, compared to the local checkout the install scripts use)."""
    try:
        return jsonify(installer.check_paiton_update())
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/installer/paiton/update', methods=['POST'])
def update_paiton_endpoint():
    """Apply the Paiton update: git pull --ff-only in the plugin repo
    (refreshes the launchers; new pinned image releases land as repo commits)."""
    success, message = installer.update_paiton_repo()
    return jsonify({'success': success, 'message': message})


@app.route('/api/installer/paiton-models')
def paiton_models():
    """List the Paiton release models with download status."""
    PAITON_MODELS = [
        {'slug': 'qwen38', 'name': 'Qwen3.8 27B', 'bits': '3-bit W3A4 + FP8 draft', 'size': '~66 GB'},
        {'slug': 'qwen38-mxfp4', 'name': 'Qwen3.8 27B (MXFP4)', 'bits': 'MXFP4 (4-bit)', 'size': '~62 GB'},
        {'slug': 'gpt-oss-20b', 'name': 'GPT-OSS 20B', 'bits': 'MXFP4 (4-bit)', 'size': '~44 GB'},
        {'slug': 'minicpm5-2b', 'name': 'MiniCPM5 2B', 'bits': 'W4A16 (4-bit)', 'size': '~40 GB'},
        {'slug': 'ornith-1.5', 'name': 'Ornith 1.5 35B', 'bits': 'MXFP4 (4-bit)', 'size': '~28 GB'},
        {'slug': 'qwen3-coder-30b', 'name': 'Qwen3-Coder 30B', 'bits': 'INT4 (4-bit)', 'size': '~30 GB'},
        {'slug': 'qwen38-neo-coder', 'name': 'Qwen3.8 NEO CODER MAX', 'bits': 'Q4_K_M (4-bit)', 'size': '~25 GB'},
    ]
    models = installer.check_model_download_status([dict(m) for m in PAITON_MODELS], kind='paiton')
    return jsonify({'success': True, 'models': models})


@app.route('/api/installer/vllm-models')
def vllm_models():
    """List the curated vLLM models (safetensors) the user can download."""
    from model_catalog import VLLM_MODELS
    models = installer.check_model_download_status([dict(m) for m in VLLM_MODELS], kind='vllm')
    return jsonify({'success': True, 'models': models})


@app.route('/api/installer/vllm-model', methods=['POST'])
def vllm_model():
    """Download a vLLM model (safetensors from HF). Body: {model: slug}."""
    body = request.get_json(silent=True) or {}
    job_id, err = installer.start_vllm_model_job(body)
    if err:
        return jsonify({'success': False, 'message': err}), 409
    return jsonify({'success': True, 'job': job_id, 'log_file': installer.JOBS[job_id]['log_file']})


@app.route('/api/installer/lmstudio-models')
def lmstudio_models():
    """List the curated LM Studio models (GGUF) the user can download."""
    from model_catalog import LMSTUDIO_MODELS
    models = installer.check_model_download_status([dict(m) for m in LMSTUDIO_MODELS], kind='lmstudio')
    return jsonify({'success': True, 'models': models})


@app.route('/api/installer/lmstudio-model', methods=['POST'])
def lmstudio_model():
    """Download an LM Studio model (GGUF from HF). Body: {model: slug}."""
    body = request.get_json(silent=True) or {}
    job_id, err = installer.start_lmstudio_model_job(body)
    if err:
        return jsonify({'success': False, 'message': err}), 409
    return jsonify({'success': True, 'job': job_id, 'log_file': installer.JOBS[job_id]['log_file']})

@app.route('/api/installer/uninstall', methods=['POST'])
def uninstall():
    """Start an uninstall job. Body: {kind: 'vllm'|'hermes'|'comfyui'|'lmstudio'|'openviking', venv?, remove_venv?, dir?, remove_checkout?, remove_workspace?}.

    vLLM: pip-uninstalls vLLM from the given venv (optionally removes the venv).
    Hermes: disables the webapp (safe reverse — does not remove the running agent).
    OpenViking: stops/removes services + Hermes plugin/config (memory data kept unless remove_workspace).
    """
    body = request.get_json(silent=True) or {}
    kind = body.get('kind')
    if kind not in ('vllm', 'hermes', 'comfyui', 'lmstudio', 'openviking', 'strata'):
        return jsonify({'success': False, 'message': 'kind must be vllm, hermes, comfyui, lmstudio, openviking, or strata'}), 400
    job_id, err = installer.start_uninstall_job(kind, body)
    if err:
        return jsonify({'success': False, 'message': err}), 400
    return jsonify({'success': True, 'job': job_id, 'log_file': installer.JOBS[job_id]['log_file']})

@app.route('/api/installer/logs')
def get_installer_logs():
    """Tail a job's log (job id from the install POST response)."""
    txt, job = installer.tail_job_log(request.args.get('job') or '', lines=200)
    if not job:
        return jsonify({'success': False, 'message': 'Unknown job id'}), 404
    return jsonify({'success': True, 'logs': txt, 'status': job['status'], 'job': job['kind']})

@app.route('/api/installer/gateway/restart', methods=['POST'])
def restart_hermes_gateway():
    """Restart the Hermes gateway (loads the webapp after install).

    The manager backend is a separate process from the gateway, so this is
    allowed (the self-termination guard only blocks restarts from inside a
    gateway session). The desktop app / webapp UI will reconnect in a few
    seconds.
    """
    hermes = shutil.which('hermes')
    if not hermes:
        for cand in (
            Path.home() / '.hermes' / 'hermes-agent' / '.hermes' / 'bin' / 'hermes',
            Path.home() / '.local' / 'bin' / 'hermes',
        ):
            if cand.exists():
                hermes = str(cand)
                break
    if not hermes:
        return jsonify({'success': False, 'message': 'hermes not found — install Hermes first'}), 400
    try:
        subprocess.Popen(
            ['bash', '-c', f'{hermes} gateway restart'],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return jsonify({'success': True, 'message': 'Hermes gateway restarting — the UI will reconnect in a few seconds.'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to restart gateway: {e}'}), 500

if __name__ == '__main__':
    # Start the service
    port = int(os.environ.get('PORT', 9000))
    host = os.environ.get('HOST', '0.0.0.0')

    print("=" * 60)
    print("🚀 LLM Model Manager")
    print("=" * 60)
    print(f"URL: http://{host}:{port}")
    print(f"Config file: {CONFIG_FILE}")
    print(f"Services managed: {len(SERVICES)}")
    print("=" * 60)

    app.run(host=host, port=port, debug=False)
