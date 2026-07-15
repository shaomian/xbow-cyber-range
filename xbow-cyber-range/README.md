# XBow CyberRange 靶场平台

基于容器化的网络安全靶场管理平台，通过 Web 端管理靶机镜像、启动/停止容器实例、终端进入容器、资源监控、超时自动回收等。

## 功能概览

| 模块 | 说明 |
| --- | --- |
| **靶场目录（XBEN）** | 扫描 104 个 docker-compose benchmark，一键构建启动，端口自动重映射到随机范围 |
| **容器生命周期** | 列表 / 启动 / 停止 / 重启 / 删除 / 日志查看 |
| 靶机模板库 | 预置镜像+命令+端口+资源限制，一键启动；支持自定义/编辑 |
| 端口映射 | 容器端口在**可配置的随机范围**内自动分配宿主端口，页面直接点击访问 |
| **终端进入** | 点击「终端」即可在浏览器中打开容器内 shell（xterm.js + WebSocket TTY） |
| **超时自动停止** | 每个实例有过期时间，后台扫描自动停止；页面有**实时倒计时** |
| **手动续期** | 用户可一键延长实例存活时间（受管理员配置的上限约束） |
| 用户登录与隔离 | JWT 认证；普通用户只能看到/操作自己的实例；管理员可管理全部 |
| 资源监控 | 系统级 CPU/内存/磁盘 + 每个容器 CPU/内存/网络 |
| 环境快照与历史 | 对运行中容器 `docker commit` 生成镜像并记录 |
| 系统设置（管理员） | 在线修改端口范围、默认/最大超时、终端命令、靶场目录等 |
| **MCP Server** | 将容器生命周期（列表/启动/停止/重启/删除/日志/续期）以 MCP 工具暴露，接入 agent / LLM（stdio + HTTP） |

## 技术栈

- **后端**：Python 3.10+ / FastAPI / SQLAlchemy / Docker SDK / JWT
- **前端**：React 18 + Vite + Ant Design 5 + xterm.js
- **容器**：本地 Docker Daemon（Linux socket / Windows npipe / 远程 TCP 均可）

## 目录结构

```
xbow-cyber-range/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口 + 后台超时清理 + MCP HTTP 挂载
│   │   ├── config.py            # 配置（环境变量/.env）
│   │   ├── models.py            # ORM 模型
│   │   ├── database.py          # engine/session/运行时配置读写
│   │   ├── schemas.py           # Pydantic 模型
│   │   ├── auth.py              # bcrypt 密码 + JWT
│   │   ├── deps.py              # 依赖：当前用户/管理员/运行时配置
│   │   ├── api/                 # 路由：auth users templates instances exec snapshots stats settings
│   │   ├── mcp_server.py        # MCP Server（容器生命周期工具，stdio + HTTP）
│   │   └── services/
│   │       ├── docker_service.py    # Docker SDK 封装
│   │       └── instance_service.py  # 实例业务逻辑
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── api/                 # axios 客户端 + 各模块 API
│   │   ├── components/          # MainLayout / Countdown / TerminalPanel
│   │   ├── pages/               # Login Dashboard Templates Instances InstanceDetail Users Settings
│   │   ├── App.tsx              # 路由 + 守卫
│   │   └── main.tsx
│   └── vite.config.ts           # 含 /api 代理到 8000
└── start.bat                    # 一键启动（Windows）
```

## 快速开始

### 前置条件
- 已安装 Docker 并正在运行（`docker version` 可用）
- Python 3.10+
- Node.js 18+

