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


def detect_paiton(venv=None):
    """Is the Paiton plugin installed in the given venv? (AMD-only, fast MXFP4/NVFP4 kernels)"""
    venv_path = Path(venv or os.path.expanduser('~/vllm-venv')).expanduser()
    out = {'installed': False, 'version': None, 'detail': ''}
    if (venv_path / 'bin' / 'python').exists():
        py = str(venv_path / 'bin' / 'python')
        rc, txt = _run([py, '-m', 'pip', 'show', 'paiton-vllm-plugin'], timeout=10)
        if rc == 0 and 'paiton-vllm-plugin' in txt:
            out['installed'] = True
            m = re.search(r'Version:\s*(\S+)', txt)
            out['version'] = m.group(1) if m else None
        else:
            out['detail'] = 'paiton-vllm-plugin not in venv'
    else:
        out['detail'] = f'no venv at {venv_path}'
    return out


def detect_qwen(venv=None):
    """Are the Qwen tools installed? (qwen-agent in the venv + qwen-code global CLI)"""
    venv_path = Path(venv or os.path.expanduser('~/vllm-venv')).expanduser()
    out = {'installed': False, 'agent': False, 'code': False, 'detail': ''}
    if (venv_path / 'bin' / 'python').exists():
        py = str(venv_path / 'bin' / 'python')
        rc, txt = _run([py, '-m', 'pip', 'show', 'qwen-agent'], timeout=10)
        if rc == 0 and 'qwen-agent' in txt:
            out['agent'] = True
    # qwen-code is a global npm CLI (not in the venv)
    out['code'] = shutil.which('qwen') is not None
    out['installed'] = out['agent'] or out['code']
    return out


def detect_docker():
    """Is Docker installed and is the daemon reachable? (Prerequisite for the Paiton big-brain install.)"""
    out = {'installed': False, 'running': False, 'detail': ''}
    if not shutil.which('docker'):
        out['detail'] = 'docker not found'
        return out
    rc, txt = _run(['docker', 'version', '--format', '{{.Server.Version}}'], timeout=10)
    if rc == 0 and txt.strip():
        out['installed'] = True
        out['running'] = True
        out['detail'] = f"server {txt.strip()}"
    else:
        out['installed'] = True
        out['running'] = False
        out['detail'] = 'docker client present, daemon not reachable'
    return out


def detect_paiton_docker():
    """Is any Paiton Docker container installed/running? (checks all paiton-* containers)"""
    out = {'installed': False, 'running': False, 'image': None, 'version': None, 'detail': '', 'models': []}
    if not shutil.which('docker'):
        out['detail'] = 'docker not found'
        return out
    # List all paiton-* containers (running or stopped).
    rc, txt = _run(['docker', 'ps', '-a', '--filter', 'name=paiton-', '--format', '{{.Names}}\t{{.Image}}\t{{.Status}}'], timeout=10)
    lines = [l for l in (txt.strip().splitlines() or []) if l.strip()]
    if lines:
        out['installed'] = True
        for line in lines:
            name, image, status = (line.split('\t') + [''])[:3]
            out['models'].append({'name': name, 'image': image.split(':')[0] if ':' in image else image, 'running': 'Up' in status, 'status': status.strip()})
        # Aggregate: running if any is up; detail shows the first model's status.
        out['running'] = any(m['running'] for m in out['models'])
        out['image'] = out['models'][0]['image']
        out['detail'] = f"{len(out['models'])} container(s)" if len(out['models']) > 1 else out['models'][0]['status']
    else:
        out['detail'] = 'no paiton containers'
    return out


