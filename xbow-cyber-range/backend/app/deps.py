"""FastAPI 依赖：当前用户、管理员校验、运行时配置。"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from . import auth, models
from .database import SessionLocal, get_db, get_setting
from .config import settings


def get_db_dep():
    yield from get_db()


def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db_dep),
) -> models.User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少认证信息")
    token = authorization.split(" ", 1)[1].strip()
    payload = auth.decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌无效或已过期")
    user = db.query(models.User).filter(models.User.username == payload["sub"]).first()
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "用户不存在或已禁用")
    return user


def get_admin_user(user: models.User = Depends(get_current_user)) -> models.User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user


# ---- 运行时配置（DB 覆盖 config.py）----
class RuntimeSettings:
    """聚合 config.py 默认 + DB 覆盖值的运行时配置视图。"""

    def __init__(self, db: Session):
        self.db = db

    @property
    def port_range_start(self) -> int:
        return get_setting(self.db, "port_range_start", settings.port_range_start)

    @property
    def port_range_end(self) -> int:
        return get_setting(self.db, "port_range_end", settings.port_range_end)

    @property
    def default_instance_timeout(self) -> int:
        return get_setting(self.db, "default_instance_timeout", settings.default_instance_timeout)

    @property
    def max_instance_timeout(self) -> int:
        return get_setting(self.db, "max_instance_timeout", settings.max_instance_timeout)

    @property
    def terminal_default_command(self) -> str:
        return get_setting(self.db, "terminal_default_command", settings.terminal_default_command)

    @property
    def reaper_interval_seconds(self) -> int:
        return settings.reaper_interval_seconds

    @property
    def docker_host(self) -> str:
        return settings.docker_host

    @property
    def benchmarks_root(self) -> str:
        return get_setting(self.db, "benchmarks_root", settings.benchmarks_root)


def get_runtime_settings(db: Session = Depends(get_db_dep)) -> RuntimeSettings:
    return RuntimeSettings(db)
