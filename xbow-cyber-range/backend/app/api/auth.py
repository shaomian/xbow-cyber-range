"""认证与用户管理路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..deps import get_db_dep, get_current_user, get_admin_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _ensure_first_admin(db: Session) -> bool:
    """返回是否尚无管理员（用于开放注册时第一个用户自动为管理员）。"""
    return db.query(func.count(models.User.id)).filter(models.User.is_admin.is_(True)).scalar() == 0


@router.post("/login", response_model=schemas.TokenOut)
def login(payload: schemas.LoginIn, db: Session = Depends(get_db_dep)):
    user = db.query(models.User).filter(models.User.username == payload.username).first()
    if not user or not auth.verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已禁用")
    token = auth.create_access_token(user.username, user.is_admin)
    return schemas.TokenOut(access_token=token, is_admin=user.is_admin, username=user.username)


@router.post("/register", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: schemas.RegisterIn, db: Session = Depends(get_db_dep)):
    exists = db.query(models.User).filter(models.User.username == payload.username).first()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在")
    first_admin = _ensure_first_admin(db)
    user = models.User(
        username=payload.username,
        hashed_password=auth.hash_password(payload.password),
        is_admin=first_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(get_current_user)):
    return user


@router.post("/change-password", response_model=schemas.MessageOut)
def change_password(
    old_password: str,
    new_password: str,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
):
    if not auth.verify_password(old_password, user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "旧密码错误")
    if len(new_password) < 6:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "新密码至少 6 位")
    user.hashed_password = auth.hash_password(new_password)
    db.commit()
    return schemas.MessageOut(message="密码已更新")


# ---- 管理员管理用户 ----
admin_router = APIRouter(prefix="/api/users", tags=["admin-users"])


@admin_router.get("", response_model=list[schemas.UserOut])
def list_users(
    _admin: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db_dep),
):
    return db.query(models.User).order_by(models.User.id).all()


@admin_router.patch("/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: int,
    payload: schemas.UserUpdateIn,
    admin: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db_dep),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if payload.is_admin is not None:
        if not payload.is_admin and user.id == admin.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能取消自己的管理员权限")
        user.is_admin = payload.is_admin
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password:
        user.hashed_password = auth.hash_password(payload.password)
    db.commit()
    db.refresh(user)
    return user


@admin_router.delete("/{user_id}", response_model=schemas.MessageOut)
def delete_user(
    user_id: int,
    admin: models.User = Depends(get_admin_user),
    db: Session = Depends(get_db_dep),
):
    if user_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能删除自己")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    db.delete(user)
    db.commit()
    return schemas.MessageOut(message="用户已删除")
