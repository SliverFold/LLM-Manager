#!/usr/bin/env bash
# vllm-model-manager: install vLLM into a venv (vendor-aware)
#
#   AMD ROCm (channel "nightly" = default):
#     Follows the official AMD procedure (rocm.docs.amd.com vLLM page):
#       1. torch/torchvision/torchaudio (ROCm builds, latest rocm10.x) from
#          https://stable.repo.amd.com/rocm/whl-next/ with the per-GPU-arch
#          "device-<gfx>" extra (kernels from AMD's whl-multi-arch index).
#          The ROCm SDK comes from pip (TheRock/_rocm_sdk_core) — the system
#          ROCm install is NOT used or required.
#       2. flash-attn + amd-aiter + triton from AMD's whl-multi-arch index.
#       3. the newest vLLM wheel (rocm10.x) from AMD's whl-multi-arch index.
#     The newest ROCm wheels (10.1+) live only on AMD's indexes —
#     wheels.vllm.ai/rocm carries rocm100 only.
#
#   AMD ROCm (channel "stable"):
#     Latest stable vLLM on ROCm 10.0 from wheels.vllm.ai/rocm (Python 3.12 only).
#
#   NVIDIA CUDA:
#     Latest stable CUDA wheel, torch backend auto-selected from the driver.
#
# Usage: install_vllm.sh <venv_dir> <channel> [paiton=true|false]
set -euo pipefail

VENV="${1:?usage: install_vllm.sh <venv_dir> <channel> [paiton]}"
CHANNEL="${2:-nightly}"
PAITON="${3:-false}"
VENV="$(eval echo "$VENV")"
mkdir -p "$VENV"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# The system ROCm (if any) can interfere with the pip-bundled ROCm SDK.
unset ROCM_PATH LD_LIBRARY_PATH

# NOTE: AMD's frameworks index (rocm.frameworks.amd.com) blocks pip's user
# agent and returns an empty listing for it — use plain curl (no -A).
# Both AMD indexes sit behind CloudFront and intermittently return 403
# (bot detection / rate limiting) — every fetch retries.
AMD_TORCH_INDEX="https://stable.repo.amd.com/rocm/whl-next"
AMD_FRAMEWORKS_INDEX="https://rocm.frameworks.amd.com/whl-multi-arch/vllm"

fetch_index() { # fetch a URL with retries (CloudFront 403s are intermittent)
  local url="$1" attempt out
  for attempt in 1 2 3 4 5; do
    out="$(curl -sL --fail "$url" 2>/dev/null)" && [ -n "$out" ] && { printf '%s' "$out"; return 0; }
    sleep 2
  done
  echo "WARNING: index fetch failed after 5 attempts: $url" >&2
  return 1
}

# --- 1. GPU vendor detection ---
VENDOR=""
if command -v rocm-smi >/dev/null 2>&1 || [ -d /opt/rocm ]; then
  VENDOR="amd"
elif command -v nvidia-smi >/dev/null 2>&1; then
  VENDOR="nvidia"
else
  log "ERROR: no GPU stack found (neither rocm-smi nor nvidia-smi)"
  exit 1
fi
log "GPU vendor: $VENDOR"

# --- 2. Python selection ---
# AMD STABLE wheels: Python 3.12 only — otherwise the installer silently falls
#   back to the CUDA wheel and fails with 'libcudart.so: cannot open shared object file'.
# AMD latest wheels: currently cp314 only.
# NVIDIA: Python 3.11-3.14.
PYBIN=""
if [ "$VENDOR" = "amd" ] && [ "$CHANNEL" = "stable" ]; then
  PYBIN="$(command -v python3.12 || true)"
  [ -n "$PYBIN" ] || { log "ERROR: stable ROCm wheels need python3.12 — install it and retry, or use the nightly channel"; exit 1; }
else
  for p in python3.14 python3.13 python3.12 python3.11 python3; do
    PYBIN="$(command -v "$p" || true)"
    [ -n "$PYBIN" ] && break
  done