### 1. 启动后端
```bash
cd xbow-cyber-range/backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux:   source .venv/bin/activate
pip install -r requirements.txt

# 可选：复制并修改配置
copy .env.example .env   # Windows
# cp .env.example .env   # Linux

python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
首次启动会自动：
- 初始化 SQLite 数据库（`xbow_cyber_range.db`）
- 创建默认管理员 `admin / admin123`
- 注入 4 个示例模板（kali、ubuntu、dvwa、metasploit）

### 2. 启动前端
```bash
cd xbow-cyber-range/frontend
npm install
npm run dev
```

### 3. 访问
- 前端：http://127.0.0.1:5173
- 后端 API 文档：http://127.0.0.1:8000/docs
- 默认账号：`admin / admin123`（**请尽快在「用户管理」改密码**）

### Windows 一键启动
直接双击 `start.bat`。

## 配置说明

所有配置通过环境变量（前缀 `XBOW_CYBER_RANGE_`）或 `.env` 文件读取，见 `backend/.env.example`。关键项：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `XBOW_CYBER_RANGE_DOCKER_HOST` | 自动 | Docker 连接地址；留空按平台选（Win=npipe, Linux=unix sock） |
| `XBOW_CYBER_RANGE_PORT_RANGE_START/END` | 20000 / 30000 | 随机端口分配范围，管理员可在「系统设置」页在线改 |
| `XBOW_CYBER_RANGE_DEFAULT_INSTANCE_TIMEOUT` | 3600 | 实例默认超时秒数 |
| `XBOW_CYBER_RANGE_MAX_INSTANCE_TIMEOUT` | 28800 | 单次续期/超时上限 |
| `XBOW_CYBER_RANGE_DATABASE_URL` | sqlite | 可改 MySQL：`mysql+aiomysql://user:pass@host/db` |
| `XBOW_CYBER_RANGE_PUBLIC_HOST` | 空（用 `127.0.0.1`） | 对外访问地址（不含端口）；远程访问实例/agent 调用需设为公网 IP 或域名（容器端口绑定 `0.0.0.0`） |

> 在线修改的端口范围/超时等保存在数据库 `settings` 表，覆盖 `.env` 默认值。

> ⚠️ **远程访问提示**：若后端供公网/远程 agent 接入，务必设置 `XBOW_CYBER_RANGE_PUBLIC_HOST` 为服务器对外可达 IP 或域名。否则实例返回的 `host` 字段为 `127.0.0.1`，远程用户/agent 用该地址无法访问靶场端口。

## 使用流程

### A. 管理 XBEN benchmarks（靶场目录）
1. 首次启动时自动探测 `../xbow-validation-benchmarks-main/benchmarks` 目录（可在「系统设置」改）
2. 打开「靶场目录」页，看到 104 个 benchmark（含服务数、端口、Flag）
3. 搜索/选择目标，点「启动」→ 平台用 `docker compose build` 构建（复刻 `make run`，FLAG 由 sha256 生成）
4. 构建期间状态为 `creating`，完成后变 `running`；固定宿主端口被重映射到随机范围（互不冲突）
5. 在「实例管理」查看端口映射（点击直达）、倒计时、终端、日志；可停止/续期/删除

### B. 管理自定义单镜像容器（靶机模板）
1. **管理员**在「靶机模板」页新建模板（选择镜像、暴露端口、资源限制）
2. 在「实例管理」点「启动实例」选择模板 → 系统在端口范围内随机分配宿主端口
3. 实例列表显示状态、端口映射（点击直达）、**剩余时间倒计时**
4. 点「终端」在浏览器内进入容器 shell 执行命令
5. 测试完成可手动「停止」；忘记关也无需担心——到点自动停止
6. 需要更多时间点「续期」延长；管理员可在「系统设置」调整默认/最大超时与端口范围
7. 对已过期自动停止的实例直接点「启动」即可，系统会自动续期至默认超时，无需先续期

> 两类实例（compose / 单容器）在同一「实例管理」列表统一管理，共享超时回收、续期、倒计时、终端、日志。

## API 速览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/login` | 登录获取 JWT |
| GET | `/api/templates` | 模板列表 |
| POST | `/api/instances` | 启动实例 |
| GET | `/api/instances` | 实例列表（含 remaining_seconds） |
| POST | `/api/instances/{id}/stop` | 停止 |
| POST | `/api/instances/{id}/start` | 启动已停实例（已过期则自动续期至默认/指定超时） |
| POST | `/api/instances/{id}/extend` | 续期 |
| PUT | `/api/instances/{id}/timeout` | 重设超时 |
| WS | `/api/instances/{id}/terminal?token=...` | 终端 WebSocket |
| GET | `/api/stats/system` | 系统资源 |
| GET | `/api/stats/instances` | 容器资源 |
| GET/PUT | `/api/settings` | 平台配置（管理员） |

完整文档见 `/docs`（FastAPI 自动生成）。

## MCP Server（供 agent / LLM 工具接入）

平台内置 MCP（Model Context Protocol）Server，把容器生命周期管理能力以工具形式暴露给 agent（Claude Desktop / opencode / Cursor 等）。工具以**管理员身份**执行，复用现有后端服务。