def stop_paiton():
    """Stop all running Paiton containers. Returns (success, message)."""
    if not shutil.which('docker'):
        return False, 'docker not found'
    # Stop all running paiton-* containers.
    rc, txt = _run(['docker', 'ps', '--filter', 'name=paiton-', '--filter', 'status=running', '--format', '{{.Names}}'], timeout=10)
    names = [n.strip() for n in (txt.strip().splitlines() or []) if n.strip()]
    if not names:
        return True, 'no running paiton containers'
    for name in names:
        _run(['docker', 'stop', name], timeout=30)
    return True, f'stopped {len(names)} container(s): {", ".join(names)}'


def uninstall_paiton():
    """Remove all Paiton containers (stopped and running). Returns (success, message)."""
    if not shutil.which('docker'):
        return False, 'docker not found'
    # Remove all paiton-* containers.
    rc, txt = _run(['docker', 'ps', '-a', '--filter', 'name=paiton-', '--format', '{{.Names}}'], timeout=10)
    names = [n.strip() for n in (txt.strip().splitlines() or []) if n.strip()]
    if not names:
        return True, 'no paiton containers'
    for name in names:
        _run(['docker', 'rm', '-f', name], timeout=30)
    return True, f'removed {len(names)} container(s): {", ".join(names)}'


def restart_paiton():
    """Restart all running Paiton containers (stop + start). Returns (success, message)."""
    if not shutil.which('docker'):
        return False, 'docker not found'
    rc, txt = _run(['docker', 'ps', '--filter', 'name=paiton-', '--filter', 'status=running', '--format', '{{.Names}}'], timeout=10)
    names = [n.strip() for n in (txt.strip().splitlines() or []) if n.strip()]
    if not names:
        return True, 'no running paiton containers'
    for name in names:
        _run(['docker', 'restart', name], timeout=60)
    return True, f'restarted {len(names)} container(s): {", ".join(names)}'


def _paiton_repo():
    """The Paiton plugin repo (where the launchers live). Overridable via
    platform.json 'paiton_repo'."""
    from loaders.base import expand, load_platform_config
    return Path(expand(load_platform_config().get('paiton_repo', '~/Desktop/AI/paiton-vllm-plugin')))


def _git_in(repo, args, timeout=30):
    """Run a git command in the given repo dir. Returns (ok, output)."""
    try:
        r = subprocess.run(['git'] + args, cwd=str(repo),
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)


def check_paiton_update():
    """Check for newer Paiton upstream: compare the local paiton-vllm-plugin
    checkout against origin/main on GitHub (same pattern as the manager's own
    updater). The Paiton Docker images are pinned per model in install_paiton.sh
    (and the GHCR org is API-private), so the repo's new commits are the
    upstream signal — a new image release lands as commits to the launchers +
    a new pin. Returns a dict (no HTTP status — the endpoint wraps it)."""
    repo = _paiton_repo()
    out = {
        'success': True,
        'installed': detect_paiton_docker()['installed'],
        'current': {'commit': None, 'date': None},
        'latest': {'commit': None, 'date': None},
        'up_to_date': False,
        'ahead': 0,
        'behind': 0,
        'commits': [],
        'diffstat': [],
        'message': '',
    }
    if not (repo / '.git').exists():
        out['success'] = False
        out['message'] = f'Paiton repo not found at {repo}'
        return out
    ok, _ = _git_in(repo, ['fetch', '--quiet', 'origin', 'main'], timeout=60)
    if not ok:
        out['success'] = False
        out['message'] = 'git fetch failed (check network / GitHub access)'
        return out
    ok, local = _git_in(repo, ['rev-parse', 'HEAD'])
    ok_remote, remote = _git_in(repo, ['rev-parse', 'origin/main'])
    if not (ok and ok_remote):
        out['success'] = False
        out['message'] = 'Paiton repo is not a git checkout with a HEAD'
        return out
    out['current']['commit'] = local[:8]
    ok, d = _git_in(repo, ['log', '-1', '--pretty=%cs'])
    if ok:
        out['current']['date'] = d
    out['latest']['commit'] = remote[:8]
    ok, d = _git_in(repo, ['log', '-1', '--pretty=%cs', 'origin/main'])
    if ok:
        out['latest']['date'] = d
    if local == remote:
        out['up_to_date'] = True
        return out
    ok, commits = _git_in(repo, ['log', '--pretty=format:%h %s', 'HEAD..origin/main'])
    if ok:
        out['commits'] = commits.splitlines()
    ok, diffstat = _git_in(repo, ['diff', '--stat', 'HEAD..origin/main'])
    if ok:
        out['diffstat'] = diffstat.splitlines()
    ok, behind = _git_in(repo, ['rev-list', '--count', 'HEAD..origin/main'])
    ok_ahead, ahead = _git_in(repo, ['rev-list', '--count', 'origin/main..HEAD'])
    out['behind'] = int(behind or 0)
    out['ahead'] = int(ahead or 0)
    return out


