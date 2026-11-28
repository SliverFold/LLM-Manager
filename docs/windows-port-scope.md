# Windows Port — Scope

**Status:** scoping (not yet built). **Constraint:** keep this work separate from the existing Linux setup — no in-place modification of the Linux code path; the Windows work is its own set of files + a dispatch layer.

_Last grounded: 2026-11-27, against the live tree at `~/Desktop/AI/vllm-model-manager-`._

## 1. Grounded findings (verified against the live tree)

The Linux-specific surface is exactly:

| Area | Where | Windows implication |
|---|---|---|
| 2 manager systemd user units | `vllm-manager-backend.service.user`, `vllm-manager-frontend.service.user` | → Windows Services (NSSM or Task Scheduler) |
| `loginctl enable-linger` | `setup.sh:34` | → no equivalent; Windows services persist by default |
| `systemctl --user` calls | `app.py:696,785,898,1447–1462` (self-update restart, manager restart, status check) | → `Restart-Service` / NSSM restart; detached-spawn trick → `CREATE_NEW_PROCESS_GROUP` |
| GPU metrics | `app.py:75–110` (`rocm-smi` JSON + `/opt/rocm/bin` candidates), `157` + `212` (`nvidia-smi` fallback) | → `nvidia-smi` works as-is; AMD-on-Windows has **no rocm-smi** (see §3) |
| 5 loaders generate bash start/stop | `loaders/{vllm,ollama,lmstudio,llama_cpp,paiton}.py` — `nohup … &`, `pkill -f`, `HIP_VISIBLE_DEVICES`, `--device /dev/kfd --device /dev/dri`, `/home/{os.getlogin()}/logs/` | → emit `.ps1` with `Start-Process`/`Stop-Process`; drop `/dev/kfd` device flags |
| 42 project bash scripts | `setup.sh`, `uninstall_manager.sh`, 6 `install_*.sh`, 5 `uninstall_*.sh`, 10 `mgr_*_start/stop.sh`, ComfyUI/qwen3/paddleocr starters | → PowerShell equivalents (or run under Git Bash) |
| OpenViking installer registers **2 more** systemd units | `scripts/install_openviking.sh:124–180` (`openviking-embed.service`, `openviking-server.service`) | → 2 more Windows services |
| Hardcoded `/home/j` paths in the backend itself | `app.py:1084` (`/home/j/logs/metrics_lmstudio.csv`), `app.py:1709` (`/home/j/logs/comfyui.log`) | → `%USERPROFILE%\logs\…` |
| `start_new_session=True` (detached spawn) | `app.py:786,899,1698,1917`, `installer.py:368` | → `subprocess.CREATE_NEW_PROCESS_GROUP` / `DETACHED_PROCESS` |
| Conda activation via `source` | `app.py:498–499` | → `conda activate` in a `.cmd`/PowerShell or drop |
| Config paths | `config/platform.json` (`~/.cache/huggingface`, `~/models/gguf`), `config/services.json` (absolute `/home/j/…` start/stop/log paths, `process_pattern`) | → Windows path variants |

Cross-platform (works as-is): `requirements.txt` (flask, flask-cors, psutil), the Flask backend logic, the Next.js frontend + standalone output (Node is cross-platform), the `hf` CLI, `python -m venv`.

## 2. Corrected platform reality (from web research)

Two corrections to the earlier "Path A / Path B" framing:

- **vLLM does not run natively on Windows.** Official vLLM docs: *"vLLM does not support Windows natively. To run vLLM on Windows, you can use WSL … or community-maintained forks, e.g. `SystemPanic/vllm-windows`."* The ROCm CLI adapter also reports `runtime: unsupported_native_windows` and refuses native Windows vLLM serving.
- **ROCm-on-WSL2 is a Technology Preview** (ROCm 10.2.0). Under WSL2 there is **no `/dev/kfd`** and no `/sys/class/drm` GPU tree; the GPU is reached through the Windows WDDM driver's **D3DKMT interface via `/dev/dxg`** (`librocdxg`). The required WSL package is `hsa-runtime-rocr4wsl-amdgpu` with `HSA_ENABLE_DXG_DETECTION=1`. A Docker container needs `--device=/dev/dxg` plus mounts of `libdxcore.so` and `librocdxg.so` — **not** the `--device /dev/kfd --device /dev/dri` the Paiton launchers use today.
- **gfx1201 (R9700/RX 9070, RDNA 4) is explicitly in the ROCm-on-WSL2 DXG support matrix** (librocdxg 1.2.0), and there is a **verified, working vLLM-on-R9700-on-WSL2 setup** (`SlyBase/vllm-sly-radiance`, tested on an R9700 with Windows 11 + WSL2 + ROCm 10.1 + Ubuntu 24.04). The remaining risk is the **Paiton custom kernels** (specifically the R4D one-shot IPC all-reduce, which is multi-GPU and not in the single-GPU big-brain path) and a **performance hit** from the DXG bridge.