### 暴露的 MCP 工具

> ⚠️ **关于 flag**：MCP 工具**绝不返回 flag**（包括 `flag` / `computed_flag` / `env_flag`，统一显示为 `hidden`）。
> flag 只能由 agent 启动目标实例后，对靶机进行 **Web 安全漏洞利用**，在容器/环境内实际获取——
> 这正是靶场的安全训练目标。平台管理 Web（管理员鉴权）可核对 flag，仅供平台运维而非 agent。

| 工具 | 说明 |
| --- | --- |
| `list_instances` | 列出容器/compose 实例（含状态、端口、剩余秒数；**不含 flag**） |
| `get_instance` | 查询单个实例详情与实时状态（**不含 flag**） |
| `start_instance` | 启动新容器实例（按 template_id 或 image） |
| `start_stopped_instance` | 启动已停止的实例（不重建容器） |
| `stop_instance` | 停止实例 |
| `restart_instance` | 重启实例 |
| `remove_instance` | 删除实例（停止并移除） |
| `get_instance_logs` | 查看日志（单容器 / compose 多服务合并） |
| `extend_instance` | 续期（延长存活时间） |
| `set_instance_timeout` | 重设超时 |
| `list_templates` | 列出靶机模板 |
| `list_benchmarks` | 列出 XBEN benchmarks（compose 栈；**不含 flag**） |
| `get_benchmark` | 查询 benchmark 详情（端口/服务/描述；**不含 flag**） |
| `launch_benchmark` | 启动 benchmark 为 compose 实例（返回信息**不含 flag**） |
| `get_system_stats` | 宿主机资源概览 |
| `get_instance_stats` | 单实例实时资源占用 |
| `ping_docker` | 测试 Docker 连通性 |
| `list_images` | 列出本地镜像 |

### 接入方式 A：stdio（推荐，用于本地 agent）

后端就绪后，以 stdio 传输独立运行：

```bash
cd xbow-cyber-range/backend
python -m app.mcp_server
```

在 agent 配置中注册该 MCP server。例如 Claude Desktop / opencode 的 MCP 配置（JSON）：

```json
{
  "mcpServers": {
    "xbow-cyber-range": {
      "command": "python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "J:/AI/augment/xbow-cyber-range/backend",
      "env": {
        "PYTHONWARNINGS": "ignore"
      }
    }
  }
}
```

stdio 模式下日志写入 `backend/.compose-work/mcp.log`（可用 `XBOW_CYBER_RANGE_MCP_STDIO_LOG_FILE` 覆盖）。

### 接入方式 B：HTTP / Streamable HTTP（用于远程 agent）

MCP HTTP 端点默认挂载在 FastAPI 应用的 `/mcp` 路径（随后端一起启动）。agent 客户端指向：

```
http://127.0.0.1:8000/mcp
```

- 协议：Streamable HTTP（MCP 2024-11-05 协议版本）
- 用 `POST` 发起 JSON-RPC，响应以 `text/event-stream`（SSE）形式返回
- 设置 `XBOW_CYBER_RANGE_MCP_HTTP_TOKEN` 后，所有请求须携带鉴权头 `Authorization: Bearer <token>`，否则返回 401
- 置空 `XBOW_CYBER_RANGE_MCP_HTTP_PATH` 即可禁用 HTTP 端点，仅保留 stdio

带鉴权的 agent 配置示例（HTTP transport）：

```json
{
  "name": "xbow-cyber-range",
  "transport": "http",
  "url": "http://your-host:8000/mcp",
  "headers": {
    "Authorization": "Bearer SilverNeedle"
  },
  "agents": ["default/master"],
  "enabled": true
}
```

### MCP 相关配置

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `XBOW_CYBER_RANGE_MCP_ADMIN_USERNAME` | 空 | agent impersonate 的管理员用户名；留空自动取首个活跃管理员 |
| `XBOW_CYBER_RANGE_MCP_HTTP_PATH` | `/mcp` | 挂载到 FastAPI 的 HTTP 端点路径前缀；置空禁用 |
| `XBOW_CYBER_RANGE_MCP_HTTP_TOKEN` | 空 | HTTP 端点 Bearer Token；客户端须带 `Authorization: Bearer <此值>`；留空不鉴权 |
| `XBOW_CYBER_RANGE_MCP_STDIO_LOG_FILE` | 空（用 `.compose-work/mcp.log`） | stdio 模式日志文件 |