fi
[ -n "$PYBIN" ] || { log "ERROR: no suitable python found"; exit 1; }
PYVER="$("$PYBIN" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
PYMINOR="${PYVER#3.}"
log "Python: $PYBIN (Python $PYVER)"

# --- 3. venv ---
if [ ! -x "$VENV/bin/python" ]; then
  log "Creating venv at $VENV"
  "$PYBIN" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install -q -U pip setuptools wheel

# --- 4. uv ---
# uv is REQUIRED for the AMD indexes (pip merges extra-index with PyPI and
# picks the wrong version) and is vLLM's recommended installer.
if ! command -v uv >/dev/null 2>&1; then
  log "Installing uv…"
  "$VENV/bin/python" -m pip install -q uv
fi
UV="$(command -v uv)"

# --- 5. Install vLLM (vendor + channel) ---
if [ "$VENDOR" = "amd" ] && [ "$CHANNEL" = "stable" ]; then
  log "Installing vLLM (stable ROCm 10.0 wheel)…"
  "$UV" pip install --python "$VENV" vllm --extra-index-url https://wheels.vllm.ai/rocm/ --upgrade
elif [ "$VENDOR" = "amd" ]; then
  # ---- Latest ROCm from AMD's indexes (official AMD procedure) ----
  # uv.toml for the AMD indexes: 403s mean "package not hosted here" and must
  # be ignored so resolution continues on the next index. Named indexes are
  # consulted before the default (PyPI), so vllm/torch/flash-attn/triton come
  # from AMD, and everything else (lm-format-enforcer, …) falls back to PyPI.
  CFG_DIR="$(mktemp -d)"
  trap 'rm -rf "$CFG_DIR"' EXIT
  cat > "$CFG_DIR/uv.toml" <<'TOML'
[[index]]
name = "amd-frameworks"
url = "https://rocm.frameworks.amd.com/whl-multi-arch/vllm/"
ignore-error-codes = [403]

[[index]]
name = "amd-torch"
url = "https://stable.repo.amd.com/rocm/whl-next/"
ignore-error-codes = [403, 404]

