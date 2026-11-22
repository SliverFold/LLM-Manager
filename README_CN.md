# LLM 模型管理系统

<div align="center">

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0+-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

一个优雅的 Web 管理系统，用于管理和监控 LLM 模型服务（vLLM、Ollama、LM Studio、llama.cpp 等）

[English](README.md) | 简体中文

</div>

---

## ✨ 功能特性

### 核心功能

- 🚀 **一键管理** - 通过 Web 界面一键启动/停止所有模型服务
- 📊 **实时监控** - 实时显示 GPU 利用率、显存使用、温度、功耗等
- 💻 **系统资源** - 监控 CPU、内存、磁盘使用情况
- 📝 **日志查看** - 在 Web 界面直接查看服务日志（最近 200 行）
- 🎨 **现代化 UI** - 美观的渐变色界面，响应式设计，支持各种屏幕尺寸
- 🔄 **自动刷新** - 每 5 秒自动更新所有状态信息
- ⚙️ **灵活配置** - 通过 JSON 配置文件轻松管理多个服务

### 支持的功能

- ✅ 多服务管理（无数量限制）
- ✅ GPU 实时监控（支持多 GPU）
- ✅ 进程状态追踪（PID、CPU、内存）
- ✅ 资源使用统计
- ✅ 日志实时查看
- ✅ 配置文件驱动（JSON 格式）

## 🚀 快速开始

### 环境要求

- Python 3.8+
- NVIDIA GPU with CUDA
- 至少一个 LLM 推理后端已安装并可运行（vLLM、Ollama、LM Studio、llama.cpp）
- nvidia-smi 命令可用

### 1. 克隆项目

```bash
git clone https://github.com/yourusername/vllm-model-manager.git
cd vllm-model-manager
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

或使用国内镜像加速：
```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 3. 配置服务

复制配置文件示例：
```bash
cp config/services.json.example config/services.json
```

编辑 `config/services.json`，配置你的模型服务：
```json
{
    "my_model": {
        "name": "我的模型",
        "port": 8000,
        "start_script": "/path/to/start.sh",
        "stop_script": "/path/to/stop.sh",
        "log_file": "/path/to/service.log",
        "process_pattern": "vllm serve.*my-model",
        "gpus": [0, 1]
    }
}
```

### 4. 启动管理系统

使用启动脚本（推荐）：
```bash
./start.sh
```

或直接运行：
```bash
python3 app.py
```

### 5. 访问管理界面

打开浏览器访问: **http://服务器IP:9000**

## ⚙️ 配置说明

### 服务配置项详解

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 服务显示名称 |
| `port` | int | ✅ | 服务监听端口 |
| `start_script` | string | ✅ | 启动脚本的绝对路径 |
| `stop_script` | string | ✅ | 停止脚本的绝对路径 |
| `log_file` | string | ✅ | 日志文件的绝对路径 |
| `process_pattern` | string | ✅ | 用于 pgrep 识别进程的正则表达式 |
| `gpus` | array | ❌ | 服务使用的 GPU 编号列表（仅用于显示） |

### 完整配置示例

```json
{
    "qwen_72b": {
        "name": "Qwen-72B-Chat",
        "port": 8000,
        "start_script": "/opt/models/scripts/start_qwen72b.sh",
        "stop_script": "/opt/models/scripts/stop_qwen72b.sh",
        "log_file": "/var/log/vllm/qwen72b.log",
        "process_pattern": "vllm serve.*Qwen.*72B",
        "gpus": [0, 1, 2, 3]
    },
    "llama3_70b": {
        "name": "LLaMA-3-70B-Instruct",
        "port": 8001,
        "start_script": "/opt/models/scripts/start_llama3.sh",
        "stop_script": "/opt/models/scripts/stop_llama3.sh",
        "log_file": "/var/log/vllm/llama3.log",
        "process_pattern": "vllm serve.*llama-3-70b",
        "gpus": [4, 5, 6, 7]
    },
    "mistral_7b": {
        "name": "Mistral-7B-Instruct",
        "port": 8002,
        "start_script": "/opt/models/scripts/start_mistral.sh",
        "stop_script": "/opt/models/scripts/stop_mistral.sh",
        "log_file": "/var/log/vllm/mistral.log",
        "process_pattern": "vllm serve.*mistral",
        "gpus": [0]
    }
}
```