def update_paiton_repo():
    """Apply the Paiton update: git pull --ff-only in the paiton-vllm-plugin
    checkout (refreshes the launchers the install scripts delegate to).
    Returns (success, message)."""
    repo = _paiton_repo()
    if not (repo / '.git').exists():
        return False, f'Paiton repo not found at {repo}'
    # Discard any local (uncommitted) changes so the pull can't conflict.
    _git_in(repo, ['checkout', '--', '.'])
    ok, out = _git_in(repo, ['pull', '--ff-only', '--quiet', 'origin', 'main'], timeout=120)
    if not ok:
        return False, f'git pull failed (fast-forward only): {out[:300]}'
    ok, commit = _git_in(repo, ['rev-parse', '--short', 'HEAD'])
    return True, f'Paiton repo updated to {commit}'


def detect_strata():
    """Strata: Docker image present? terminal CLI installed? containers?"""
    out = {'installed': False, 'image': None, 'version': None, 'cli': False, 'detail': '', 'containers': []}
    if not shutil.which('docker'):
        out['detail'] = 'docker not found'
        return out
    rc, txt = _run(['docker', 'images', 'ghcr.io/niko1221/strata', '--format', '{{.Tag}}'], timeout=10)
    tags = [l for l in (txt.strip().splitlines() or []) if l.strip()]
    if tags:
        out['installed'] = True
        out['image'] = 'ghcr.io/niko1221/strata'
        out['version'] = tags[0]
    # terminal CLI (strata launch/monitor/connect)
    cli = shutil.which('strata')
    if not cli:
        for cand in (Path.home() / '.local' / 'bin' / 'strata',
                     Path.home() / 'Applications' / 'strata',
                     Path.home() / '.strata' / 'bin' / 'strata'):
            if cand.exists():
                cli = str(cand)
                break
    out['cli'] = bool(cli)
    out['cli_version'] = None
    if cli:
        try:
            _, vtxt = _run([cli, '--version'], timeout=10)
            m = re.search(r'strata ([\d.]+)', vtxt or '')
            out['cli_version'] = m.group(1) if m else None
        except Exception:
            pass
    # containers (running or stopped)
    rc, txt = _run(['docker', 'ps', '-a', '--filter', 'name=strata-', '--format', '{{.Names}}\t{{.Status}}'], timeout=10)
    lines = [l for l in (txt.strip().splitlines() or []) if l.strip()]
    for line in lines:
        name, status = (line.split('\t') + [''])[:2]
        out['containers'].append({'name': name, 'running': 'Up' in status, 'status': status.strip()})
    if out['installed']:
        out['detail'] = f"image {out['version']}" + (' + CLI' if out['cli'] else ' (no terminal CLI)')
    elif out['cli']:
        out['detail'] = 'terminal CLI only, no Docker image'
    else:
        out['detail'] = 'not installed'
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


