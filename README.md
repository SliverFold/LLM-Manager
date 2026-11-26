# LLM Manager

A web dashboard for running AI models on your own computer. Start and stop models
with a button, watch your GPU in real time, chat with your models in the browser,
and install the tools you need (vLLM, Hermes, ComfyUI) from the same page — no
terminal required.

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)]()
[![Flask](https://img.shields.io/badge/Flask-3.0+-green.svg)]()
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

**[Quick start](#quick-start)** • [What you can do](#what-you-can-do) •
[Supported backends](#supported-backends) • [Troubleshooting](#troubleshooting) •
[For developers](#for-developers)

---

## Quick start

Three steps:

```bash
git clone https://github.com/SliverFold/LLM-Manager.git
cd LLM-Manager
./setup.sh
```

Then open **http://127.0.0.1:3000** in your browser.

That's it. `setup.sh` installs everything (Python environment, frontend, and the
background services that keep the manager running) and finishes with a
"ready" message. The manager starts automatically when your computer boots.

**Requirements:** Python 3.8+, Node.js 18+, and a GPU (NVIDIA with CUDA or AMD
with ROCm). You don't need anything installed yet — vLLM, Hermes, and ComfyUI
can all be installed from the UI itself (see below).

---

## What you can do

### Start, stop, and watch your models

Each model service is a card with **Start**, **Stop**, and **Logs** buttons,
plus a live **Running / Stopped** badge. Use **Unload all** to stop everything
at once. The left sidebar shows a live system monitor: per-GPU VRAM,
utilization, temperature, and power, plus CPU, memory, and disk.

### Chat with your models

The **Model chats** list in the sidebar opens a simple browser chat for each
model that's running — no extra setup.

### Add a new model

Click **Add Service** and pick a backend (e.g. vLLM), a model, and the GPU(s)
to use. The manager finds the model for you (it scans your model folders) and
generates the start/stop scripts automatically. You can also browse the
filesystem to point at a model the scan missed.

### Install tools with one click

The **Installers** section at the bottom of the page installs:

- **vLLM** — the fast LLM inference engine. The installer picks the right
  wheels for your GPU (AMD ROCm or NVIDIA CUDA). On AMD you can also add the
  Paiton plugin for faster quantized-model performance.
- **Hermes Agent + Web UI** — the AI assistant and its browser workspace
  (port 9120).
- **ComfyUI** — the AI image/video generation framework.

Each card shows whether the tool is already installed, and you can uninstall
it the same way. Watch the live install log in a dialog while it runs.

---

## Supported backends

| Backend | What it is |
|---------|------------|
| **vLLM** | High-performance LLM inference (the default for most users) |
| **Ollama** | Popular local LLM runner |
| **LM Studio** | GUI LLM runner with a built-in server |
| **llama.cpp** | Lightweight CPU/GPU LLM inference |

Anything with a start/stop script and a port works — the backends above get
extra integration (model scanning, chat, etc.).

---

## Troubleshooting

**The page is a white screen or looks unstyled.**
The frontend build didn't finish copying its assets. Run
`cd frontend && bash build.sh` and reload.

**GPU details don't show up.**
Make sure `rocm-smi` (AMD) or `nvidia-smi` (NVIDIA) works from your terminal
and the current user can run it.

**A service won't start.**
Check the service's **Logs** button first — the error is almost always there.
Common causes: the port is already taken, the GPU is busy with another model,
or the model path is wrong.

**I edited the config file but nothing changed.**
The manager reads `config/services.json` only at startup. Click
**Restart Manager** in the sidebar footer (or use the *Add Service* dialog,
which restarts automatically).

**I changed the config and the UI is blank / shows old services.**
Same fix — **Restart Manager**.

---

## For developers

### Manual install

```bash
pip install -r requirements.txt
cd frontend && npm ci && cd ..

# build the frontend (copies static assets into the standalone bundle and
# restarts the frontend service — do NOT run bare `npx next build`)
cd frontend && bash build.sh && cd ..
```

Endpoints: **UI** at http://localhost:3000, **backend API** at
http://localhost:9000.

### systemd

`setup.sh` installs two **user** services (`vllm-manager-backend`,
`vllm-manager-frontend`) and enables linger so they survive logout. System
units (`vllm-manager-{backend,frontend}.service`) are also in the repo if you
prefer root-level services.

```bash
systemctl --user status vllm-manager-backend
systemctl --user restart vllm-manager-frontend
```

### Configuration

Services are defined in `config/services.json` (see
`config/services.json.example`). Each entry:

```json
{
    "my-model": {
        "name": "My Model",
        "port": 8000,
        "start_script": "/path/to/start.sh",
        "stop_script": "/path/to/stop.sh",
        "log_file": "/path/to/log.log",
        "process_pattern": "vllm serve.*MyModel",
        "gpus": [0]
    }
}
```

The **Add Service** dialog in the UI generates entries like this for you.

### Backend API (quick reference)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/services` | All services + live status (running/stopped, PID, CPU, memory) |
| `POST /api/service/{key}/start` · `/stop` | Start or stop a service |
| `GET /api/service/{key}/logs?lines=200` | Recent log lines |
| `GET /api/gpu` | Per-GPU info (VRAM, utilization, temperature, power) |
| `GET /api/system` | CPU / memory / disk usage |
| `GET /api/models` | Scan of installed models (HF cache, GGUF dirs, loader APIs) |
| `GET /api/models/browse?dir=/path` | List a directory (manual model picker) |
| `GET /api/installer/status` · `POST /api/installer/{vllm,hermes,comfyui}` · `POST /api/installer/uninstall` | Installers |
| `GET /api/hermes/webapp-link?profile=<name>` | One-use link to the Hermes web UI |

### Project structure

```
LLM-Manager/
├── app.py                     # Flask backend (:9000)
├── installer.py               # install/uninstall job runner
├── loaders/                   # backend loaders (vllm, ollama, lmstudio, llama_cpp)
├── frontend/                  # Next.js frontend (:3000)
│   └── build.sh               # build + copy static assets + restart service
├── templates/                 # per-model web chat page
├── config/
│   ├── services.json          # your services
│   └── platform.json          # model scan dirs + ports
├── scripts/                   # generated start/stop + installer scripts
├── setup.sh                   # first-run installer
└── vllm-manager-*.service     # systemd units (system + user templates)
```

---

## Contributing

Issues and pull requests are welcome — see
[Issues](https://github.com/SliverFold/LLM-Manager/issues).

## License

MIT — see [LICENSE](LICENSE).