### 启动/停止脚本示例

**启动脚本** (`start_model.sh`):
```bash
#!/bin/bash

MODEL_PATH="/path/to/model"
LOG_FILE="/var/log/vllm/model.log"
PORT=8000

# 检查服务是否已运行
if pgrep -f "vllm serve.*my-model" > /dev/null; then
    echo "服务已在运行"
    exit 0
fi

# 启动服务
nohup vllm serve $MODEL_PATH \
    --port $PORT \
    --host 0.0.0.0 \
    --gpu-memory-utilization 0.9 \
    > $LOG_FILE 2>&1 &

echo "服务启动成功"
```

**停止脚本** (`stop_model.sh`):
```bash
#!/bin/bash

# 查找并停止进程
if pgrep -f "vllm serve.*my-model" > /dev/null; then
    pkill -f "vllm serve.*my-model"
    sleep 2
    # 如果进程仍在运行，强制终止
    if pgrep -f "vllm serve.*my-model" > /dev/null; then
        pkill -9 -f "vllm serve.*my-model"
    fi
    echo "服务已停止"
else
    echo "服务未运行"
fi
```

记得给脚本添加执行权限：
```bash
chmod +x start_model.sh stop_model.sh
```

## 📖 使用说明

### Web 界面操作

#### 1. 查看服务状态

服务卡片会显示：
- **运行中**（绿色标签）：服务正常运行
  - 进程 PID
  - CPU 使用率
  - 内存占用
  - GPU 显存占用
  - 启动时间
- **已停止**（红色标签）：服务未运行

#### 2. 启动服务

1. 找到要启动的服务卡片
2. 点击"启动"按钮
3. 等待启动完成（可能需要 1-5 分钟）
4. 启动成功后会弹出提示，按钮自动禁用

#### 3. 停止服务

1. 找到要停止的服务卡片
2. 点击"停止"按钮
3. 确认操作
4. 等待停止完成
5. 停止成功后会弹出提示，按钮自动禁用

#### 4. 查看日志

1. 点击服务卡片的"日志"按钮
2. 在弹出的对话框中查看最近 200 行日志
3. 日志以终端风格显示，便于阅读
4. 点击关闭按钮或对话框外部区域关闭日志窗口

#### 5. GPU 监控

GPU 监控面板实时显示每个 GPU 的：
- **GPU 利用率** - 当前计算使用率百分比
- **显存使用** - 已用显存 / 总显存
- **温度** - 当前 GPU 温度（摄氏度）
- **功耗** - 当前功耗 / 功耗限制（瓦特）

#### 6. 系统资源监控

系统资源面板显示：
- **CPU 使用率** - 当前 CPU 使用百分比
- **内存使用率** - 当前内存使用百分比
- **内存使用** - 已用内存 / 总内存（GB）
- **磁盘使用率** - 当前磁盘使用百分比

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HOST` | 0.0.0.0 | 监听的主机地址 |
| `PORT` | 9000 | 监听的端口号 |

使用示例：
```bash
# 只监听本地
HOST=127.0.0.1 python3 app.py

# 使用自定义端口
PORT=8080 python3 app.py