def _build_install_cmd(kind, params):
    """Build the install/update command for a kind. Returns a cmd list, or None if unknown.

    The install scripts are idempotent and vendor-aware, so the SAME command is
    used for a fresh install and an in-place update:
      vLLM     re-installs the latest vendor-correct wheels (ROCm from AMD's
               indexes, CUDA from the NVIDIA wheel index) + vLLM.
      Hermes   runs `hermes update` (or a fresh install) + enables the webapp.
      ComfyUI  does `git pull` on the checkout + refreshes the venv deps.
      LM Studio updates the Beledarian Suite (git pull) / installs the app.
      OpenViking re-pips the packages (upgrade) + ensures the services.
    """
    if kind == 'vllm':
        venv = os.path.expanduser(params.get('venv') or '~/vllm-venv')
        channel = params.get('channel') or 'nightly'
        paiton = 'true' if params.get('paiton') else 'false'
        qwentools = 'true' if params.get('qwentools') else 'false'
        return ['bash', str(SCRIPTS_DIR / 'install_vllm.sh'), venv, channel, paiton, qwentools]
    elif kind == 'hermes':
        return ['bash', str(SCRIPTS_DIR / 'install_hermes.sh')]
    elif kind == 'comfyui':
        dir = os.path.expanduser(params.get('dir') or '~/ComfyUI-plain')
        return ['bash', str(SCRIPTS_DIR / 'install_comfyui.sh'), dir]
    elif kind == 'lmstudio':
        return ['bash', str(SCRIPTS_DIR / 'install_lmstudio.sh')]
    elif kind == 'openviking':
        return ['bash', str(SCRIPTS_DIR / 'install_openviking.sh')]
    elif kind == 'strata':
        return ['bash', str(SCRIPTS_DIR / 'install_strata.sh')]
    return None


def _start_install_like_job(kind, params, operation):
    """Start an install or update job. operation: 'install' | 'update'. Returns (job_id, error)."""
    with JOBS_LOCK:
        active = _ACTIVE.get(kind)
        if active and JOBS.get(active, {}).get('status') == 'running':
            return None, f'{kind} {operation} already running (job {active})'
        ts = int(time.time())
        job_id = f'{operation}-{kind}-{ts}'
        log_file = LOG_DIR / f'{operation}_{kind}_{ts}.log'
        JOBS[job_id] = {
            'kind': kind,
            'status': 'running',
            'log_file': str(log_file),
            'started_at': datetime.now().isoformat(),
        }
        _ACTIVE[kind] = job_id
    LOG_DIR.mkdir(exist_ok=True)
    cmd = _build_install_cmd(kind, params)
    if cmd is None:
        return None, f'unknown kind: {kind}'
    t = threading.Thread(target=_job_worker, args=(job_id, log_file, cmd), daemon=True)
    t.start()
    return job_id, None


def start_job(kind, params):
    """Start an install job. kind: 'vllm' | 'hermes' | 'comfyui' | 'lmstudio' | 'openviking'. Returns (job_id, error)."""
    return _start_install_like_job(kind, params, 'install')


def start_update_job(kind, params):
    """Start an update job — re-runs the idempotent install script in place.
    kind: 'vllm' | 'hermes' | 'comfyui' | 'lmstudio' | 'openviking'. Returns (job_id, error).

    vLLM is the important one: it re-resolves and reinstalls the latest
    vendor-correct PyTorch wheels (ROCm from AMD's whl-next / whl-multi-arch
    indexes, or the CUDA wheel from the NVIDIA index) plus the latest vLLM —
    so an update always lands on a matching torch/vLLM pair.
    """
    return _start_install_like_job(kind, params, 'update')