**Consequence:** the clean architecture is not "native Windows + NVIDIA vLLM" (vLLM isn't native). It is a **two-machine deployment**:

> **The Linux machine (R9700 + 9070) keeps the Paiton big brain + the current manager dashboard (untouched). The Windows machine (RTX 4080, 12GB) gets the native manager dashboard + WSL2 vLLM (CUDA) for smaller models + the native backends (LM Studio, Ollama, llama.cpp). No Paiton on Windows (NVIDIA GPU). The Windows dashboard can optionally manage the Linux big brain as a remote service (if same network).**

## 3. Architecture

```
Machine 1: Linux (CachyOS) — R9700 (gfx1201, 32GB) + 9070 (16GB)
├─ Paiton big brain  (Qwen3.8 27B on R9700, :8000)  ← native ROCm, UNTOUCHED
├─ 9070  (image/sound gen + small brain LM Studio Q2)
└─ Manager dashboard (native Linux)  ← current setup, UNTOUCHED

Machine 2: Windows (RTX 4080, 12GB, NVIDIA)
├─ Manager dashboard  (Flask :9000 + Next.js :3000)  ← native Windows Services
├─ GPU metrics        ← nvidia-smi (the 4080)
├─ Native backends    ← LM Studio, Ollama, llama.cpp  (native .ps1 start/stop)
├─ WSL2 distro (Ubuntu)
│   └─ vLLM (CUDA) on the RTX 4080  ← existing Linux CUDA start/stop scripts, invoked via `wsl`
└─ [optional] Remote service → Linux big brain :8000 (if same network)
```

The dashboard's loaders dispatch on platform:
- `lmstudio` / `ollama` / `llama_cpp` → emit **native** `.ps1` start/stop.
- `vllm` → emit `.ps1` that **invokes the existing Linux CUDA start/stop scripts inside WSL2** (`wsl bash /home/…/mgr_x_start.sh`). The existing scripts are **reused, not rewritten** — this is what keeps the two tracks separate.
- `paiton` → **out of scope on Windows** (NVIDIA GPU); the big brain stays on the Linux machine. The Windows dashboard can manage it as a **remote service** (an OpenAI-compatible endpoint in `config/services.json`).

## 4. Work breakdown — Native Windows (primary)

### 4.1 Platform detection + dispatch layer
- New `platform.py` (or extend `loaders/base.py`): `is_windows()`, `expand()` for `%USERPROFILE%`, `which()` for `.exe`/`.cmd`/`.ps1`, path separators.
- `write_scripts()` in `base.py`: emit `.ps1` on Windows, `.sh` on Linux.
- Verify `expand()` already handles `~` → `%USERPROFILE%` via `os.path.expanduser`.

### 4.2 Service management
- `windows/setup.ps1` (PowerShell equivalent of `setup.sh`): venv + `pip install -r requirements.txt`; `npm install && npm run build` + the **static-copy steps** (the white-screen gotcha applies identically); register the 2 manager Windows services; start them.
- `windows/uninstall.ps1` (equivalent of `uninstall_manager.sh`): stop + remove the 2 services.
- Service registration: **NSSM** (recommended — simple, robust, auto-restart) or Task Scheduler + a `.ps1` launcher. Map the unit fields:
  - backend: `WorkingDirectory=@REPO@`, `HOST=0.0.0.0`, `PORT=9000`, `PYTHONUNBUFFERED=1`, `ExecStart=.venv\python app.py`, `Restart=always/RestartSec=10`.
  - frontend: `WorkingDirectory=@REPO@\frontend\.next\standalone`, `NODE_ENV=production`, `PORT=3000`, `HOSTNAME=0.0.0.0`, `ExecStart=node server.js`, requires the backend.
- `app.py` `systemctl --user` calls (696, 785, 898, 1447–1462) → a `service.py` shim that calls NSSM/`Restart-Service` on Windows and `systemctl` on Linux.
- The detached-spawn trick (`start_new_session=True`) → `subprocess.CREATE_NEW_PROCESS_GROUP` / `DETACHED_PROCESS` creationflags.
- OpenViking installer's 2 units (`openviking-embed`, `openviking-server`) → 2 more Windows services in `install_openviking.ps1`.

### 4.3 GPU metrics (`app.py` `get_gpu_info` / `get_gpu_process_usage`)
- NVIDIA: `nvidia-smi --query-gpu=… --format=csv` — **works as-is** (add a Windows branch that calls `nvidia-smi` directly).
- AMD on Windows: **no rocm-smi**. Options: (a) AMD ADL (Advanced Display Library) via Python bindings for util/VRAM/power; (b) `Get-CimInstance Win32_VideoController` for name + total VRAM only; (c) drop live util/temp/power and show name + VRAM. Realistically: NVIDIA full; AMD-on-Windows name + total VRAM unless ADL is wired up.
- `get_gpu_process_usage` (app.py:191): `nvidia-smi --query-compute-apps` for NVIDIA; AMD → ADL or drop.

### 4.4 Generated start/stop scripts (the 5 loaders)
- Each loader's `build_service` gets a Windows branch emitting `.ps1`:
  - `vllm.py`: `nohup vllm serve …` → `Start-Process` / `python -m vllm.serve …` with redirected output; `pkill -f` → `Get-Process`/`Stop-Process`/`taskkill`. **On a native Windows + NVIDIA target, vLLM itself needs the community fork or WSL** (see §2) — so this loader may be WSL2-invoking rather than native.
  - `ollama.py`: `nohup ollama serve` → `Start-Process ollama serve`; `pkill -f "ollama serve"` → `Stop-Process`.
  - `lmstudio.py`: `lms load …` → `lms.exe load …` (LM Studio is a native Windows app).
  - `llama_cpp.py`: `nohup llama-server` → `Start-Process`; drop the `--device /dev/kfd` docker flags.
  - `paiton.py`: **native Windows = out of scope** (ROCm/Docker-only). `detect()` returns False on a native Windows target (no paiton repo + no ROCm). Paiton lives in the WSL2 track.
- `config/services.json`: `start_script`/`stop_script` → `.ps1` paths; `process_pattern` → Windows process names; `log_file` → Windows paths.
- `config/platform.json`: `hf_cache`, `gguf_dirs`, `extra_model_dirs`, `generated_scripts_dir` → Windows path variants.

### 4.5 Installers (PowerShell)
- `install_vllm.ps1`: venv + pip (Windows wheel is **CUDA** — works); the Paiton step (5.5) is **skipped on Windows** (AMD-only); Qwen tools (5.6, npm) work cross-platform.
- `install_lmstudio.ps1`: LM Studio has a **native Windows installer**; Beledarian Suite `lms clone` works if `lms` is on PATH.
- `install_hermes.ps1`: Hermes is Python — `pip install` / `hermes update` cross-platform; webapp works.
- `install_openviking.ps1`: Python (cross-platform) + the 2 systemd units → 2 Windows services.
- `install_comfyui.ps1`: git clone + venv (cross-platform); ComfyUI also has a native Windows desktop.
- `install_paiton.ps1`: **out of scope on native Windows** (ROCm/Docker).
- `uninstall_*.ps1`: PowerShell equivalents of the 5 uninstallers.

### 4.6 Paths
- All `/home/<user>/…` → `%USERPROFILE%\…` (or `~`, which `expand()` handles).
- `/opt/rocm`, `/dev/kfd`, `/dev/dri` → N/A on Windows.
- `/usr/bin/node` → `node` on PATH.
- Log dir `/home/j/logs` → `%USERPROFILE%\logs` or `%APPDATA%`.

### 4.7 Frontend
- Next.js standalone is cross-platform. `frontend/build.sh` → `frontend/build.ps1` (same static-copy steps + service restart). The white-screen gotcha applies identically.

## 5. Work breakdown — WSL2 vLLM (CUDA) on the RTX 4080

The Windows machine's GPU is the **RTX 4080 (12GB, NVIDIA)** — so the WSL2 track is **vLLM (CUDA)** for **smaller models** (not the 27B big brain, which stays on the Linux R9700). This is the **standard, well-supported** WSL2 path (WSL2 + NVIDIA + CUDA is fully supported, unlike AMD/ROCm which is a Tech Preview). The existing Linux CUDA start/stop scripts are reused, not rewritten.

### 5.1 Prerequisites
- WSL2 enabled (Ubuntu distro); Docker Desktop with the WSL2 backend (or run vLLM directly in WSL2 without Docker).
- NVIDIA driver on the Windows host + CUDA in WSL2 (WSL2 auto-detects the NVIDIA GPU; no `/dev/dxg`/ROCm needed).

### 5.2 GPU passthrough
- WSL2 + NVIDIA is **fully supported** — the GPU is passed through automatically (no manual device mounts). The existing vLLM CUDA start script (`CUDA_VISIBLE_DEVICES=0 vllm serve …`) runs as-is inside WSL2.
- The **12GB VRAM constraint**: smaller models only (~7B–14B quantized). The 27B big brain does not fit.
- `--gpu-memory-utilization` can be the native 0.90–0.95 (no Windows-desktop VRAM reservation issue like the AMD/ROCm path).

### 5.3 Work items
- A `wsl/` setup script (PowerShell on the Windows host) that: provisions the WSL2 Ubuntu distro, sets up the Python venv + vLLM (CUDA wheel), and installs the existing manager + vLLM stack inside WSL2.
- A `windows/` launcher that invokes the **existing Linux CUDA start/stop scripts** inside WSL2 (`wsl bash /home/…/mgr_x_start.sh`) — the dashboard talks to the WSL2 backend via localhost (WSL2 port forwarding, automatic on Win11).
- Expose :9000/:3000/:8000 from WSL2 to Windows.

### 5.4 Assessment
**Low risk** — WSL2 + NVIDIA + CUDA is the standard, well-supported path. The main constraint is the **12GB VRAM** (smaller models only). No Paiton (NVIDIA GPU); the big brain stays on the Linux machine.

## 6. Risks & decision points

| # | Risk / decision | Mitigation |
|---|---|---|
| 1 | **Paiton on Windows is out of scope** (NVIDIA GPU) | The big brain stays on the Linux R9700; the Windows dashboard manages it as a **remote service** (OpenAI-compatible endpoint in `config/services.json`) |
| 1b | **12GB VRAM on the RTX 4080** — smaller models only (~7B–14B quantized); the 27B big brain doesn't fit | The WSL2 vLLM on Windows is for smaller models; the 27B big brain stays on the Linux R9700 |
| 2 | **vLLM not native on Windows** | The vLLM loader is WSL2-invoking (or the community fork), not native; LM Studio/Ollama/llama.cpp are the native backends |
| 3 | **AMD-on-Windows GPU metrics** (no rocm-smi) | NVIDIA full via `nvidia-smi`; AMD name + VRAM only (or ADL if wired up) |
| 4 | **Separation discipline** | Windows work = `windows/` + `wsl/` dirs + a `platform.py`/`service.py` dispatch layer; the existing Linux `.sh` scripts and systemd units are **untouched**; the WSL2 track reuses the Linux scripts via `wsl` rather than rewriting them |
| 5 | **Service restart kills the request's own process** (the self-update path) | The detached-spawn trick must be replicated on Windows (`CREATE_NEW_PROCESS_GROUP`); the response must already be on its way |

## 7. Recommended order & effort

1. **Native dashboard + services** (`platform.py`, `service.py`, `windows/setup.ps1`, `windows/uninstall.ps1`, GPU metrics) — ~2–3 days.
2. **Native backends** (LM Studio / Ollama / llama.cpp `.ps1` loaders + installers) — ~2–3 days.
3. **Config/path migration** (`services.json`, `platform.json`, the hardcoded `/home/j` paths) — ~1 day.
4. **WSL2 vLLM (CUDA) on the RTX 4080** — ~1–2 days (low risk; standard WSL2 + NVIDIA path).
5. **Remote service** (Windows dashboard → Linux big brain :8000) — ~0.5 day.
6. **Testing/validation** — ~2–3 days.

**Total:** ~1.5–2 weeks. The WSL2 track is low-risk (standard WSL2 + NVIDIA + CUDA); Paiton is out of scope (stays on the Linux R9700).

## 8. Out of scope
- **Paiton on Windows** (NVIDIA GPU — no ROCm); the big brain stays on the Linux R9700 (native, untouched).
- The 27B big brain on the Windows RTX 4080 (12GB VRAM — smaller models only).
- `rocm-smi`-based per-card metrics on AMD (no Windows equivalent; the Windows machine is NVIDIA).
- The dual-card (R9700+9070) RCCL/Radiance path (Linux/ROCm-specific, stays on the Linux machine).
