"""Loader base class + shared helpers."""
import glob
import json
import os
import re
import subprocess
import shutil

# ---------------------------------------------------------------------------
# Platform config (machine-specific knobs, auto-created with sane defaults)
# ---------------------------------------------------------------------------

PLATFORM_CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'config', 'platform.json'
)

DEFAULT_PLATFORM_CONFIG = {
    # Where to look for HF safetensors models (vLLM)
    "hf_cache": "~/.cache/huggingface",
    # Directories to scan for GGUF files (llama.cpp)
    "gguf_dirs": ["~/models/gguf"],
    # Extra model dirs to scan (any loader)
    "extra_model_dirs": [],
    # Base for auto-assigned service ports
    "port_base": 8000,
    # Never assign these ports
    "reserved_ports": [3000, 9000, 11434, 45987, 8188],
    # Where generated start/stop scripts live
    "generated_scripts_dir": "~/Desktop/AI/vllm-model-manager-/scripts/generated",
}


def load_platform_config():
    """Load config/platform.json (merging over defaults); create it if absent."""
    cfg = dict(DEFAULT_PLATFORM_CONFIG)
    try:
        with open(PLATFORM_CONFIG_FILE) as f:
            cfg.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        os.makedirs(os.path.dirname(PLATFORM_CONFIG_FILE), exist_ok=True)
        with open(PLATFORM_CONFIG_FILE, 'w') as f:
            json.dump(DEFAULT_PLATFORM_CONFIG, f, indent=4)
    return cfg


def _run(cmd, timeout=10):
    """subprocess.run wrapper (never raises).

    Runs with the augmented PATH — the manager's systemd user service has a
    minimal PATH, so user-installed tools (ollama, lms, docker in
    /usr/local/bin) would otherwise be invisible to these calls.
    """
    try:
        env = dict(os.environ)
        env['PATH'] = _extra_path()
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except Exception:
        return None


def expand(p):
    return os.path.expanduser(p)


def _extra_path():
    """PATH for subprocess/which: the service's PATH + common user bin dirs.

    The manager runs as a systemd user service with a minimal PATH
    (/opt/rocm/bin:/usr/bin:/bin), so user-installed tools (ollama in
    /usr/local/bin, lms in ~/.lmstudio/bin) are invisible to plain
    shutil.which. Augment the search path for detection + generated scripts.
    """
    base = os.environ.get('PATH', '/usr/bin:/bin')
    extras = ['/usr/local/bin', expand('~/.lmstudio/bin'), expand('~/.local/bin'),
              expand('~/.cargo/bin'), '/opt/rocm/bin']
    parts = base.split(os.pathsep)
    for e in extras:
        if e not in parts:
            parts.append(e)
    return os.pathsep.join(parts)


def which(name):
    """shutil.which with the augmented PATH."""
    return shutil.which(name, path=_extra_path())


# ---------------------------------------------------------------------------
# Shared model scanning
# ---------------------------------------------------------------------------

def scan_hf_cache(cfg=None):
    """Scan the HF hub cache for model repos (safetensors).

    Returns [{'name': 'org/repo', 'path': abs, 'size_gb': float, 'format': 'safetensors'}]
    """
    cfg = cfg or load_platform_config()
    hub = os.path.join(expand(cfg.get('hf_cache', '~/.cache/huggingface')), 'hub')
    models = []
    for d in sorted(glob.glob(os.path.join(hub, 'models--*'))):
        repo = d[len(hub) + 1 + len('models--'):]  # +1 for the path separator
        repo = repo.replace('--', '/', 1) if '--' in repo else repo
        # only count repos with actual weights
        blobs = os.path.join(d, 'snapshots')
        has_safetensors = False
        total = 0
        for root, _, files in os.walk(blobs):
            for f in files:
                if f.endswith(('.safetensors', '.bin', '.gguf')):
                    has_safetensors = True
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
        if has_safetensors:
            models.append({
                'name': repo,
                'path': d,
                'size_gb': round(total / 1024 ** 3, 1),
                'format': 'safetensors' if any(
                    f.endswith('.safetensors') for f in os.listdir(d) if os.path.isdir(os.path.join(d, f))
                ) else 'weights',
                'source': 'hf_cache',
            })
    return models


def scan_gguf_dirs(cfg=None):
    """Scan configured GGUF directories for .gguf files."""
    cfg = cfg or load_platform_config()
    models = []
    for base in cfg.get('gguf_dirs', []) + cfg.get('extra_model_dirs', []):
        for f in sorted(glob.glob(os.path.join(expand(base), '**', '*.gguf'), recursive=True)):
            try:
                size = os.path.getsize(f)
            except OSError:
                continue
            name = os.path.basename(f)
            models.append({
                'name': name,
                'path': f,
                'size_gb': round(size / 1024 ** 3, 1),
                'format': 'gguf',
                'source': 'gguf_dir',
            })
    return models