def start_paiton_job(params):
    """Start a Paiton Docker install job for the chosen model (pull image + download
    weights + recreate container). params: {model?: slug, port?, kv_cache?, context?}.
    Returns (job_id, error)."""
    model = params.get('model') or 'qwen38'
    with JOBS_LOCK:
        active = _ACTIVE.get('paiton')
        if active and JOBS.get(active, {}).get('status') == 'running':
            return None, f'paiton install already running (job {active})'
        ts = int(time.time())
        job_id = f'paiton-{ts}'
        log_file = LOG_DIR / f'paiton_{ts}.log'
        JOBS[job_id] = {
            'kind': 'paiton',
            'status': 'running',
            'log_file': str(log_file),
            'started_at': datetime.now().isoformat(),
            'model': model,
        }
        _ACTIVE['paiton'] = job_id
    LOG_DIR.mkdir(exist_ok=True)
    port = str(params.get('port') or '')
    cmd = ['bash', str(SCRIPTS_DIR / 'install_paiton.sh'), model, port]
    kv_cache = params.get('kv_cache') or ''
    context = str(params.get('context') or '')
    if kv_cache:
        cmd += ['--kv-cache', kv_cache]
    if context:
        cmd += ['--context', context]
    t = threading.Thread(target=_job_worker, args=(job_id, log_file, cmd), daemon=True)
    t.start()
    return job_id, None


def start_paiton_download_job(params):
    """Start a Paiton weight-download job for the chosen model (pull image + download
    weights, NO container start). params: {model?: slug}. Returns (job_id, error)."""
    model = params.get('model') or 'qwen38'
    with JOBS_LOCK:
        active = _ACTIVE.get('paiton_download')
        if active and JOBS.get(active, {}).get('status') == 'running':
            return None, f'paiton download already running (job {active})'
        ts = int(time.time())
        job_id = f'paiton-download-{ts}'
        log_file = LOG_DIR / f'paiton_download_{ts}.log'
        JOBS[job_id] = {
            'kind': 'paiton_download',
            'status': 'running',
            'log_file': str(log_file),
            'started_at': datetime.now().isoformat(),
            'model': model,
        }
        _ACTIVE['paiton_download'] = job_id
    LOG_DIR.mkdir(exist_ok=True)
    cmd = ['bash', str(SCRIPTS_DIR / 'install_paiton.sh'), model, '', '--download-only']
    t = threading.Thread(target=_job_worker, args=(job_id, log_file, cmd), daemon=True)
    t.start()
    return job_id, None


def _strata_version_num(tag):
    """'0.2.20-rocm-gfx120x' or 'v0.2.23' -> (0, 2, 20) or None."""
    m = re.search(r'(\d+)\.(\d+)\.(\d+)', tag or '')
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def check_strata_update():
    """Check for a newer Strata release: the latest GitHub release (with its
    notes) plus the newest published ROCm gfx120x Docker image tag, compared
    against what is installed. Returns a dict (no HTTP status — the endpoint
    wraps it)."""
    cur = detect_strata()
    out = {
        'success': True,
        'installed': cur['installed'],
        'current': {'image': cur.get('version'), 'cli': cur.get('cli_version')},
        'latest': None,
        'up_to_date': False,
        'release_pending': False,
        'message': '',
    }
    # 1) Latest GitHub release (tag, name, date, notes)
    try:
        req = urllib.request.Request(
            'https://api.github.com/repos/Niko1221/Strata/releases/latest',
            headers={'User-Agent': 'vllm-model-manager'})
        with urllib.request.urlopen(req, timeout=15) as r:
            rel = json.load(r)
    except Exception as e:
        out['success'] = False
        out['message'] = f'GitHub check failed: {e}'
        return out
    rel_tag = rel.get('tag_name') or ''
    rel_num = _strata_version_num(rel_tag)
    out['latest'] = {
        'tag': rel_tag,
        'version': '.'.join(map(str, rel_num)) if rel_num else rel_tag,
        'name': rel.get('name') or rel_tag,
        'date': (rel.get('published_at') or '')[:10],
        'notes': rel.get('body') or '',
        'image': None,
    }
    # 2) Newest published ROCm gfx120x image tag (paginated tag list)
    try:
        tok_req = urllib.request.Request(
            'https://ghcr.io/token?scope=repository:niko1221/strata:pull',
            headers={'User-Agent': 'vllm-model-manager'})
        with urllib.request.urlopen(tok_req, timeout=15) as r:
            token = json.load(r).get('token', '')
        tags, last = [], None
        for _ in range(5):
            url = 'https://ghcr.io/v2/niko1221/strata/tags/list'
            if last:
                url += f'?last={last}'
            req = urllib.request.Request(url, headers={
                'User-Agent': 'vllm-model-manager',
                'Authorization': f'Bearer {token}'})
            with urllib.request.urlopen(req, timeout=15) as r:
                page = json.load(r).get('tags') or []
            tags.extend(page)
            if len(page) < 100:
                break
            last = page[-1]
        rocm = [t for t in tags if t.endswith('-rocm-gfx120x') and not t.startswith('latest')]
        nums = [(t, _strata_version_num(t)) for t in rocm]
        nums = [(t, n) for t, n in nums if n]
        if nums:
            best_tag, _ = max(nums, key=lambda x: x[1])
            out['latest']['image'] = f'ghcr.io/niko1221/strata:{best_tag}'
    except Exception as e:
        out['message'] = (out['message'] + ' ' if out['message'] else '') + f'GHCR tag check failed: {e}'
    # 3) Compare installed vs latest
    cur_num = _strata_version_num(cur.get('version') or '')
    if cur.get('version') and cur['version'].startswith('latest'):
        out['up_to_date'] = True
    elif cur_num and out['latest'] and out['latest'].get('image'):
        lat_num = _strata_version_num(out['latest']['image'].rsplit(':', 1)[-1])
        if lat_num:
            out['up_to_date'] = cur_num >= lat_num
    elif cur_num and rel_num:
        out['up_to_date'] = cur_num >= rel_num
    # A newer GitHub release exists but its ROCm image is not published yet
    if cur_num and rel_num and cur_num < rel_num:
        out['release_pending'] = True
    return out


