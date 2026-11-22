# LLM Model Manager

<div align="center">

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0+-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

一个优雅的 Web 管理系统，用于管理和监控 LLM 模型服务（vLLM、Ollama、LM Studio、llama.cpp 等）

[功能特性](#功能特性) • [快速开始](#快速开始) • [配置说明](#配置说明) • [界面预览](#界面预览) • [API文档](#api文档)

</div>

---

## 功能特性

### 核心功能

- 🚀 **一键管理** - 通过 Web 界面一键启动/停止所有模型服务
- 📊 **实时监控** - 实时显示 GPU 利用率、显存使用、温度、功耗等
- 💻 **系统资源** - 监控 CPU、内存、磁盘使用情况
- 📝 **日志查看** - 在 Web 界面直接查看服务日志
- 🎨 **现代化 UI** - 美观的渐变色界面，响应式设计
- 🔄 **自动刷新** - 每 0.5 秒自动更新所有状态信息
- ⚙️ **灵活配置** - 通过 JSON 配置文件轻松管理多个服务

### 支持的功能

- ✅ 多服务管理
- ✅ GPU 实时监控
- ✅ 进程状态追踪
- ✅ 资源使用统计
- ✅ 日志实时查看
- ✅ 配置文件驱动

## 快速开始

### 环境要求

- Python 3.8+
- Node.js 18+
- GPU（NVIDIA with CUDA 或 AMD ROCm）
- 至少一个 LLM 推理后端已安装（vLLM、Ollama、LM Studio、llama.cpp）
- nvidia-smi 或 rocm-smi 可用

### 安装依赖

后端依赖：
```bash
pip install flask flask-cors psutil
```

前端依赖：
```bash
cd frontend
npm ci
```

### 配置服务

1. 复制配置文件示例：

```bash
cp config/services.json.example config/services.json
```

2. 编辑 `config/services.json`，配置你的模型服务：

```json
{
    "service_key": {
        "name": "模型名称",
        "port": 8000,
        "start_script": "/path/to/start_script.sh",
        "stop_script": "/path/to/stop_script.sh",
        "log_file": "/path/to/log_file.log",
        "process_pattern": "vllm serve.*YourModel",
        "gpus": [0, 1]
    }
}
```

### 构建前端

```bash
cd frontend
API_URL=http://localhost:9000 npm run build
cd ..
```

### 启动管理系统

启动后端：
```bash
python3 app.py
```

启动前端（新终端）：
```bash
cd frontend/.next/standalone
node server.js
```

访问地址：
- **前端界面**: http://localhost:3000
- **后端 API**: http://localhost:9000

### 使用 systemd 管理（推荐）

安装服务：
```bash
# 复制服务文件到 systemd 目录
sudo cp vllm-manager-backend.service /etc/systemd/system/
sudo cp vllm-manager-frontend.service /etc/systemd/system/

# 重新加载 systemd
sudo systemctl daemon-reload

# 启动服务
sudo systemctl start vllm-manager-backend
sudo systemctl start vllm-manager-frontend

# 设置开机自启
sudo systemctl enable vllm-manager-backend
sudo systemctl enable vllm-manager-frontend
```

查看服务状态：
```bash
sudo systemctl status vllm-manager-backend
sudo systemctl status vllm-manager-frontend
```

## 配置说明

### 服务配置项

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 服务显示名称 |
| `port` | int | 服务监听端口 |
| `start_script` | string | 启动脚本的绝对路径 |
| `stop_script` | string | 停止脚本的绝对路径 |
| `log_file` | string | 日志文件的绝对路径 |
| `process_pattern` | string | 用于识别进程的正则表达式 |
| `gpus` | array | 服务使用的 GPU 编号列表 |

### 配置示例

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

## 界面预览

### 主界面

- **系统资源监控面板** - 显示 CPU、内存、磁盘使用情况
- **GPU 状态卡片** - 每个 GPU 的详细信息（利用率、显存、温度、功耗）
- **服务管理卡片** - 每个服务的状态和控制按钮

### 服务卡片信息

运行中的服务显示：
- 进程 PID
- CPU 使用率
- 内存占用
- GPU 显存占用
- 启动时间

### 操作按钮

- **启动** - 启动模型服务
- **停止** - 停止模型服务
- **日志** - 查看服务日志（最近 200 行）

## API 文档

### 获取所有服务状态

```http
GET /api/services
```

响应示例：
```json
{
    "service_key": {
        "name": "模型名称",
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

### 获取 GPU 信息

```http
GET /api/gpu
```

响应示例：
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

### 获取系统信息

```http
GET /api/system
```

响应示例：
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

### 启动服务

```http
POST /api/service/{service_key}/start
```

响应示例：
```json
{
    "success": true,
    "message": "服务启动成功",
    "output": "..."
}
```

### 停止服务

```http
POST /api/service/{service_key}/stop
```

响应示例：
```json
{
    "success": true,
    "message": "服务停止成功",
    "output": "..."
}
```

### 获取服务日志

```http
GET /api/service/{service_key}/logs?lines=100
```

参数：
- `lines` (可选): 返回的日志行数，默认 100

响应示例：
```json
{
    "success": true,
    "logs": "日志内容..."
}
```

## 项目结构

```
vllm-model-manager/
├── app.py                           # Flask 后端主程序
├── frontend/                        # Next.js 前端应用
│   ├── app/                        # Next.js App Router
│   ├── components/                 # React 组件
│   ├── hooks/                      # React Hooks
│   ├── lib/                        # 工具函数
│   └── package.json                # 前端依赖
├── config/
│   ├── services.json               # 服务配置文件
│   └── services.json.example       # 配置文件示例
├── vllm-manager-backend.service    # 后端 systemd 服务文件
├── vllm-manager-frontend.service   # 前端 systemd 服务文件
├── requirements.txt                # Python 依赖
├── .gitignore                      # Git 忽略文件
├── LICENSE                         # 开源协议
└── README.md                       # 项目文档
```

## 部署建议

### 生产环境部署

1. **构建前端**：
```bash
cd frontend
API_URL=http://your-server-ip:9000 npm run build
```

2. **配置 systemd 服务**：项目已包含服务文件 `vllm-manager-backend.service` 和 `vllm-manager-frontend.service`

3. **安装并启动服务**：
```bash
sudo cp vllm-manager-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vllm-manager-backend vllm-manager-frontend
```

### 使用 Nginx 反向代理

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

### 添加基础认证

安装 `flask-httpauth`：
```bash
pip install flask-httpauth
```

在 `app.py` 中添加：
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

# 在路由上添加 @auth.login_required 装饰器
```

## 安全建议

1. **防火墙配置** - 限制管理端口的访问
2. **使用 HTTPS** - 配置 SSL 证书
3. **添加认证** - 使用 HTTP 基础认证或 OAuth
4. **定期更新** - 及时更新依赖包
5. **日志审计** - 记录所有操作日志

## 常见问题

### Q: 为什么 GPU 信息无法显示？

A: 确保 `nvidia-smi` 命令可用，并且当前用户有权限执行该命令。

### Q: 服务启动失败怎么办？

A: 检查以下几点：
- 启动脚本路径是否正确
- 启动脚本是否有执行权限
- GPU 是否被其他进程占用
- 端口是否被占用
- 查看服务日志获取详细错误信息

### Q: 如何添加新的服务？

A: 在 `config/services.json` 中添加新的服务配置，然后重启管理系统。

### Q: 可以管理非 vLLM 服务吗？

A: 可以！只需要提供对应的启动/停止脚本和进程识别模式即可。

## 开发计划

- [ ] 添加用户认证系统
- [ ] 性能图表和历史数据
- [ ] 邮件/钉钉告警通知
- [ ] API 密钥管理
- [ ] 多节点支持
- [ ] 服务健康检查
- [ ] 自动故障恢复

## 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 致谢

- [Flask](https://flask.palletsprojects.com/) - Web 框架
- [vLLM](https://github.com/vllm-project/vllm) - 大语言模型推理引擎
- [psutil](https://github.com/giampaolo/psutil) - 系统和进程工具

## 联系方式

如有问题或建议，欢迎提交 Issue 或通过以下方式联系：

- GitHub Issues: [项目 Issues 页面](https://github.com/yourusername/vllm-model-manager/issues)

---

<div align="center">

**[⬆ 回到顶部](#vllm-model-manager)**

Made with ❤️ for the AI community

</div>
