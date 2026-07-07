"""快照与历史路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..deps import get_db_dep, get_current_user
from ..services import instance_service
from ..services.docker_service import DockerError

router = APIRouter(prefix="/api/instances/{instance_id}/snapshots", tags=["snapshots"])


@router.get("", response_model=list[schemas.SnapshotOut])
def list_snapshots(
    instance_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
):
    inst = instance_service.get_instance(db, instance_id, user)
    if not inst:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "实例不存在")
    return inst.snapshots


@router.post("", response_model=schemas.SnapshotOut, status_code=status.HTTP_201_CREATED)
def create_snapshot(
    instance_id: int,
    payload: schemas.SnapshotCreateIn,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
):
    inst = instance_service.get_instance(db, instance_id, user)
    if not inst:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "实例不存在")
    try:
        return instance_service.commit_snapshot(db, inst, payload.image_tag, payload.note)
    except DockerError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))


@router.delete("/{snapshot_id}", response_model=schemas.MessageOut)
def delete_snapshot(
    instance_id: int,
    snapshot_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
):
    inst = instance_service.get_instance(db, instance_id, user)
    if not inst:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "实例不存在")
    snap = db.query(models.Snapshot).filter(
        models.Snapshot.id == snapshot_id, models.Snapshot.instance_id == inst.id
    ).first()
    if not snap:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "快照不存在")
    db.delete(snap)
    db.commit()
    return schemas.MessageOut(message="快照已删除")