def start_strata_job(params):
    """Start a Strata install job (pull the AMD Docker image + install the
    terminal CLI). params: {tag?: image tag to pull (update flow)}. Returns (job_id, error)."""
    with JOBS_LOCK:
        active = _ACTIVE.get('strata')
        if active and JOBS.get(active, {}).get('status') == 'running':
            return None, f'strata install already running (job {active})'
        ts = int(time.time())
        job_id = f'strata-{ts}'
        log_file = LOG_DIR / f'strata_{ts}.log'
        JOBS[job_id] = {
            'kind': 'strata',
            'status': 'running',
            'log_file': str(log_file),
            'started_at': datetime.now().isoformat(),
        }
        _ACTIVE['strata'] = job_id
    LOG_DIR.mkdir(exist_ok=True)
    cmd = ['bash', str(SCRIPTS_DIR / 'install_strata.sh'), (params or {}).get('tag') or '']
    t = threading.Thread(target=_job_worker, args=(job_id, log_file, cmd), daemon=True)
    t.start()
    return job_id, None


def start_strata_download_job(params):
    """Start a Strata model-download job: download the chosen model into the
    volume the service for it would use (NO service left running). params:
    {model: display name from the Strata catalog}. Returns (job_id, error)."""
    from loaders.strata import STRATA_MODELS
    from loaders.base import make_service_key

    model = (params or {}).get('model') or ''
    cfg = STRATA_MODELS.get(model)
    if not cfg:
        return None, f'Unknown Strata model: {model!r}'
    key = make_service_key('strata', model)
    volume = f'strata-data-{key}'
    # If a service for this model already exists, the download must stop it for
    # the duration (Strata allows one engine per volume) and restart it after —
    # the script handles both, and always brings the service back up.
    try:
        _svc_cfg = json.loads((Path(__file__).parent / 'config' / 'services.json').read_text())
    except Exception:
        _svc_cfg = {}
    service_key = key if _svc_cfg.get(key) else ''
    with JOBS_LOCK:
        active = _ACTIVE.get('strata_download')
        if active and JOBS.get(active, {}).get('status') == 'running':
            return None, f'strata download already running (job {active})'
        ts = int(time.time())
        job_id = f'strata-download-{ts}'
        log_file = LOG_DIR / f'strata_download_{ts}.log'
        JOBS[job_id] = {
            'kind': 'strata_download',
            'status': 'running',
            'log_file': str(log_file),
            'started_at': datetime.now().isoformat(),
            'model': model,
        }
        _ACTIVE['strata_download'] = job_id
    LOG_DIR.mkdir(exist_ok=True)
    cmd = ['bash', str(SCRIPTS_DIR / 'strata_download_model.sh'),
           cfg['family'], cfg['model'], volume, service_key]
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
    elif kind == 'strata':
        cmd = ['bash', str(SCRIPTS_DIR / 'uninstall_strata.sh')]
    else:
        return None, f'unknown kind: {kind}'
    t = threading.Thread(target=_job_worker, args=(job_id, log_file, cmd), daemon=True)
    t.start()
    return job_id, None


