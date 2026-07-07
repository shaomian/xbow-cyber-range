"""靶机模板库路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..deps import get_db_dep, get_current_user, get_admin_user
from ..services.docker_service import docker_service, DockerError

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("", response_model=list[schemas.TemplateOut])
def list_templates(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
):
    q = db.query(models.Template)
    if not user.is_admin:
        q = q.filter(models.Template.is_public.is_(True))
    return q.order_by(models.Template.id.desc()).all()


@router.post("", response_model=schemas.TemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(
    payload: schemas.TemplateIn,
    _admin: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db_dep),
):
    exists = db.query(models.Template).filter(models.Template.name == payload.name).first()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "模板名已存在")
    tpl = models.Template(**payload.model_dump())
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.put("/{template_id}", response_model=schemas.TemplateOut)
def update_template(
    template_id: int,
    payload: schemas.TemplateIn,
    _admin: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db_dep),
):
    tpl = db.query(models.Template).filter(models.Template.id == template_id).first()
    if not tpl:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板不存在")
    for k, v in payload.model_dump().items():
        setattr(tpl, k, v)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.delete("/{template_id}", response_model=schemas.MessageOut)
def delete_template(
    template_id: int,
    _admin: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db_dep),
):
    tpl = db.query(models.Template).filter(models.Template.id == template_id).first()
    if not tpl:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板不存在")
    db.delete(tpl)
    db.commit()
    return schemas.MessageOut(message="模板已删除")


@router.get("/images", response_model=list)
def list_docker_images(_admin: models.User = Depends(get_admin_user)):
    """列出本地镜像，便于创建模板时选择。"""
    try:
        return docker_service.list_local_images()
    except DockerError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))