# 同时设置主机和端口
HOST=0.0.0.0 PORT=8888 python3 app.py
```

## 📁 项目结构

```
vllm-model-manager/
├── app.py                      # Flask 应用主程序
├── templates/
│   └── index.html             # Web 界面模板
├── static/                    # 静态资源目录（预留）
├── config/
│   ├── services.json          # 服务配置文件（需自行创建）
│   └── services.json.example  # 配置文件示例
├── requirements.txt           # Python 依赖列表
├── start.sh                   # 启动脚本
├── .gitignore                # Git 忽略文件
├── LICENSE                   # MIT 开源协议
├── README.md                 # 英文文档
└── README_CN.md              # 中文文档（本文件）
```

## 🔧 生产部署

### 使用 systemd 管理服务

创建系统服务文件 `/etc/systemd/system/vllm-manager.service`：

```ini
[Unit]
Description=LLM Model Manager
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/vllm-model-manager
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
Environment="PORT=9000"
Environment="HOST=0.0.0.0"
ExecStart=/usr/bin/python3 /opt/vllm-model-manager/app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

管理服务：
```bash
# 重新加载 systemd 配置
sudo systemctl daemon-reload

# 设置开机自启
sudo systemctl enable vllm-manager

# 启动服务
sudo systemctl start vllm-manager

# 查看状态
sudo systemctl status vllm-manager

# 查看日志
sudo journalctl -u vllm-manager -f
```

### 使用 Nginx 反向代理

安装 Nginx：
```bash
sudo apt install nginx
```

创建配置文件 `/etc/nginx/sites-available/vllm-manager`：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # 如果需要 HTTPS，取消下面的注释
    # listen 443 ssl;
    # ssl_certificate /path/to/cert.pem;
    # ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:9000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket 支持（如果需要）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