def _start_model_job(kind, params):
    """Start a model download job for vLLM or LM Studio.
    params: {model: slug}. Returns (job_id, error)."""
    from model_catalog import VLLM_MODELS, LMSTUDIO_MODELS
    model = params.get('model')
    catalog = VLLM_MODELS if kind == 'vllm' else LMSTUDIO_MODELS
    entry = next((m for m in catalog if m['slug'] == model), None)
    if not entry:
        return None, f'unknown model slug {model!r}'
    script = 'download_vllm_model.sh' if kind == 'vllm' else 'download_lmstudio_model.sh'
    with JOBS_LOCK:
        active = _ACTIVE.get(f'{kind}-model')
        if active and JOBS.get(active, {}).get('status') == 'running':
            return None, f'{kind} model download already running (job {active})'
        ts = int(time.time())
        job_id = f'{kind}-model-{ts}'
        log_file = LOG_DIR / f'{kind}_model_{ts}.log'
        JOBS[job_id] = {
            'kind': f'{kind}-model',
            'status': 'running',
            'log_file': str(log_file),
            'started_at': datetime.now().isoformat(),
            'model': entry['name'],
        }
        _ACTIVE[f'{kind}-model'] = job_id
    LOG_DIR.mkdir(exist_ok=True)
    cmd = ['bash', str(SCRIPTS_DIR / script), entry['repo'], entry.get('file', ''), entry['slug']]
    t = threading.Thread(target=_job_worker, args=(job_id, log_file, cmd), daemon=True)
    t.start()
    return job_id, None


def start_vllm_model_job(params):
    """Start a vLLM model download job (safetensors from HF)."""
    return _start_model_job('vllm', params)


def start_lmstudio_model_job(params):
    """Start an LM Studio model download job (GGUF from HF)."""
    return _start_model_job('lmstudio', params)


