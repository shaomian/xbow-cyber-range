"""容器实例路由：列表/启动/停止/启动/删除/重启/续期/改超时/日志。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..deps import get_db_dep, get_current_user, get_runtime_settings
from ..services import instance_service
from ..services.docker_service import DockerError, docker_service

router = APIRouter(prefix="/api/instances", tags=["instances"])


def _to_out(inst: models.Instance, rs=None) -> schemas.InstanceOut:
    out = schemas.InstanceOut.model_validate(inst)
    out.remaining_seconds = instance_service.remaining_seconds(inst.expires_at)
    if rs is not None:
        real = docker_service.container_status(inst.container_id) if inst.container_id else "removed"
        if real == "running":
            out.status = "running"
        elif real in {"exited", "dead"} and inst.status not in {"stopped", "removed"}:
            out.status = "exited"
        elif real == "removed":
            out.status = "removed"
    return out


@router.get("", response_model=list[schemas.InstanceOut])
def list_instances(
    only_active: bool = False,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
    rs=Depends(get_runtime_settings),
):
    instance_service.sync_all_status(db)
    insts = instance_service.list_instances(db, user, only_active=only_active)
    return [_to_out(i, rs) for i in insts]


@router.get("/{instance_id}", response_model=schemas.InstanceOut)
def get_instance(
    instance_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
    rs=Depends(get_runtime_settings),
):
    inst = instance_service.get_instance(db, instance_id, user)
    if not inst:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "实例不存在")
    instance_service._apply_runtime_status(inst)
    db.commit()
    return _to_out(inst, rs)


@router.post("", response_model=schemas.InstanceOut, status_code=status.HTTP_201_CREATED)
def start_instance(
    payload: schemas.InstanceStartIn,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
    rs=Depends(get_runtime_settings),
):
    inst, err = instance_service.start_instance(db, user, payload, rs)
    if inst is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, err)
    return _to_out(inst, rs)


@router.post("/{instance_id}/stop", response_model=schemas.InstanceOut)
def stop(
    instance_id: int,
    timeout: int = 10,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
    rs=Depends(get_runtime_settings),
):
    inst = instance_service.get_instance(db, instance_id, user)
    if not inst:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "实例不存在")
    instance_service.stop_instance(db, inst, timeout=timeout)
    return _to_out(inst, rs)


@router.post("/{instance_id}/start", response_model=schemas.InstanceOut)
def start_existing(
    instance_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
    rs=Depends(get_runtime_settings),
):
    inst = instance_service.get_instance(db, instance_id, user)
    if not inst:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "实例不存在")
    try:
        instance_service.start_existing(db, inst)
    except DockerError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))
    return _to_out(inst, rs)


@router.post("/{instance_id}/restart", response_model=schemas.InstanceOut)
def restart(
    instance_id: int,
    timeout: int = 10,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
    rs=Depends(get_runtime_settings),
):
    inst = instance_service.get_instance(db, instance_id, user)
    if not inst:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "实例不存在")
    if not inst.container_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "容器尚未创建")
    try:
        docker_service.restart(inst.container_id, timeout=timeout)
        inst.status = "running"
        db.commit()
    except DockerError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))
    return _to_out(inst, rs)


@router.delete("/{instance_id}", response_model=schemas.MessageOut)
def remove(
    instance_id: int,
    force: bool = True,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
):
    inst = instance_service.get_instance(db, instance_id, user)
    if not inst:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "实例不存在")
    instance_service.remove_instance(db, inst, force=force)
    return schemas.MessageOut(message="实例已删除")


@router.post("/{instance_id}/extend", response_model=schemas.InstanceOut)
def extend(
    instance_id: int,
    payload: schemas.InstanceExtendIn,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
    rs=Depends(get_runtime_settings),
):
    inst = instance_service.get_instance(db, instance_id, user)
    if not inst:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "实例不存在")
    instance_service.extend_instance(db, inst, payload.add_seconds, rs)
    return _to_out(inst, rs)


@router.put("/{instance_id}/timeout", response_model=schemas.InstanceOut)
def set_timeout(
    instance_id: int,
    payload: schemas.InstanceUpdateTimeoutIn,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
    rs=Depends(get_runtime_settings),
):
    inst = instance_service.get_instance(db, instance_id, user)
    if not inst:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "实例不存在")
    instance_service.set_instance_timeout(db, inst, payload.timeout_seconds, rs)
    return _to_out(inst, rs)


@router.get("/{instance_id}/logs")
def logs(
    instance_id: int,
    tail: int = 500,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
):
    inst = instance_service.get_instance(db, instance_id, user)
    if not inst:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "实例不存在")
    if inst.kind == "compose":
        from ..services import benchmark_service
        if not inst.project_name:
            return {"logs": ""}
        return {"logs": benchmark_service.compose_logs(inst.project_name, tail=tail)}
    if not inst.container_id:
        return {"logs": ""}
    return {"logs": docker_service.logs(inst.container_id, tail=tail)}
