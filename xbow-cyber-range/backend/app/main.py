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
                models.Template(name="kali-linux", image="kali/kali-rolling", description="Kali 渗透测试", exposed_ports=[22], command="/bin/bash"),
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
    """后台定时扫描过期实例并停止。"""
    interval = max(5, settings.reaper_interval_seconds)
    while True:
        await asyncio.sleep(interval)
        db = SessionLocal()
        try:
            stopped = instance_service.reap_expired(db)
            if stopped:
                logger.info("自动停止过期实例: %s", stopped)
        except Exception as e:  # noqa: BLE001
            logger.warning("reaper 异常: %s", e)
        finally:
            db.close()


@app.on_event("startup")
async def _start_reaper() -> None:
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