def check_model_download_status(models, kind='vllm'):
    """Check download status for a list of models. Adds 'downloaded' (bool) and
    'download_pct' (0-100) to each model dict.
    
    For vllm: checks if the HF repo directory exists in ~/.cache/huggingface/hub/
    For lmstudio: checks if the GGUF file exists in LM Studio's model directory
    For paiton: checks if the model cache directories exist in the Paiton plugin
    """
    import os
    import glob
    hf_hub = os.path.expanduser('~/.cache/huggingface/hub')
    lms_models_dir = os.path.expanduser('~/.lmstudio/models')
    paiton_cache = os.path.expanduser('~/Desktop/AI/paiton-vllm-plugin/model-cache')
    
    for m in models:
        repo = m.get('repo', '')
        slug = m.get('slug', '')
        
        if kind == 'vllm':
            # HF cache structure: models--{org}--{repo}/snapshots/
            # e.g. "Qwen/Qwen3.5-9B" -> "models--Qwen--Qwen3.5-9B"
            repo_dir = os.path.join(hf_hub, f'models--{repo.replace("/", "--")}')
            if os.path.exists(repo_dir):
                # Check if there are actual files in the snapshot
                snapshots = os.path.join(repo_dir, 'snapshots')
                if os.path.exists(snapshots):
                    # Count files in all snapshots
                    total_files = 0
                    for snap in os.listdir(snapshots):
                        snap_path = os.path.join(snapshots, snap)
                        if os.path.isdir(snap_path):
                            for f in os.listdir(snap_path):
                                if os.path.isfile(os.path.join(snap_path, f)):
                                    total_files += 1
                    if total_files > 0:
                        m['downloaded'] = True
                        m['download_pct'] = 100
                        continue
                # Directory exists but no files — partial download
                m['downloaded'] = False
                m['download_pct'] = 0
            else:
                m['downloaded'] = False
                m['download_pct'] = 0
        elif kind == 'lmstudio':
            # Check if the GGUF file exists in LM Studio's model directory.
            # LM Studio may use a different org name than the HF repo, so
            # search all subdirectories for the filename.
            file = m.get('file', '')
            if file:
                # Search for the file in all subdirectories of ~/.lmstudio/models/
                # (files are at org/repo/file, so use */* to match two levels)
                found = False
                if os.path.exists(lms_models_dir):
                    if '*' in file:
                        pattern = os.path.join(lms_models_dir, '*', '*', file)
                        matches = glob.glob(pattern)
                        found = len(matches) > 0
                    else:
                        pattern = os.path.join(lms_models_dir, '*', '*', file)
                        matches = glob.glob(pattern)
                        found = len(matches) > 0
                m['downloaded'] = found
                m['download_pct'] = 100 if found else 0
            else:
                # No specific file — check if the repo directory exists anywhere
                org, _, repo_name = repo.partition('/')
                found = False
                if os.path.exists(lms_models_dir):
                    # Search for the repo directory in all subdirectories
                    pattern = os.path.join(lms_models_dir, '*', repo_name)
                    matches = glob.glob(pattern)
                    found = len(matches) > 0
                m['downloaded'] = found
                m['download_pct'] = 100 if found else 0
        elif kind == 'paiton':
            # Paiton models are stored in ~/Desktop/AI/paiton-vllm-plugin/model-cache/
            # with subdirectories named after the model (e.g., qwen38-nvfp4, qwen38-mxfp4)
            slug = m.get('slug', '')
            found = False
            if os.path.exists(paiton_cache):
                # Check common Paiton model directory patterns
                # qwen38 -> qwen38-nvfp4, qwen38-w3rot-int3, qwen38-dflash2
                # qwen38-mxfp4 -> qwen38-mxfp4
                # gpt-oss-20b -> gpt-oss-20b (or similar)
                if slug == 'qwen38':
                    # Check if any of the qwen38 directories exist with files
                    for dir_name in ['qwen38-nvfp4', 'qwen38-w3rot-int3', 'qwen38-dflash2']:
                        dir_path = os.path.join(paiton_cache, dir_name)
                        if os.path.exists(dir_path) and any(os.path.isfile(os.path.join(dir_path, f)) for f in os.listdir(dir_path)):
                            found = True
                            break
                elif slug == 'qwen38-mxfp4':
                    dir_path = os.path.join(paiton_cache, 'qwen38-mxfp4')
                    if os.path.exists(dir_path) and any(os.path.isfile(os.path.join(dir_path, f)) for f in os.listdir(dir_path)):
                        found = True
                else:
                    # For other models, check if a directory with the slug name exists
                    dir_path = os.path.join(paiton_cache, slug)
                    if os.path.exists(dir_path) and any(os.path.isfile(os.path.join(dir_path, f)) for f in os.listdir(dir_path)):
                        found = True
            m['downloaded'] = found
            m['download_pct'] = 100 if found else 0
    
    return models


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
