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
import json
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


def detect_lmstudio():
    """LM Studio: installed? (lms CLI / AppImage / /opt, any distro) + Beledarian Suite present?"""
    home = Path.home()
    suite_dir = home / 'beledarians-lm-studio-tools'
    out = {
        'installed': False,
        'lms': None,
        'detail': '',
        'suite': {
            'installed': False,
            'dir': str(suite_dir),
            'revision': None,
            'detail': '',
        },
    }
    # lms CLI: PATH, then the official curl|bash location, then common AppImage / .deb spots
    lms = shutil.which('lms')
    if not lms and (home / '.lmstudio' / 'bin' / 'lms').exists():
        lms = str(home / '.lmstudio' / 'bin' / 'lms')
    if not lms:
        for cand in (
            home / 'Applications' / 'LM-Studio.AppImage',
            home / 'Downloads' / 'LM-Studio.AppImage',
            home / 'LM-Studio.AppImage',
        ):
            if cand.exists():
                lms = str(cand)
                break
    if not lms and Path('/opt/LM Studio').is_dir():
        lms = '/opt/LM Studio'
    if lms:
        out['installed'] = True
        out['lms'] = lms
        out['detail'] = 'lms CLI' if lms.endswith('/lms') or lms == 'lms' else 'AppImage / app dir'
    else:
        out['detail'] = 'no LM Studio found (lms CLI, AppImage, /opt/LM Studio)'
    if suite_dir.exists() and (suite_dir / 'manifest.json').exists():
        out['suite']['installed'] = True
        try:
            m = re.search(r'"revision"\s*:\s*(\d+)', (suite_dir / 'manifest.json').read_text())
            out['suite']['revision'] = int(m.group(1)) if m else None
        except Exception:
            pass
    else:
        out['suite']['detail'] = f'no Beledarian Suite at {suite_dir}'
    return out


def _hermes_memory_provider():
    """Value of `memory: provider:` in ~/.hermes/config.yaml (line-based, no YAML dep)."""
    cfg = Path.home() / '.hermes' / 'config.yaml'
    if not cfg.exists():
        return None
    try:
        lines = cfg.read_text().splitlines()
    except Exception:
        return None
    i, n = 0, len(lines)
    while i < n:
        if re.match(r'^memory:\s*$', lines[i]):
            j = i + 1
            while j < n:
                if re.match(r'^\S', lines[j]) and not lines[j].lstrip().startswith('#'):
                    break  # real top-level key — end of the memory block
                m = re.match(r'^  provider:\s*(\S+)', lines[j])
                if m:
                    return m.group(1).strip('"\'')
                j += 1
            return None
        i += 1
    return None


def detect_openviking():
    """OpenViking (Hermes long-term memory): server, embeddings, plugin, Hermes config."""
    out = {
        'installed': False,
        'server': False,
        'server_version': None,
        'embed': False,
        'plugin': False,
        'hermes_configured': False,
        'detail': '',
    }
    # OpenViking server health (:1934)
    try:
        with urllib.request.urlopen('http://127.0.0.1:1934/health', timeout=3) as r:
            if r.status == 200:
                data = json.loads(r.read())
                out['server'] = bool(data.get('healthy'))
                out['server_version'] = data.get('version')
    except Exception:
        pass
    # Embedding service health (:8091)
    try:
        with urllib.request.urlopen('http://127.0.0.1:8091/health', timeout=3) as r:
            if r.status == 200:
                data = json.loads(r.read())
                out['embed'] = bool(data.get('ready'))
    except Exception:
        pass
    # Hermes plugin
    out['plugin'] = (Path.home() / '.hermes' / 'plugins' / 'openviking' / '__init__.py').exists()
    # Hermes memory provider
    provider = _hermes_memory_provider()
    out['hermes_configured'] = (provider == 'openviking')
    out['installed'] = out['server'] and out['plugin'] and out['hermes_configured']
    if not out['installed']:
        missing = []
        if not out['server']:
            missing.append('server')
        if not out['plugin']:
            missing.append('Hermes plugin')
        if not out['hermes_configured']:
            missing.append('Hermes memory config')
        out['detail'] = 'missing: ' + ', '.join(missing) if missing else ''
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
    """Start an install job. kind: 'vllm' | 'hermes' | 'comfyui' | 'lmstudio' | 'openviking'. Returns (job_id, error)."""
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
        qwentools = 'true' if params.get('qwentools') else 'false'
        cmd = ['bash', str(SCRIPTS_DIR / 'install_vllm.sh'), venv, channel, paiton, qwentools]
    elif kind == 'hermes':
        cmd = ['bash', str(SCRIPTS_DIR / 'install_hermes.sh')]
    elif kind == 'comfyui':
        dir = os.path.expanduser(params.get('dir') or '~/ComfyUI-plain')
        cmd = ['bash', str(SCRIPTS_DIR / 'install_comfyui.sh'), dir]
    elif kind == 'lmstudio':
        cmd = ['bash', str(SCRIPTS_DIR / 'install_lmstudio.sh')]
    elif kind == 'openviking':
        cmd = ['bash', str(SCRIPTS_DIR / 'install_openviking.sh')]
    else:
        return None, f'unknown kind: {kind}'
    t = threading.Thread(target=_job_worker, args=(job_id, log_file, cmd), daemon=True)
    t.start()
    return job_id, None


def start_uninstall_job(kind, params):
    """Start an uninstall job. kind: 'vllm' | 'hermes' | 'comfyui' | 'lmstudio' | 'openviking'. Returns (job_id, error).

    vLLM: pip-uninstalls vLLM from the given venv (optionally removes the venv).
    Hermes: disables the webapp (the safe reverse — does NOT remove the running agent).
    ComfyUI: removes the venv (optionally the whole checkout).
    LM Studio: removes the app + Beledarian Suite clone (never models/settings).
    OpenViking: stops/removes the services + Hermes plugin/config (memory data kept
    unless remove_workspace=true).
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
    elif kind == 'comfyui':
        dir = os.path.expanduser(params.get('dir') or '~/ComfyUI-plain')
        remove_checkout = 'true' if params.get('remove_checkout') else 'false'
        cmd = ['bash', str(SCRIPTS_DIR / 'uninstall_comfyui.sh'), dir, remove_checkout]
    elif kind == 'lmstudio':
        cmd = ['bash', str(SCRIPTS_DIR / 'uninstall_lmstudio.sh')]
    elif kind == 'openviking':
        remove_workspace = 'true' if params.get('remove_workspace') else 'false'
        cmd = ['bash', str(SCRIPTS_DIR / 'uninstall_openviking.sh'), remove_workspace]
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
