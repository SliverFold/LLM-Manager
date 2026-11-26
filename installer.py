"""
Installer backend for the LLM Model Manager.

Detects the system (GPU vendor + driver, Python, uv) and what is already
installed (vLLM in a venv, Hermes Agent + webapp), and runs long install jobs
in background threads. Each job writes to its own log file; the UI polls
/api/installer/logs?job=<id> for progress.
"""

import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent / 'scripts'
LOG_DIR = Path.home() / 'logs'

JOBS = {}          # job_id -> {kind, status, log_file, exit_code, started_at, finished_at}
JOBS_LOCK = threading.Lock()
_ACTIVE = {}       # kind -> job_id (one job per kind at a time)


def _run(cmd, timeout=None):
    """Run a command, return (rc, combined stdout+stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or '') + (r.stderr or '')
    except subprocess.TimeoutExpired:
        return 124, 'timeout'
    except Exception as e:
        return 1, str(e)


def detect_system():
    """GPU vendor + driver version, Python, uv, free disk."""
    out = {
        'vendor': 'unknown',
        'vendor_detail': '',
        'python': None,
        'python312': None,
        'uv': None,
        'disk_free_gb': 0.0,
    }
    # GPU vendor: AMD first (rocm-smi / /opt/rocm), then NVIDIA.
    # NOTE: we detect the vendor here, but deliberately do NOT report the
    # system ROCm version (rocm-smi --version). That is the distro ROCm in
    # /opt/rocm, which is NOT what vLLM runs on — vLLM uses the pip-bundled
    # ROCm SDK (_rocm_sdk_core) whose version is reported per-venv in
    # detect_vllm(). Showing the system version is misleading (e.g. "ROCm 7.8").
    rocm_smi = shutil.which('rocm-smi')
    if not rocm_smi and Path('/opt/rocm/bin/rocm-smi').exists():
        rocm_smi = '/opt/rocm/bin/rocm-smi'
    if rocm_smi:
        out['vendor'] = 'amd'
        out['vendor_detail'] = 'AMD GPU'
    else:
        nvidia_smi = shutil.which('nvidia-smi')
        if nvidia_smi:
            out['vendor'] = 'nvidia'
            _, txt = _run([nvidia_smi, '--query', '--format=csv,noheader'], timeout=5)
            lines = [l for l in txt.strip().splitlines() if l.strip()]
            out['vendor_detail'] = f'{len(lines)} GPU(s), driver {lines[0].strip()}' if lines else 'NVIDIA'

    _, txt = _run(['python3', '--version'], timeout=5)
    out['python'] = txt.strip() if txt.strip() else None
    out['python312'] = shutil.which('python3.12')
    out['uv'] = shutil.which('uv')
    try:
        import psutil
        out['disk_free_gb'] = round(psutil.disk_usage('/').free / 1024 ** 3, 1)
    except Exception:
        pass
    return out


def detect_vllm(venv=None):
    """Is vLLM installed (in the given venv, or on PATH)?

    Also reports the ROCm version vLLM actually runs on, parsed from
    torch.__version__'s '+rocmX.Y.Z' local tag (the pip-bundled ROCm SDK).
    That is the meaningful version — not the system ROCm in /opt/rocm.
    """
    venv_path = Path(venv or os.path.expanduser('~/vllm-venv')).expanduser()
    out = {'installed': False, 'venv': str(venv_path), 'version': None, 'rocm_version': None, 'detail': ''}
    if (venv_path / 'bin' / 'python').exists():
        # vLLM version + torch version (carries the +rocmX.Y.Z tag)
        probe = 'import vllm, torch; print(vllm.__version__); print(torch.__version__)'
        rc, txt = _run([str(venv_path / 'bin' / 'python'), '-c', probe], timeout=20)
        lines = [l for l in txt.strip().splitlines() if l.strip()]
        if rc == 0 and lines:
            out['installed'] = True
            out['version'] = lines[0]
            if len(lines) >= 2:
                m = re.search(r'\+rocm(\d+\.\d+)', lines[1])
                if m:
                    out['rocm_version'] = m.group(1)
        else:
            out['detail'] = 'venv exists but vLLM is not installed in it'
    else:
        out['detail'] = f'no venv at {venv_path}'
    if not out['installed']:
        rc, txt = _run(['vllm', '--version'], timeout=5)
        if rc == 0 and txt.strip():
            out['installed'] = True
            out['version'] = txt.strip()
            out['detail'] = 'found on PATH (system)'
    return out


def detect_hermes():
    """Hermes Agent: installed? version? webapp enabled? webapp reachable?"""
    out = {'installed': False, 'version': None, 'webapp_enabled': None, 'webapp_reachable': False, 'detail': ''}
    hermes = shutil.which('hermes')
    if not hermes:
        for cand in (
            Path.home() / '.hermes' / 'hermes-agent' / '.hermes' / 'bin' / 'hermes',
            Path.home() / '.local' / 'bin' / 'hermes',
            Path.home() / '.hermes' / 'bin' / 'hermes',
        ):
            if cand.exists():
                hermes = str(cand)
                break
    if not hermes:
        return out
    out['installed'] = True
    _, txt = _run([hermes, '--version'], timeout=15)
    m = re.search(r'Hermes Agent v([\d.]+)', txt)
    out['version'] = m.group(1) if m else None
    # webapp enabled in config.yaml?
    cfg = Path.home() / '.hermes' / 'config.yaml'
    if cfg.exists():
        try:
            m = re.search(r'^\s*webapp:\s*\n\s*enabled:\s*(true|false)', cfg.read_text(), re.M)
            if m:
                out['webapp_enabled'] = m.group(1) == 'true'
        except Exception:
            pass
    # webapp reachable?
    try:
        with urllib.request.urlopen('http://127.0.0.1:9120/', timeout=3) as r:
            out['webapp_reachable'] = r.status == 200
    except Exception:
        out['webapp_reachable'] = False
    return out


def detect_comfyui(venv=None):
    """ComfyUI: installed? (checkout + venv present)."""
    comfy_dir = Path((venv or os.path.expanduser('~/ComfyUI-plain'))).expanduser()
    out = {'installed': False, 'dir': str(comfy_dir), 'detail': ''}
    if comfy_dir.exists() and (comfy_dir / 'main.py').exists():
        out['installed'] = True
        if (comfy_dir / '.venv' / 'bin' / 'python').exists():
            out['detail'] = 'venv ready'
        else:
            out['detail'] = 'checkout present, no venv yet'
    else:
        out['detail'] = f'no ComfyUI at {comfy_dir}'
    return out


def _job_worker(job_id, log_file, cmd):
    """Run the install command, streaming its output to the job log file."""
    try:
        with open(log_file, 'a') as lf:
            lf.write(f'=== install started {datetime.now():%Y-%m-%d %H:%M:%S} ===\n')
            lf.write('$ ' + ' '.join(cmd) + '\n\n')
            lf.flush()
            proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
            proc.wait()
            rc = proc.returncode
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job:
                job['status'] = 'done' if rc == 0 else 'failed'
                job['exit_code'] = rc
                job['finished_at'] = datetime.now().isoformat()
    except Exception as e:
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job:
                job['status'] = 'failed'
                job['exit_code'] = -1
                job['finished_at'] = datetime.now().isoformat()
                job['detail'] = str(e)


def start_job(kind, params):
    """Start an install job. kind: 'vllm' | 'hermes'. Returns (job_id, error)."""
    with JOBS_LOCK:
        active = _ACTIVE.get(kind)
        if active and JOBS.get(active, {}).get('status') == 'running':
            return None, f'{kind} install already running (job {active})'
        job_id = f'{kind}-{int(time.time())}'
        log_file = LOG_DIR / f'install_{kind}_{int(time.time())}.log'
        JOBS[job_id] = {
            'kind': kind,
            'status': 'running',
            'log_file': str(log_file),
            'started_at': datetime.now().isoformat(),
        }
        _ACTIVE[kind] = job_id
    LOG_DIR.mkdir(exist_ok=True)
    if kind == 'vllm':
        venv = os.path.expanduser(params.get('venv') or '~/vllm-venv')
        channel = params.get('channel') or 'nightly'
        paiton = 'true' if params.get('paiton') else 'false'
        cmd = ['bash', str(SCRIPTS_DIR / 'install_vllm.sh'), venv, channel, paiton]
    elif kind == 'hermes':
        cmd = ['bash', str(SCRIPTS_DIR / 'install_hermes.sh')]
    elif kind == 'comfyui':
        dir = os.path.expanduser(params.get('dir') or '~/ComfyUI-plain')
        cmd = ['bash', str(SCRIPTS_DIR / 'install_comfyui.sh'), dir]
    else:
        return None, f'unknown kind: {kind}'
    t = threading.Thread(target=_job_worker, args=(job_id, log_file, cmd), daemon=True)
    t.start()
    return job_id, None


def start_uninstall_job(kind, params):
    """Start an uninstall job. kind: 'vllm' | 'hermes'. Returns (job_id, error).

    vLLM: pip-uninstalls vLLM from the given venv (optionally removes the venv).
    Hermes: disables the webapp (the safe reverse — does NOT remove the running agent).
    """
    with JOBS_LOCK:
        active = _ACTIVE.get(kind)
        if active and JOBS.get(active, {}).get('status') == 'running':
            return None, f'{kind} job already running (job {active})'
        job_id = f'uninstall-{kind}-{int(time.time())}'
        log_file = LOG_DIR / f'uninstall_{kind}_{int(time.time())}.log'
        JOBS[job_id] = {
            'kind': kind,
            'status': 'running',
            'log_file': str(log_file),
            'started_at': datetime.now().isoformat(),
        }
        _ACTIVE[kind] = job_id
    LOG_DIR.mkdir(exist_ok=True)
    if kind == 'vllm':
        venv = os.path.expanduser(params.get('venv') or '~/vllm-venv')
        remove_venv = 'true' if params.get('remove_venv') else 'false'
        cmd = ['bash', str(SCRIPTS_DIR / 'uninstall_vllm.sh'), venv, remove_venv]
    elif kind == 'hermes':
        cmd = ['bash', str(SCRIPTS_DIR / 'uninstall_hermes.sh')]
    else:
        return None, f'unknown kind: {kind}'
    t = threading.Thread(target=_job_worker, args=(job_id, log_file, cmd), daemon=True)
    t.start()
    return job_id, None


def tail_job_log(job_id, lines=200):
    """Tail a job's log file. Returns (text, job) or (None, None)."""
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return None, None
    lf = Path(job['log_file'])
    if lf.exists():
        _, txt = _run(['tail', '-n', str(lines), str(lf)], timeout=5)
        return txt, job
    return '', job