启用配置：
```bash
sudo ln -s /etc/nginx/sites-available/vllm-manager /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 使用 Docker 部署（开发中）

创建 `Dockerfile`：

```dockerfile
FROM python:3.10-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    curl \
    procps \
    && rm -rf /var/lib/apt/lists/*

# 复制项目文件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 暴露端口
EXPOSE 9000

# 启动应用
CMD ["python3", "app.py"]
```

构建和运行：
```bash
docker build -t vllm-manager .
docker run -d -p 9000:9000 \
    -v /path/to/config:/app/config \
    --name vllm-manager \
    vllm-manager
```

## 🔒 安全建议

### 1. 防火墙配置

只允许特定 IP 访问管理端口：
```bash
# UFW 防火墙
sudo ufw allow from 192.168.1.0/24 to any port 9000
sudo ufw deny 9000

# iptables
sudo iptables -A INPUT -p tcp -s 192.168.1.0/24 --dport 9000 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 9000 -j DROP
```

### 2. 添加 HTTP 基础认证

安装 `flask-httpauth`：
```bash
pip install flask-httpauth
```

修改 `app.py` 添加认证：
```python
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash

auth = HTTPBasicAuth()

users = {
    "admin": generate_password_hash("your-strong-password")
}

@auth.verify_password
def verify_password(username, password):
    if username in users and check_password_hash(users.get(username), password):
        return username

# 在所有路由上添加装饰器
@app.route('/')
@auth.login_required
def index():
    return render_template('index.html')
```

### 3. 使用 HTTPS

使用 Let's Encrypt 获取免费 SSL 证书：
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

### 4. 其他安全措施

- 定期更新依赖包
- 使用强密码
- 限制文件访问权限
- 定期备份配置文件
- 启用日志审计

## ❓ 常见问题

### Q1: GPU 信息无法显示怎么办？

**A:** 检查以下几点：
1. 确保 `nvidia-smi` 命令可用：
   ```bash
   nvidia-smi
   ```
2. 检查当前用户是否有权限执行 nvidia-smi
3. 确认 CUDA 驱动已正确安装

### Q2: 服务启动失败怎么办？

**A:** 按以下步骤排查：
1. 检查启动脚本路径是否正确
2. 确认启动脚本有执行权限：
   ```bash
   chmod +x /path/to/start_script.sh
   ```
3. 手动执行启动脚本，查看错误信息
4. 检查 GPU 是否被其他进程占用
5. 检查端口是否被占用：
   ```bash
   netstat -tlnp | grep 端口号
   ```
6. 查看服务日志获取详细错误信息

### Q3: 如何添加新的服务？

**A:** 按以下步骤操作：
1. 编辑 `config/services.json`
2. 添加新服务的配置
3. 保存文件
4. 重启管理系统
5. 刷新浏览器页面

### Q4: 可以管理非 vLLM 服务吗？

**A:** 可以！本系统可以管理任何通过脚本启动的服务。只需要提供：
- 启动脚本
- 停止脚本
- 日志文件路径
- 进程识别模式（用于 pgrep）

### Q5: 为什么服务状态显示运行中，但无法访问？

**A:** 可能的原因：
1. 服务正在启动中，还未完全就绪
2. 防火墙阻止了端口访问
3. 服务监听在 127.0.0.1，只能本地访问
4. 网络配置问题

解决方法：
```bash
# 检查端口监听
netstat -tlnp | grep 端口号

# 测试本地访问
curl http://localhost:端口号/health

# 检查防火墙
sudo ufw status
```

### Q6: 如何查看管理系统自身的日志？

**A:** 如果使用 systemd：
```bash
sudo journalctl -u vllm-manager -f
```

如果直接运行：查看启动时的终端输出

### Q7: 支持多用户吗？

**A:** 当前版本不支持多用户系统。建议：
- 使用 Nginx 添加基础认证
- 或通过防火墙限制访问
- 未来版本会考虑添加用户系统

## 🗺️ 开发计划

### 近期计划

- [ ] 支持 Docker 一键部署
- [ ] 添加完整的用户认证系统
- [ ] 支持多语言切换（中文/英文）
- [ ] 添加服务配置在线编辑功能

### 中期计划

- [ ] 性能图表和历史数据展示
- [ ] 邮件/钉钉/企业微信告警通知
- [ ] API 密钥管理
- [ ] 服务健康检查和自动重启
- [ ] 批量操作支持

### 长期计划

- [ ] 支持多节点管理
- [ ] 分布式部署
- [ ] 负载均衡配置
- [ ] 服务编排和依赖管理
- [ ] Kubernetes 集成

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

### 提交 Issue

如果你发现了 bug 或有新功能建议：
1. 搜索现有 Issue，避免重复
2. 使用 Issue 模板
3. 提供详细的问题描述和复现步骤
4. 附上相关的日志和截图

### 提交 Pull Request

1. Fork 本项目
2. 创建特性分支：
   ```bash
   git checkout -b feature/AmazingFeature
   ```
3. 提交更改：
   ```bash
   git commit -m 'Add some AmazingFeature'
   ```
4. 推送到分支：
   ```bash
   git push origin feature/AmazingFeature
   ```
5. 开启 Pull Request

### 代码规范

- 遵循 PEP 8 Python 代码规范
- 添加适当的注释
- 更新相关文档
- 确保代码能正常运行

## 📜 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

这意味着你可以：
- ✅ 商业使用
- ✅ 修改
- ✅ 分发
- ✅ 私人使用

但需要：
- 📋 包含许可证和版权声明

## 🙏 致谢

感谢以下开源项目：

- [Flask](https://flask.palletsprojects.com/) - 优秀的 Python Web 框架
- [vLLM](https://github.com/vllm-project/vllm) - 高性能 LLM 推理引擎
- [psutil](https://github.com/giampaolo/psutil) - 跨平台的系统和进程工具库
- [NVIDIA](https://www.nvidia.com/) - 提供强大的 GPU 和 CUDA 工具

## 📧 联系方式

如有问题或建议，欢迎通过以下方式联系：

- 📮 GitHub Issues: [提交 Issue](https://github.com/yourusername/vllm-model-manager/issues)
- 💬 Discussions: [参与讨论](https://github.com/yourusername/vllm-model-manager/discussions)

## ⭐ Star History

如果这个项目对你有帮助，请给个 Star ⭐️

---

<div align="center">

**[⬆ 回到顶部](#vllm-模型管理系统)**

Made with ❤️ by the community

</div>
