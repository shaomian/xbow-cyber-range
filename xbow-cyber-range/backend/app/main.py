"""FastAPI 应用入口：挂载路由、CORS、后台超时清理任务。"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import models
from .config import settings
from .api import auth as auth_api
from .api import benchmarks as benchmarks_api
from .api import exec as exec_api
from .api import instances as instances_api
from .api import settings as settings_api
from .api import snapshots as snapshots_api
from .api import stats as stats_api
from .api import templates as templates_api
from .database import SessionLocal, init_db
from .services import instance_service
from . import mcp_server as mcp_server_module

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("xbow_cyber_range")


app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MCP HTTP 端点尾斜杠归一化中间件：把无尾斜杠的 /mcp 重写为 /mcp/，
# 避免 Starlette Mount 默认的 307 重定向——很多 MCP 客户端用 POST 直发
# /mcp 且不跟随 307（POST 不自动跳转是正确行为），会导致连接失败。
# 此中间件在路由前改写 scope.path，使 Mount 直接命中，不再 307。
_mcp_http_path_norm = (settings.mcp_http_path or "").strip().rstrip("/") or "/mcp"


@app.middleware("http")
async def _mcp_trailing_slash_normalizer(request, call_next):
    if request.url.path == _mcp_http_path_norm:
        scope = request.scope
        new_path = _mcp_http_path_norm + "/"
        scope["path"] = new_path
        scope["raw_path"] = new_path.encode("latin-1")
    return await call_next(request)


@app.on_event("startup")
def _on_startup() -> None:
    init_db()
    Path(settings.compose_work_dir).mkdir(parents=True, exist_ok=True)
    logger.info("数据库已初始化")


@app.on_event("startup")
def _create_default_admin() -> None:
    """若无任何用户，自动创建默认管理员 admin / admin123（仅一次）。"""
    db = SessionLocal()
    try:
        from . import auth
        any_user = db.query(models.User).first()
        if any_user is None:
            admin = models.User(
                username="admin",
                hashed_password=auth.hash_password("admin123"),
                is_admin=True,
            )
            db.add(admin)
            db.commit()
            logger.warning("已创建默认管理员: admin / admin123 （请尽快修改密码）")
        # 若无默认模板，注入几个示例
        if db.query(models.Template).count() == 0:
            samples = [
                models.Template(name="kali-linux", image="kalilinux/kali-rolling", description="Kali 渗透测试", exposed_ports=[22], command="/bin/bash"),
                models.Template(name="ubuntu-base", image="ubuntu:22.04", description="Ubuntu 22.04 基础环境", exposed_ports=[], command="/bin/bash"),
                models.Template(name="web-dvwa", image="vulnerables/web-dvwa", description="DVWA Web 靶场", exposed_ports=[80], command=""),
                models.Template(name="metasploit", image="metasploitframework/metasploit-framework", description="Metasploit Framework", exposed_ports=[], command=""),
            ]
            db.add_all(samples)
            db.commit()
            logger.info("已注入 4 个示例模板")
    finally:
        db.close()


async def _reaper_loop() -> None:
    """后台定时扫描过期实例并停止；同时周期性同步 DB 状态与 docker 实际状态。"""
    interval = max(5, settings.reaper_interval_seconds)
    while True:
        await asyncio.sleep(interval)
        db = SessionLocal()
        try:
            # 先同步状态：让重启后残留的 running/creating/paused/restarting/partial
            # 实例的状态匹配 docker 实际状态（exited/stopped/removed）。
            instance_service.sync_all_status(db)
            stopped = instance_service.reap_expired(db)
            if stopped:
                logger.info("自动停止过期实例: %s", stopped)
        except Exception as e:  # noqa: BLE001
            logger.warning("reaper 异常: %s", e)
        finally:
            db.close()


@app.on_event("startup")
async def _start_reaper() -> None:
    # 启动时立即同步一次实例状态：覆盖环境重启 / Docker daemon 重启后
    # DB 中仍残留 running/creating 但容器实际已退出 的情况，避免 web 显示陈旧状态。
    db = SessionLocal()
    try:
        instance_service.sync_all_status(db)
        logger.info("启动时已同步实例状态")
    except Exception as e:  # noqa: BLE001
        logger.warning("启动时同步实例状态失败: %s", e)
    finally:
        db.close()
    asyncio.create_task(_reaper_loop())


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name}


# 挂载路由
app.include_router(auth_api.router)
app.include_router(auth_api.admin_router)
app.include_router(templates_api.router)
app.include_router(instances_api.router)
app.include_router(benchmarks_api.router)
app.include_router(exec_api.router)
app.include_router(snapshots_api.router)
app.include_router(stats_api.router)
app.include_router(settings_api.router)

# 挂载 MCP HTTP/SSE 端点（供远程 agent 通过 streamable HTTP 接入）。
# 端点路径见 settings.mcp_http_path；置空则不挂载（仅以独立 stdio 进程运行）。
# 注意：streamable-http 子应用的 session manager 需要在应用 lifespan 内启动；
# 挂载到 FastAPI 时父应用不会自动 propagate 子应用 lifespan，故在此手动驱动。
_mcp_http_path = (settings.mcp_http_path or "").strip()
_mcp_session_cm = None

if _mcp_http_path:
    try:
        _mcp_asgi = mcp_server_module.streamable_http_asgi()
        # 标准 Mount 即可：上面的 _mcp_trailing_slash_normalizer 已把 /mcp
        # 重写为 /mcp/，Mount 会直接命中并转发给 MCP 子应用，不再走 307。
        app.mount(_mcp_http_path, _mcp_asgi)
        logger.info("MCP HTTP 端点已挂载: %s (无尾斜杠 /mcp 也可直连，不再 307)", _mcp_http_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("挂载 MCP HTTP 端点失败: %s", e)


@app.on_event("startup")
async def _start_mcp_lifespan() -> None:
    global _mcp_session_cm
    if not _mcp_http_path:
        return
    mgr = mcp_server_module.get_server().session_manager
    if mgr is None:
        return
    _mcp_session_cm = mgr.run()
    await _mcp_session_cm.__aenter__()
    logger.info("MCP session manager 已启动")


@app.on_event("shutdown")
async def _stop_mcp_lifespan() -> None:
    global _mcp_session_cm
    if _mcp_session_cm is not None:
        try:
            await _mcp_session_cm.__aexit__(None, None, None)
        except Exception as e:  # noqa: BLE001
            logger.warning("MCP session manager 关闭异常: %s", e)
        _mcp_session_cm = None