def scan_all_model_dirs(cfg=None):
    """Unified scan of ALL known model locations across loaders.

    Returns a list of model dicts, each tagged with:
      - name: model name (basename or repo name)
      - path: absolute path (or None for store-based models)
      - size_gb: size in GB (0.0 if unknown)
      - format: 'safetensors' | 'gguf' | 'bin' | 'weights'
      - source: where it was found ('hf_cache', 'gguf_dir', 'ollama_store',
                'lmstudio_models', 'ollama_api', 'ollama_cli', 'service')
      - loaders: list of loader keys that can load this model (based on format)

    Deduplicates by (name, source).
    """
    cfg = cfg or load_platform_config()
    models = []
    seen = set()

    def _add(m):
        key = (m['name'], m['source'])
        if key not in seen:
            seen.add(key)
            models.append(m)

    # 1) HF cache (vllm)
    for m in scan_hf_cache(cfg):
        m['loaders'] = ['vllm']
        _add(m)

    # 2) GGUF dirs (llama_cpp, lmstudio)
    for m in scan_gguf_dirs(cfg):
        m['loaders'] = ['llama_cpp', 'lmstudio']
        _add(m)

    # 3) LM Studio models dir (~/.lmstudio/models)
    lmstudio_models_dir = expand('~/.lmstudio/models')
    if os.path.isdir(lmstudio_models_dir):
        for f in sorted(glob.glob(os.path.join(lmstudio_models_dir, '**', '*.gguf'), recursive=True)):
            try:
                size = os.path.getsize(f)
            except OSError:
                continue
            # Skip multimodal projector files (mmproj-*)
            if f.startswith('mmproj') or os.path.basename(f).startswith('mmproj'):
                continue
            name = os.path.basename(f)
            _add({
                'name': name,
                'path': f,
                'size_gb': round(size / 1024 ** 3, 1),
                'format': 'gguf',
                'source': 'lmstudio_models',
                'loaders': ['lmstudio', 'llama_cpp'],
            })

    # 4) Ollama store (~/.ollama/models/manifests)
    ollama_manifests_dir = expand('~/.ollama/models/manifests/registry.ollama.ai/library')
    if os.path.isdir(ollama_manifests_dir):
        for root, _, files in os.walk(ollama_manifests_dir):
            for f in files:
                if f.endswith('.json'):
                    name = os.path.basename(os.path.dirname(root))
                    _add({
                        'name': name,
                        'path': os.path.join(root, f),
                        'size_gb': 0.0,
                        'format': 'gguf',
                        'source': 'ollama_store',
                        'loaders': ['ollama'],
                    })

    return models


def next_free_port(cfg=None):
    """Next free port from port_base, skipping reserved + in-use + existing services."""
    import sys
    cfg = cfg or load_platform_config()
    base = int(cfg.get('port_base', 8000))
    reserved = set(cfg.get('reserved_ports', []))
    try:
        from app import SERVICES  # noqa: F401  (app.py imports loaders; avoid cycle)
        for svc in SERVICES.values():
            p = (svc.get('default_params') or {}).get('port')
            if p:
                reserved.add(int(p))
    except Exception:
        pass
    try:
        import psutil
        for conn in psutil.net_connections('inet'):
            if conn.status == 'LISTEN':
                reserved.add(conn.laddr.port)
    except Exception:
        pass
    port = base
    while port in reserved:
        port += 1
    return port


def make_service_key(loader_key, model):
    """Slug for a service key: <loader>_<model-slug> (unique-ish; caller de-dupes)."""
    slug = re.sub(r'[^a-z0-9]+', '_', (model or loader_key).lower()).strip('_')
    return f"{loader_key}_{slug}"[:40] or loader_key


def write_scripts(start_content, stop_content, key, cfg=None):
    """Write generated start/stop scripts; returns (start_path, stop_path).

    Prepends a PATH export after the shebang: the manager's systemd user
    service has a minimal PATH, and the scripts it runs inherit it —
    user-installed tools (ollama, lms, docker in /usr/local/bin) would
    otherwise be invisible to the generated scripts.
    """
    cfg = cfg or load_platform_config()
    d = expand(cfg.get('generated_scripts_dir', '~/Desktop/AI/vllm-model-manager-/scripts/generated'))
    os.makedirs(d, exist_ok=True)
    start_path = os.path.join(d, f'mgr_{key}_start.sh')
    stop_path = os.path.join(d, f'mgr_{key}_stop.sh')

    def _with_path_header(content):
        lines = content.splitlines(keepends=True)
        if lines and lines[0].startswith('#!'):
            lines.insert(1, f'export PATH="{_extra_path()}:$PATH"\n')
        return ''.join(lines)

    with open(start_path, 'w') as f:
        f.write(_with_path_header(start_content))
    with open(stop_path, 'w') as f:
        f.write(_with_path_header(stop_content))
    for p in (start_path, stop_path):
        os.chmod(p, 0o755)
    return start_path, stop_path


# ---------------------------------------------------------------------------
# Loader base class
# ---------------------------------------------------------------------------

class Loader:
    key = None          # e.g. 'vllm'
    name = None         # display name
    param_schema = []   # [{name, label, type: int|float|select, default, min, max, step, options}]
    requires_model = True
    fixed_port = None   # loader runs on a fixed port (e.g. ollama 11434)

    def detect(self):
        """-> {'installed': bool, 'version': str|None, 'detail': str|None}"""
        raise NotImplementedError

    def list_models(self):
        """-> [{'name', 'path'|None, 'size_gb', 'format', 'source'}]"""
        return []

    def build_service(self, key, model, params):
        """params: {'gpus': [..], 'port': int, **loader-specific from param_schema}
        Writes start/stop scripts and returns:
        {'service': <services.json entry dict>, 'start_script': path, 'stop_script': path}
        """
        raise NotImplementedError