## 安全注意
- 生产环境务必修改 `SECRET_KEY` 与 admin 密码
- 终端 WebSocket 通过 JWT query 参数鉴权，请走 HTTPS
- 特权模板会赋予容器特权权限，仅对可信用户开放

## 常见问题

**Q：启动某个 XBEN benchmark 时构建失败，apt 报 `connecting to 127.0.0.1:7897` 之类错误？**
A：这是本机代理（如 Clash/v2ray 监听 127.0.0.1:7897）被 Docker 构建容器继承所致——容器内的 127.0.0.1 指向容器自身，无法访问宿主代理。直接 `make run` 也会同样失败。解决办法（任选其一）：
- 关闭本机代理软件的「TUN/系统代理」后再构建；
- 在 Docker Desktop → Settings → Resources → Proxies 中正确配置代理（Docker 会自动转 `host.docker.internal`）；
- 用不需要 apt 下载的 benchmark（如 `XBEN-086-24` ruby 基础镜像）。

平台已在构建时显式传 `--build-arg http_proxy=` 等空值尝试清除代理，但守护进程级代理仍可能注入。

**Q：某些 benchmark 的 docker-compose.yml 有重复键？**
A：平台会用 PyYAML 规范化（去重复键）+ build context 转绝对路径后构建，透明修复此问题。

**Q：启动 compose benchmark 报 `failed to create network xxx: all predefined address pools have been fully subnetted`？**
A：Docker 默认地址池容量不足。Docker Desktop 出厂把 `172.17.0.0/16` 切成 `/20` 子网，只能容纳 **16 个**用户定义网络。每启动一个 compose benchmark 都会新建一个 project 网络，多次启动/失败重试后网络累积即耗尽池子，导致 daemon 拒绝再创建任何网络——表现就是新 benchmark 卡在 `creating`，点击启动直接报 `all predefined address pools have been fully subnetted`。

根治办法：扩容 Docker 地址池。编辑 daemon 配置后重启 Docker 守护进程：

- **Docker Desktop**：Settings → Docker Engine，在 JSON 中加 `default-address-pools`，Apply & Restart；
- **Linux**：编辑 `/etc/docker/daemon.json`（没有则新建），然后 `sudo systemctl restart docker`。

```json
{
  "default-address-pools": [
    {"base": "172.17.0.0/16", "size": 24},
    {"base": "172.18.0.0/16", "size": 24}
  ]
}
```

把 `/16` 切成 `/24` 子网可容纳 **256 个**网络，第二个 `/16` 做冗余，日常使用基本不会再耗尽。`size` 数值越大子网越小、可容纳网络越多（`24` 即足够本平台使用）。

> 改完后可用 `docker network prune -f` 清理一次历史遗留的孤儿网络，立刻释放存量。
> 平台代码层面已在每次删除/构建失败时清理对应 project 的容器与网络（见 `benchmark_service.compose_down` 的 `--rmi local` 和 `_force_remove_project` 的网络回收），正常使用不会再泄漏累积。

**Q：启动 benchmark 提示 `build 失败`，日志显示 apt 下载极慢或卡在某个大包（如 gcc）？**
A：这是 build 超时。平台对 `docker compose build` 设有超时（当前 3600 秒 / 1 小时），大型 benchmark（如 XBEN-001 需装 gcc 编译工具链）在 apt 源慢的网络上可能超时。解决办法（任选其一）：

1. **先手动 build，再回平台启动**（推荐，最快见效）：
   在 benchmark 目录直接 build，不受平台超时限制；build 完成后镜像缓存到本地，平台启动时复用缓存不再重新 build：
   ```bash
   cd <benchmarks 根>/XBEN-001-24
   docker compose build          # 不受超时限制，慢慢装
   # 完成后回平台点「启动」，平台直接用已缓存的镜像启动
   ```

2. **加速 apt 源**：慢的根因是 Dockerfile 里 `apt-get install` 走 `deb.debian.org` 官方源，国内访问慢。可给 Docker daemon 配 HTTP 代理（见上一条代理方案），或在 Dockerfile 里把 apt 源替换为国内镜像（如 `mirrors.tuna.tsinghua.edu.cn`）。

3. **用不需要 apt 下载的 benchmark**：部分 benchmark 基于已含完整工具链的镜像（如 `XBEN-086-24` ruby 基础镜像），build 极快。