[[index]]
name = "pypi"
url = "https://pypi.org/simple/"
default = true
TOML
  run_uv() { (cd "$CFG_DIR" && "$UV" pip install --python "$VENV" "$@"); }

  # 5a. GPU architecture (gfxXXXX) for the per-arch kernel extra
  GFX="$(rocm-smi --showproductname --json 2>/dev/null | grep -oE '"GFX Version": *"[^"]+"' | head -1 | grep -oE 'gfx[0-9]+')"
  [ -n "$GFX" ] || { log "ERROR: could not detect GPU gfx architecture via rocm-smi"; exit 1; }
  log "GPU architecture: $GFX"

  # 5b. Latest vLLM wheel (linux_x86_64) from AMD's index
  VLLM_LISTING="$(fetch_index "$AMD_FRAMEWORKS_INDEX/vllm/")"
  VLLM_WHEEL="$(echo "$VLLM_LISTING" | grep -oE 'vllm-[0-9a-zA-Z.]+%2B[^"]*linux_x86_64\.whl' | sed 's/%2B/+/g' | sort -uV | tail -1 || true)"
  [ -n "$VLLM_WHEEL" ] || { log "ERROR: no vLLM wheel found on $AMD_FRAMEWORKS_INDEX"; exit 1; }
  log "vLLM wheel: $VLLM_WHEEL"

  # ROCm version from the wheel name: rocm102 -> 10.2.0
  ROCM_TAG="$(echo "$VLLM_WHEEL" | grep -oE 'rocm[0-9]+' | head -1 | sed 's/rocm//')"
  ROCM_VER="$(echo "$ROCM_TAG" | sed -E 's/^([0-9]+)([0-9]+)$/\1.\2.0/')"
  log "Target ROCm: $ROCM_VER"

  # 5c. Latest torch / torchvision / torchaudio for that ROCm + python tag
  fetch_ver() { # $1=index path, $2=regex
    fetch_index "$AMD_TORCH_INDEX/$1/" \
      | grep -oE "$2" | sed 's/%2B/+/g' | sort -uV | tail -1
  }
  TORCH_WHEEL="$(fetch_ver torch "torch-[0-9.]+%2Brocm${ROCM_VER}-cp3${PYMINOR}-cp3${PYMINOR}-linux_x86_64\.whl")"
  TV_WHEEL="$(fetch_ver torchvision "torchvision-[0-9.]+%2Brocm${ROCM_VER}-cp3${PYMINOR}-cp3${PYMINOR}-linux_x86_64\.whl")"
  TA_WHEEL="$(fetch_ver torchaudio "torchaudio-[0-9.]+%2Brocm${ROCM_VER}-cp3${PYMINOR}-cp3${PYMINOR}-linux_x86_64\.whl")"
  [ -n "$TV_WHEEL" ] || { log "ERROR: no torchvision +rocm${ROCM_VER} cp3${PYMINOR} wheel on $AMD_TORCH_INDEX"; exit 1; }
  # wheel filename: <pkg>-<version>-cp3xx-cp3xx-linux_x86_64.whl
  # the version is the field right after the package name (never contains '-')
  wver() { echo "$1" | cut -d'-' -f2; }

  # The newest torch is often NEWER than the newest torchvision supports
  # (e.g. torchvision 0.29.0+rocm10.2.0 pins torch==2.14.0+rocm10.2.0 while
  # torch 2.15.0+rocm10.2.0 also exists). Pin torch to the exact version the
  # latest torchvision requires, read from its wheel METADATA.
  TV_ENC="$(echo "$TV_WHEEL" | sed 's/+/%2B/g')"
  TV_TORCH_PIN="$(curl -sL --fail "$AMD_TORCH_INDEX/torchvision/$TV_ENC" 2>/dev/null | python3.14 -c '
import sys, zipfile, re
try:
    data = sys.stdin.buffer.read()
    with zipfile.ZipFile(__import__("io").BytesIO(data)) as z:
        for n in z.namelist():
            if n.endswith("METADATA"):
                for line in z.read(n).decode().splitlines():
                    m = re.match(r"Requires-Dist: torch==([^\s;]+)", line)
                    if m:
                        print(m.group(1)); break
except Exception:
    pass
