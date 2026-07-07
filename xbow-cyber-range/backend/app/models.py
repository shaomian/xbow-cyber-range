"""ORM 模型定义。

所有 SQLAlchemy 模型集中在此模块，避免与 database.py 形成循环导入。
database.py 仅负责 engine/session 与运行时配置读写。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)

    instances = relationship("Instance", back_populates="user", cascade="all, delete-orphan")


class Template(Base):
    """靶机模板：固化镜像、命令、端口、环境变量、标签等。"""
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), unique=True, index=True, nullable=False)
    image = Column(String(256), nullable=False)  # e.g. kali:latest
    description = Column(Text, default="")
    command = Column(String(512), default="")  # 启动命令，空则用镜像默认
    entrypoint = Column(String(512), default="")
    env = Column(JSON, default=list)  # ["KEY=val", ...]
    exposed_ports = Column(JSON, default=list)  # 容器内端口 [22, 8080]
    privileged = Column(Boolean, default=False)
    memory_limit_mb = Column(Integer, default=0)  # 0 = 不限
    cpu_quota = Column(Integer, default=0)  # 0 = 不限
    tags = Column(String(256), default="")
    is_public = Column(Boolean, default=True)  # 是否所有用户可见
    created_at = Column(DateTime, default=_now, nullable=False)

    instances = relationship("Instance", back_populates="template")


class Instance(Base):
    """一次容器实例：记录启动者、宿主端口映射、过期时间等。

    kind:
      - "container": 单镜像 docker run（原有能力）
      - "compose":   docker-compose 多服务栈（XBEN benchmarks 等）
    """
    __tablename__ = "instances"

    id = Column(Integer, primary_key=True, index=True)
    container_id = Column(String(128), index=True)  # docker 容器 id（compose 时存主容器或留空）
    name = Column(String(128), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    template_id = Column(Integer, ForeignKey("templates.id", ondelete="SET NULL"), nullable=True)
    image = Column(String(256), nullable=False)  # compose 时存 benchmark_id
    status = Column(String(32), default="creating", nullable=False)  # creating/running/stopped/exited/removed
    ports = Column(JSON, default=dict)  # {"22": 21012} 或 compose 合并 {"80": 21012}
    host = Column(String(128), default="127.0.0.1")
    expires_at = Column(DateTime, nullable=True)  # 到点自动停止；NULL=不过期
    started_at = Column(DateTime, default=_now)
    stopped_at = Column(DateTime, nullable=True)
    last_error = Column(Text, default="")
    auto_remove = Column(Boolean, default=False)

    # ---- compose 扩展字段 ----
    kind = Column(String(16), default="container", nullable=False)  # container / compose
    project_name = Column(String(128), nullable=True)  # compose project name
    benchmark_id = Column(String(64), nullable=True)  # XBEN-xxx-24
    work_dir = Column(String(256), nullable=True)  # compose override 工作目录
    flag = Column(String(128), nullable=True)  # 启动时使用的 flag（便于用户核对）

    user = relationship("User", back_populates="instances")
    template = relationship("Template", back_populates="instances")
    snapshots = relationship("Snapshot", back_populates="instance", cascade="all, delete-orphan")


class Snapshot(Base):
    """实例历史/快照：可由 commit 生成镜像，或仅记录状态。"""
    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True, index=True)
    instance_id = Column(Integer, ForeignKey("instances.id", ondelete="CASCADE"), nullable=False)
    image_id = Column(String(128), default="")  # commit 产出的镜像 id
    image_tag = Column(String(256), default="")
    note = Column(String(256), default="")
    created_at = Column(DateTime, default=_now, nullable=False)

    instance = relationship("Instance", back_populates="snapshots")


class Setting(Base):
    """平台运行时键值配置，覆盖 config.py 默认。"""
    __tablename__ = "settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, default="")
    updated_at = Column(DateTime, default=_now, onupdate=_now)
