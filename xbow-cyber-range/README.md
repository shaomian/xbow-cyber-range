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

## 技术栈

- **后端**：Python 3.10+ / FastAPI / SQLAlchemy / Docker SDK / JWT
- **前端**：React 18 + Vite + Ant Design 5 + xterm.js
- **容器**：本地 Docker Daemon（Linux socket / Windows npipe / 远程 TCP 均可）

## 目录结构

```
xbow-cyber-range/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口 + 后台超时清理任务
│   │   ├── config.py            # 配置（环境变量/.env）
│   │   ├── models.py            # ORM 模型
│   │   ├── database.py          # engine/session/运行时配置读写
│   │   ├── schemas.py           # Pydantic 模型
│   │   ├── auth.py              # bcrypt 密码 + JWT
│   │   ├── deps.py              # 依赖：当前用户/管理员/运行时配置
│   │   ├── api/                 # 路由：auth users templates instances exec snapshots stats settings
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

> 在线修改的端口范围/超时等保存在数据库 `settings` 表，覆盖 `.env` 默认值。

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

> 两类实例（compose / 单容器）在同一「实例管理」列表统一管理，共享超时回收、续期、倒计时、终端、日志。

## API 速览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/login` | 登录获取 JWT |
| GET | `/api/templates` | 模板列表 |
| POST | `/api/instances` | 启动实例 |
| GET | `/api/instances` | 实例列表（含 remaining_seconds） |
| POST | `/api/instances/{id}/stop` | 停止 |
| POST | `/api/instances/{id}/extend` | 续期 |
| PUT | `/api/instances/{id}/timeout` | 重设超时 |
| WS | `/api/instances/{id}/terminal?token=...` | 终端 WebSocket |
| GET | `/api/stats/system` | 系统资源 |
| GET | `/api/stats/instances` | 容器资源 |
| GET/PUT | `/api/settings` | 平台配置（管理员） |

完整文档见 `/docs`（FastAPI 自动生成）。

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