')"
  if [ -n "$TV_TORCH_PIN" ]; then
    TORCH_VER="$TV_TORCH_PIN"
    TORCH_WHEEL="$(fetch_ver torch "torch-${TORCH_VER//+/%2B}-cp3${PYMINOR}-cp3${PYMINOR}-linux_x86_64\\.whl")"
    log "torch pinned to $TORCH_VER (required by torchvision)"
  else
    TORCH_VER="$(wver "$TORCH_WHEEL")"
    log "WARNING: could not read torchvision's torch pin — using newest torch $TORCH_VER"
  fi
  [ -n "$TORCH_WHEEL" ] || { log "ERROR: no torch +rocm${ROCM_VER} cp3${PYMINOR} wheel on $AMD_TORCH_INDEX"; exit 1; }
  log "torch: $TORCH_VER  torchvision: ${TV_WHEEL:-none}  torchaudio: ${TA_WHEEL:-none}"

  # 5d. Latest flash-attn / amd-aiter / triton from AMD's frameworks index
  fetch_fw() { # $1=folder, $2=regex
    fetch_index "$AMD_FRAMEWORKS_INDEX/$1/" \
      | grep -oE "$2" | sed 's/%2B/+/g' | sort -uV | tail -1
  }
  FA_WHEEL="$(fetch_fw flash-attn 'flash_attn-[0-9a-zA-Z.]+%2B[^"]*linux_x86_64\.whl')"
  AIT_WHEEL="$(fetch_fw amd-aiter 'amd_aiter-[0-9a-zA-Z.]+%2B[^"]*linux_x86_64\.whl')"
  TRITON_WHEEL="$(fetch_fw triton 'triton-[0-9a-zA-Z.]+%2B[^"]*linux_x86_64\.whl')"
  [ -n "$FA_WHEEL" ] || { log "ERROR: no flash-attn wheel on $AMD_FRAMEWORKS_INDEX"; exit 1; }
  [ -n "$TRITON_WHEEL" ] || { log "ERROR: no triton wheel on $AMD_FRAMEWORKS_INDEX"; exit 1; }
  FA_VER="$(wver "$FA_WHEEL")"
  AIT_VER="$(wver "$AIT_WHEEL")"
  TRITON_VER="$(wver "$TRITON_WHEEL")"
  log "flash-attn: $FA_VER  amd-aiter: ${AIT_VER:-none}  triton: $TRITON_VER"

  # 5e. Step 1: PyTorch stack (ROCm builds + per-arch kernels)
  #     pip with --index-url whl-next: torch + all its deps come from AMD's
  #     index (never PyPI's CUDA torch). The device-gfxXXXX extra resolves
  #     from whl-next too.
  log "Installing PyTorch stack (ROCm $ROCM_VER, device-$GFX kernels)…"
  TV_VER="$(wver "$TV_WHEEL")"
  TA_VER="$(wver "$TA_WHEEL")"
  PKGS=("torch[device-$GFX]==$TORCH_VER")
  [ -n "$TV_WHEEL" ] && PKGS+=("torchvision[device-$GFX]==$TV_VER")
  [ -n "$TA_WHEEL" ] && PKGS+=("torchaudio==$TA_VER")
  "$VENV/bin/python" -m pip install "${PKGS[@]}" --index-url "$AMD_TORCH_INDEX/"

  # 5f. Step 2: flash-attn + amd-aiter (from the AMD frameworks index)
  log "Installing flash-attn + amd-aiter…"
  run_fw_pkgs=()
  run_fw_pkgs+=("flash-attn==$FA_VER")
  [ -n "$AIT_WHEEL" ] && run_fw_pkgs+=("amd-aiter==$AIT_VER")
  "$VENV/bin/python" -m pip install "${run_fw_pkgs[@]}" --extra-index-url "$AMD_FRAMEWORKS_INDEX/"

  # 5g. Step 3: triton (AMD build; downgrades torch's pinned triton — the
  #     dependency-conflict warning is expected and safe to ignore)
  log "Installing triton $TRITON_VER (AMD build)… (conflict warning expected)"
  "$VENV/bin/python" -m pip install "triton==$TRITON_VER" --extra-index-url "$AMD_FRAMEWORKS_INDEX/"

  # 5h. Step 4: the vLLM wheel itself (uv, with the triton override so its
  #     triton==3.8.0+git669b31ac requirement is satisfied). Pass the full URL
  #     (uv needs a URL or an existing local file, not a bare filename).
  log "Installing vLLM wheel…"
  VLLM_WHEEL_URL="$AMD_FRAMEWORKS_INDEX/vllm/$(echo "$VLLM_WHEEL" | sed 's/+/%2B/g')"
  echo "triton==$TRITON_VER" > "$CFG_DIR/overrides.txt"
  # unsafe-best-match: vLLM's deps (numba->numpy, …) must resolve across all
  # indexes — the AMD index only has old numpy without cp314 wheels.
  run_uv "$VLLM_WHEEL_URL" --override "$CFG_DIR/overrides.txt" --index-strategy unsafe-best-match

  # 5i. Runtime environment: the bundled ROCm SDK (TheRock) needs PYTHONPATH
  #     pointing at its amd_smi share dir, and the triton-AMD flash-attention
  #     flag. The system ROCm env vars must NOT be set (they interfere).
  PYDIR="$("$VENV/bin/python" -c 'import sys; print(f"python{sys.version_info[0]}{sys.version_info[1]}")')"
  cat > "$VENV/rocm.env" <<EOF
