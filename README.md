# LLM Model Manager

<div align="center">

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0+-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

An elegant web control panel for managing and monitoring LLM model services (vLLM, Ollama, LM Studio, llama.cpp, and more)

[Features](#features) • [Quick Start](#quick-start) • [Configuration](#configuration) • [UI Overview](#ui-overview) • [API Reference](#api-reference)

</div>

---

## Features

### Core

- 🚀 **One-click control** — start/stop any model service from the web UI
- 📊 **Live monitoring** — GPU utilization, VRAM, temperature, and power in real time
- 💻 **System resources** — CPU, memory, and disk usage
- 📝 **Log viewing** — read service logs directly in the web UI
- 🎨 **Modern UI** — clean gradient design, fully responsive
- 🔄 **Auto-refresh** — all status updates every 0.5 s
- ⚙️ **Flexible config** — manage multiple services via a JSON config file

### Also supported

- ✅ Multi-service management
- ✅ Live GPU monitoring
- ✅ Process status tracking
- ✅ Resource usage stats
- ✅ Real-time log viewing
- ✅ Config-file driven

## Quick Start

### First run / reinstall (one command)

The repo ships a first-run installer that does everything:

```bash
git clone https://github.com/SliverFold/LLM-Manager.git
cd LLM-Manager
./setup.sh
```

`setup.sh` creates the Python venv, installs dependencies, builds the frontend,
installs the systemd **user** services (backend :9000, frontend :3000), enables
them, and turns on linger so they survive logout. The UI is then at
**http://127.0.0.1:3000**.

### Requirements

- Python 3.8+
- Node.js 18+
- GPU (NVIDIA with CUDA or AMD ROCm)
- At least one LLM inference backend installed (vLLM, Ollama, LM Studio, llama.cpp)
- `nvidia-smi` or `rocm-smi` available

### Install dependencies (manual)

Backend:
```bash
pip install flask flask-cors psutil
```

Frontend:
```bash
cd frontend
npm ci
```

### Configure services

1. Copy the example config:

```bash
cp config/services.json.example config/services.json
```

2. Edit `config/services.json` to describe your model services:

```json
{
    "service_key": {
        "name": "Model name",
        "port": 8000,
        "start_script": "/path/to/start_script.sh",
        "stop_script": "/path/to/stop_script.sh",
        "log_file": "/path/to/log_file.log",
        "process_pattern": "vllm serve.*YourModel",
        "gpus": [0, 1]
    }
}
```

> **Note:** the backend loads `config/services.json` only at startup — restart
> the backend after editing it (the UI has a "Restart Manager" button in the
> sidebar footer).

### Build the frontend

```bash
cd frontend
API_URL=http://localhost:9000 npm run build
cd ..
```

> The Next.js standalone build does **not** copy `static`/`public` into the
> bundle by itself — `setup.sh` and `deploy-frontend.sh` do this for you.

### Start the manager

Backend:
```bash
python3 app.py
```

Frontend (new terminal):
```bash
cd frontend/.next/standalone
node server.js
```

Endpoints:
- **UI**: http://localhost:3000
- **Backend API**: http://localhost:9000

### Manage with systemd (recommended)

The repo ships system units (`vllm-manager-{backend,frontend}.service`, root
paths) and user-unit templates (`vllm-manager-{backend,frontend}.service.user`,
with `@REPO@` placeholders). `setup.sh` installs the user units automatically.
To use the system units manually:

```bash
sudo cp vllm-manager-backend.service /etc/systemd/system/
sudo cp vllm-manager-frontend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start vllm-manager-backend vllm-manager-frontend
sudo systemctl enable vllm-manager-backend vllm-manager-frontend
```

Check status:
```bash
sudo systemctl status vllm-manager-backend
sudo systemctl status vllm-manager-frontend
```

## Configuration

### Service fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Display name of the service |
| `port` | int | Port the service listens on |
| `start_script` | string | Absolute path to the start script |
| `stop_script` | string | Absolute path to the stop script |
| `log_file` | string | Absolute path to the log file |
| `process_pattern` | string | Regex used to identify the running process |
| `gpus` | array | List of GPU indices the service uses |
| `loader` | string | Backend loader (`vllm`, `ollama`, `lmstudio`, `llama_cpp`) |

### Example

```json
{
    "llama3": {
        "name": "LLaMA-3-70B",
        "port": 8000,
        "start_script": "/opt/models/scripts/start_llama3.sh",
        "stop_script": "/opt/models/scripts/stop_llama3.sh",
        "log_file": "/var/log/vllm/llama3.log",
        "process_pattern": "vllm serve.*llama-3-70b",
        "gpus": [0, 1, 2, 3]
    },
    "mistral": {
        "name": "Mistral-7B",
        "port": 8001,
        "start_script": "/opt/models/scripts/start_mistral.sh",
        "stop_script": "/opt/models/scripts/stop_mistral.sh",
        "log_file": "/var/log/vllm/mistral.log",
        "process_pattern": "vllm serve.*mistral",
        "gpus": [4]
    }
}
```

## UI Overview

### Main dashboard

- **System resources panel** — CPU, memory, disk usage
- **GPU status cards** — per-GPU details (utilization, VRAM, temperature, power)
- **Service cards** — status and controls per service

### Service card info

A running service shows:
- Process PID
- CPU usage
- Memory usage
- GPU VRAM usage
- Start time

### Action buttons

- **Start** — start the model service
- **Stop** — stop the model service
- **Logs** — view the service log (last 200 lines)

## API Reference

### Get all service statuses

```http
GET /api/services
```

Example response:
```json
{
    "service_key": {
        "name": "Model name",
        "port": 8000,
        "gpus": [0, 1],
        "status": "running",
        "pid": 12345,
        "cpu_percent": 5.2,
        "memory_mb": 2048.5,
        "gpu_memory_mb": 10240,
        "uptime": "2024-01-20 10:30:00"
    }
}
```

### Get GPU info

```http
GET /api/gpu
```

Example response:
```json
[
    {
        "index": 0,
        "name": "NVIDIA A100-SXM4-80GB",
        "utilization": 85.5,
        "memory_used": 65536,
        "memory_total": 81920,
        "temperature": 68.0,
        "power_draw": 320.5,
        "power_limit": 400.0
    }
]
```

### Get system info

```http
GET /api/system
```

Example response:
```json
{
    "cpu_percent": 45.2,
    "memory_percent": 62.8,
    "memory_used_gb": 50.5,
    "memory_total_gb": 128.0,
    "disk_percent": 35.6,
    "disk_used_gb": 450.2,
    "disk_total_gb": 1000.0
}
```

### Start a service

```http
POST /api/service/{service_key}/start
```

Example response:
```json
{
    "success": true,
    "message": "Service started successfully",
    "output": "..."
}
```

### Stop a service

```http
POST /api/service/{service_key}/stop
```

Example response:
```json
{
    "success": true,
    "message": "Service stopped successfully",
    "output": "..."
}
```

### Get service logs

```http
GET /api/service/{service_key}/logs?lines=100
```

Parameters:
- `lines` (optional): number of log lines to return, default 100

Example response:
```json
{
    "success": true,
    "logs": "log content..."
}
```

## Project structure

```
vllm-model-manager/
├── app.py                           # Flask backend
├── loaders/                         # backend loader registry (vllm/ollama/lmstudio/llama_cpp)
├── frontend/                        # Next.js frontend
│   ├── app/                        # Next.js App Router
│   ├── components/                 # React components
│   ├── hooks/                      # React hooks
│   ├── lib/                        # utilities + i18n
│   └── package.json                # frontend dependencies
├── config/
│   ├── services.json               # service configuration
│   └── services.json.example       # example configuration
├── scripts/                          # start/stop wrappers for the services
├── vllm-manager-backend.service    # backend systemd unit (system)
├── vllm-manager-frontend.service   # frontend systemd unit (system)
├── vllm-manager-backend.service.user   # backend user-unit template
├── vllm-manager-frontend.service.user  # frontend user-unit template
├── setup.sh                        # first-run installer (venv + build + user units)
├── deploy-frontend.sh              # frontend build + deploy + restart
├── requirements.txt                # Python dependencies
├── .gitignore                      # Git ignore file
├── LICENSE                         # open-source license
└── README.md                       # this document
```

## Deployment notes

### Production deployment

1. **Build the frontend**:
```bash
cd frontend
API_URL=http://your-server-ip:9000 npm run build
```

2. **Configure systemd services**: the repo includes the unit files `vllm-manager-backend.service` and `vllm-manager-frontend.service`

3. **Install and start the services**:
```bash
sudo cp vllm-manager-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vllm-manager-backend vllm-manager-frontend
```

### Nginx reverse proxy

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:9000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### Adding basic auth

Install `flask-httpauth`:
```bash
pip install flask-httpauth
```

Add to `app.py`:
```python
from flask_httpauth import HTTPBasicAuth

auth = HTTPBasicAuth()

users = {
    "admin": "password"
}

@auth.verify_password
def verify_password(username, password):
    if username in users and users[username] == password:
        return username

# Add the @auth.login_required decorator to your routes
```

## Security recommendations

1. **Firewall** — restrict access to the management ports
2. **Use HTTPS** — configure an SSL certificate
3. **Add authentication** — HTTP basic auth or OAuth
4. **Keep up to date** — update dependencies regularly
5. **Audit logs** — record all operations

## FAQ

### Q: Why don't GPU details show up?

A: Make sure `nvidia-smi` (or `rocm-smi` on AMD) is available and the current
user can run it.

### Q: A service fails to start — what do I check?

A: Check the following:
- Is the start script path correct?
- Does the start script have execute permission?
- Is the GPU in use by another process?
- Is the port already taken?
- Check the service log for detailed error messages

### Q: How do I add a new service?

A: Add a new entry to `config/services.json`, then restart the manager.
You can also use the "Add Service" wizard in the UI, which generates the
config entry and start/stop scripts for you.

### Q: Can I manage non-vLLM services?

A: Yes — anything with a start/stop script and a process pattern works
(vLLM, Ollama, LM Studio, llama.cpp, and more).

## Development plans

- [ ] User authentication
- [ ] Performance charts and historical data
- [ ] Email/Slack alert notifications
- [ ] API key management
- [ ] Multi-node support
- [ ] Service health checks
- [ ] Automatic failure recovery

## Contributing

Issues and pull requests are welcome!

1. Fork this project
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a pull request

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file.

## Acknowledgments

- [Flask](https://flask.palletsprojects.com/) — web framework
- [vLLM](https://github.com/vllm-project/vllm) — LLM inference engine
- [psutil](https://github.com/giampaolo/psutil) — system and process utilities

## Contact

For issues or suggestions, please open an Issue:

- GitHub Issues: [Issues page](https://github.com/SliverFold/LLM-Manager/issues)

---

<div align="center">

**[⬆ Back to top](#llm-model-manager)**

Made with ❤️ for the AI community

</div>
