"""平台级配置路由（管理员在线修改端口范围/超时/默认终端命令）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..config import settings
from ..deps import get_db_dep, get_admin_user, get_runtime_settings, RuntimeSettings
from ..database import set_setting, get_setting

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=schemas.PlatformSettingsOut)
def get_platform_settings(
    _admin: models.User = Depends(get_admin_user),
    rs: RuntimeSettings = Depends(get_runtime_settings),
):
    return schemas.PlatformSettingsOut(
        port_range_start=rs.port_range_start,
        port_range_end=rs.port_range_end,
        default_instance_timeout=rs.default_instance_timeout,
        max_instance_timeout=rs.max_instance_timeout,
        docker_host=rs.docker_host,
        terminal_default_command=rs.terminal_default_command,
        reaper_interval_seconds=rs.reaper_interval_seconds,
        benchmarks_root=rs.benchmarks_root,
        allow_registration=rs.allow_registration,
    )


@router.put("", response_model=schemas.PlatformSettingsOut)
def update_platform_settings(
    payload: schemas.PlatformSettingsUpdateIn,
    _admin: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db_dep),
    rs: RuntimeSettings = Depends(get_runtime_settings),
):
    if payload.port_range_start is not None:
        end = payload.port_range_end if payload.port_range_end is not None else rs.port_range_end
        if payload.port_range_start >= end:
            raise HTTPException(400, "端口范围起始必须小于结束")
        set_setting(db, "port_range_start", payload.port_range_start)
    if payload.port_range_end is not None:
        start = payload.port_range_start if payload.port_range_start is not None else rs.port_range_start
        if start >= payload.port_range_end:
            raise HTTPException(400, "端口范围起始必须小于结束")
        if payload.port_range_end - start < 10:
            raise HTTPException(400, "端口范围至少 10 个端口")
        set_setting(db, "port_range_end", payload.port_range_end)
    if payload.default_instance_timeout is not None:
        set_setting(db, "default_instance_timeout", payload.default_instance_timeout)
    if payload.max_instance_timeout is not None:
        set_setting(db, "max_instance_timeout", payload.max_instance_timeout)
    if payload.terminal_default_command is not None:
        set_setting(db, "terminal_default_command", payload.terminal_default_command)
    if payload.benchmarks_root is not None:
        set_setting(db, "benchmarks_root", payload.benchmarks_root)
    if payload.allow_registration is not None:
        set_setting(db, "allow_registration", payload.allow_registration)

    return get_platform_settings(_admin=_admin, rs=RuntimeSettings(db))