# ROCm runtime environment for the pip-bundled ROCm SDK (_rocm_sdk_core).
# Generated by install_vllm.sh — source this before running vllm.
unset ROCM_PATH
unset LD_LIBRARY_PATH
export PYTHONPATH="$VENV/lib/$PYDIR/site-packages/_rocm_sdk_core/share/amd_smi\${PYTHONPATH:+:\$PYTHONPATH}"
export FLASH_ATTENTION_TRITON_AMD_ENABLE=TRUE
EOF
  if grep -q '_rocm_sdk_core' "$VENV/bin/activate" 2>/dev/null; then
    : # already present
  else
    {
      echo ""
      echo "# ROCm runtime (added by install_vllm.sh)"
      echo 'unset ROCM_PATH'
      echo 'unset LD_LIBRARY_PATH'
      echo "export PYTHONPATH=\"$VENV/lib/$PYDIR/site-packages/_rocm_sdk_core/share/amd_smi\${PYTHONPATH:+:\$PYTHONPATH}\""
      echo 'export FLASH_ATTENTION_TRITON_AMD_ENABLE=TRUE'
    } >> "$VENV/bin/activate"
  fi
  log "Wrote $VENV/rocm.env (source it before running vllm)"
else
  log "Installing vLLM (CUDA wheel, torch backend auto)…"
  "$UV" pip install --python "$VENV" vllm --torch-backend=auto
fi

# --- 5.5. Paiton plugin (fast AMD kernels for quantized models: MXFP4/NVFP4) ---
# AMD-only. Installs the local paiton-vllm-plugin repo (clones it from GitHub
# if not present) into the venv. It registers vLLM platform/general plugins
# and provides the paiton-* serve CLIs.
if [ "$PAITON" = "true" ]; then
  if [ "$VENDOR" != "amd" ]; then
    log "Paiton plugin is AMD-only — skipping (vendor: $VENDOR)"
  else
    log "Installing Paiton plugin (MXFP4/NVFP4 kernels)…"
    PAITON_REPO="${PAITON_REPO:-$HOME/Desktop/AI/paiton-vllm-plugin}"
    if [ ! -d "$PAITON_REPO" ]; then
      log "Cloning paiton-vllm-plugin from GitHub…"
      git clone https://github.com/Eliovp-BV/paiton-vllm-plugin "$PAITON_REPO" || {
        log "ERROR: could not clone paiton-vllm-plugin"
        exit 1
      }
    fi
    "$VENV/bin/python" -m pip install "$PAITON_REPO" || log "WARNING: paiton plugin install failed"
    log "Paiton plugin installed from $PAITON_REPO"
  fi
fi

# --- 6. FlashInfer precompiled kernels (CUDA only) ---
# Without these, vLLM JIT-compiles kernels at first startup (several minutes on
# Hopper/Blackwell). ROCm wheels do not use FlashInfer.
if [ "$VENDOR" = "nvidia" ]; then
  log "Downloading precompiled FlashInfer kernels…"
  "$VENV/bin/vllm" download-kernels || log "WARNING: download-kernels failed — vLLM will JIT-compile kernels at first startup instead"
fi

# --- 7. Smoke test (assert ROCm on AMD — never CUDA) ---
log "Verifying install…"
if [ "$VENDOR" = "amd" ]; then
  "$VENV/bin/python" - <<'EOF'
import vllm, torch
assert torch.version.hip, f"ERROR: torch is not a ROCm build: {torch.__version__}"
print(f"vLLM {vllm.__version__} + torch {torch.__version__} (HIP {torch.version.hip}) — ROCm OK")
EOF
else
  "$VENV/bin/python" -c "import vllm; print('vLLM', vllm.__version__, 'installed OK')"
fi
log "Done — start a server with: $VENV/bin/vllm serve <model>"
