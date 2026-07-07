"""资源监控路由。"""
from __future__ import annotations

import platform
import shutil

import psutil
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..deps import get_db_dep, get_current_user
from ..services import instance_service
from ..services.docker_service import DockerError, docker_service

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/system", response_model=schemas.SystemStatsOut)
def system_stats(_user: models.User = Depends(get_current_user)):
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    disk_path = "C:\\" if platform.system() == "Windows" else "/"
    disk = shutil.disk_usage(disk_path)
    disk_total = disk.total
    disk_used = disk.used
    disk_percent = round(disk_used / disk_total * 100, 1) if disk_total else 0.0

    try:
        containers = docker_service.client.containers.list(all=True)
        running = [c for c in containers if c.status == "running"]
    except Exception:  # noqa: BLE001
        containers, running = [], []

    return schemas.SystemStatsOut(
        cpu_percent=round(cpu, 2),
        memory_percent=round(mem.percent, 2),
        memory_total_gb=round(mem.total / 1024 ** 3, 2),
        disk_percent=round(disk_percent, 2),
        containers_total=len(containers),
        containers_running=len(running),
    )


@router.get("/instances", response_model=list[schemas.ContainerStatsOut])
def instances_stats(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
):
    insts = instance_service.list_instances(db, user, only_active=True)
    out = []
    for inst in insts:
        if not inst.container_id:
            continue
        try:
            s = docker_service.stats(inst.container_id)
        except DockerError:
            s = {}
        out.append(schemas.ContainerStatsOut(
            instance_id=inst.id,
            container_id=inst.container_id[:12] if inst.container_id else "",
            name=inst.name,
            cpu_percent=s.get("cpu_percent", 0.0),
            memory_used_mb=s.get("memory_used_mb", 0.0),
            memory_limit_mb=s.get("memory_limit_mb", 0.0),
            net_rx_kb=s.get("net_rx_kb", 0.0),
            net_tx_kb=s.get("net_tx_kb", 0.0),
            status=s.get("status", inst.status),
        ))
    return out


@router.get("/instances/{instance_id}", response_model=schemas.ContainerStatsOut)
def instance_stats(
    instance_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
):
    inst = instance_service.get_instance(db, instance_id, user)
    if not inst:
        raise HTTPException(404, "实例不存在")
    if not inst.container_id:
        raise HTTPException(400, "容器尚未创建")
    try:
        s = docker_service.stats(inst.container_id)
    except DockerError as e:
        raise HTTPException(502, str(e))
    return schemas.ContainerStatsOut(
        instance_id=inst.id,
        container_id=inst.container_id[:12],
        name=inst.name,
        cpu_percent=s.get("cpu_percent", 0.0),
        memory_used_mb=s.get("memory_used_mb", 0.0),
        memory_limit_mb=s.get("memory_limit_mb", 0.0),
        net_rx_kb=s.get("net_rx_kb", 0.0),
        net_tx_kb=s.get("net_tx_kb", 0.0),
        status=s.get("status", inst.status),
    )
