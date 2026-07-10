"""实例业务逻辑：启动、超时、续期、倒计时、停止、删除、同步状态。"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from .. import models, schemas
from ..config import settings
from ..deps import RuntimeSettings
from .docker_service import DockerError, docker_service


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def remaining_seconds(expires_at: Optional[datetime]) -> Optional[int]:
    if expires_at is None:
        return None
    exp = expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    delta = (exp - _now()).total_seconds()
    return max(0, int(delta))


def _gen_name(prefix: str = "range") -> str:
    return f"{prefix}-{secrets.token_hex(4)}"


def list_instances(db: Session, user: models.User, only_active: bool = False, include_removed: bool = False) -> List[models.Instance]:
    q = db.query(models.Instance)
    if not user.is_admin:
        q = q.filter(models.Instance.user_id == user.id)
    if only_active:
        q = q.filter(models.Instance.status.in_(["creating", "running"]))
    elif not include_removed:
        # 默认隐藏已删除实例，避免删除后的历史记录堆积让列表越来越乱。
        # only_active 已是更严格过滤，此处用 elif 互斥即可。
        q = q.filter(models.Instance.status != "removed")
    return q.order_by(models.Instance.started_at.desc()).all()


def get_instance(db: Session, instance_id: int, user: models.User) -> Optional[models.Instance]:
    inst = db.query(models.Instance).filter(models.Instance.id == instance_id).first()
    if not inst:
        return None
    if not user.is_admin and inst.user_id != user.id:
        return None
    return inst


def _set_stopped_now(inst: models.Instance) -> None:
    inst.status = "stopped"
    inst.stopped_at = _to_naive_utc(_now())


def _apply_runtime_status(inst: models.Instance) -> None:
    """用 docker 实际状态同步 DB 字段（不提交）。"""
    if inst.kind == "compose":
        from . import benchmark_service
        # 构建中（creating）不覆盖：build 期间无运行容器，compose_status 会误判为 removed
        if inst.status == "creating":
            return
        if inst.project_name:
            real = benchmark_service.compose_status(inst.project_name)
            # 顺带回填主 container_id（构建线程可能因时序未拿到，这里补齐）
            if real in ("running", "partial") and not inst.container_id:
                try:
                    cs = benchmark_service._compose_containers(inst.project_name)
                    if cs:
                        inst.container_id = cs[0]["id"]
                except Exception:  # noqa: BLE001
                    pass
            if real == "running":
                inst.status = "running"
            elif real == "partial":
                inst.status = "partial"
            elif real in ("stopped", "exited"):
                if inst.status not in ("stopped", "removed"):
                    inst.status = "stopped"
                    if not inst.stopped_at:
                        inst.stopped_at = _to_naive_utc(_now())
            elif real == "removed":
                inst.status = "removed"
        return
    if not inst.container_id:
        return
    real = docker_service.container_status(inst.container_id)
    if real in {"running"}:
        inst.status = "running"
    elif real in {"created", "paused", "restarting"}:
        inst.status = real
    elif real in {"exited", "dead"}:
        if inst.status not in {"stopped", "removed"}:
            inst.status = "exited"
            if not inst.stopped_at:
                inst.stopped_at = _to_naive_utc(_now())
    elif real == "removed":
        inst.status = "removed"


def start_instance(
    db: Session,
    user: models.User,
    payload: schemas.InstanceStartIn,
    rs: RuntimeSettings,
) -> Tuple[models.Instance, str]:
    """启动一个容器实例，返回 (instance, error_message)。error_message 为空表示成功。"""
    # 解析模板/镜像
    template: Optional[models.Template] = None
    if payload.template_id:
        template = db.query(models.Template).filter(models.Template.id == payload.template_id).first()
        if not template:
            return None, "模板不存在"
        if not template.is_public and not user.is_admin and template.id != payload.template_id:
            # 这里仅做存在性校验，模板可见性由前端控制
            pass
    elif payload.image:
        pass
    else:
        return None, "必须指定 template_id 或 image"

    image = (template.image if template else payload.image) or ""
    command = (template.command if template and template.command else payload.command) or ""
    entrypoint = (template.entrypoint if template else "") or ""
    env = list((template.env if template else []) or []) + list(payload.env or [])
    exposed = list((template.exposed_ports if template else []) or []) + list(payload.exposed_ports or [])
    privileged = (template.privileged if template else False) or payload.privileged
    memory_mb = (template.memory_limit_mb if template else 0) or 0
    cpu_quota = (template.cpu_quota if template else 0) or 0

    # 超时
    max_to = rs.max_instance_timeout
    timeout_seconds = payload.timeout_seconds if payload.timeout_seconds and payload.timeout_seconds > 0 else rs.default_instance_timeout
    if timeout_seconds > max_to:
        timeout_seconds = max_to
    expires_at = _now() + timedelta(seconds=timeout_seconds)

    # 端口随机分配
    try:
        port_map = docker_service.allocate_ports(
            container_ports=exposed,
            port_start=rs.port_range_start,
            port_end=rs.port_range_end,
        )
    except DockerError as e:
        return None, f"端口分配失败: {e}"

    name = payload.name or _gen_name()

    # 预先写入 DB
    inst = models.Instance(
        container_id="",
        name=name,
        user_id=user.id,
        template_id=template.id if template else None,
        image=image,
        status="creating",
        ports={str(k): v for k, v in port_map.items()},
        host=(settings.public_host or "127.0.0.1"),
        expires_at=_to_naive_utc(expires_at),
        started_at=_to_naive_utc(_now()),
        auto_remove=payload.auto_remove,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)

    # 容器标签带上 instance_id 方便反查
    labels = {"instance_id": str(inst.id), "owner": user.username}
    try:
        container_id, status = docker_service.create_and_start(
            name=f"xbow-cyber-range-{inst.id}-{name}",
            image=image,
            command=command,
            entrypoint=entrypoint,
            env=env,
            exposed_ports=exposed,
            port_bindings=port_map,
            privileged=privileged,
            memory_limit_mb=memory_mb,
            cpu_quota=cpu_quota,
            network=settings.docker_network or "",
            labels=labels,
            auto_remove=payload.auto_remove,
        )
    except DockerError as e:
        inst.status = "exited"
        inst.last_error = str(e)
        inst.stopped_at = _to_naive_utc(_now())
        db.commit()
        return inst, str(e)

    inst.container_id = container_id
    inst.status = status or "running"
    db.commit()
    db.refresh(inst)
    return inst, ""


def stop_instance(db: Session, inst: models.Instance, timeout: int = 10) -> None:
    if inst.kind == "compose":
        from . import benchmark_service
        if inst.project_name:
            benchmark_service.compose_stop(inst.project_name, inst.work_dir or "", _benchmark_dir(inst))
            # 兜底：compose stop 可能因 work_dir 文件缺失或 compose rc=0 但未实际停容器而没生效。
            # 操作后核对 docker，若仍有 running 容器则直接强停所有该 project 的容器。
            try:
                leftover = benchmark_service._compose_containers(inst.project_name)
                if any(c.get("status") == "running" for c in leftover):
                    benchmark_service._force_stop_project(inst.project_name)
            except Exception:  # noqa: BLE001
                pass
        _set_stopped_now(inst)
        db.commit()
        return
    if inst.container_id:
        try:
            docker_service.stop(inst.container_id, timeout=timeout)
        except DockerError:
            pass
    _set_stopped_now(inst)
    db.commit()


def _benchmark_dir(inst: models.Instance) -> str:
    """从 benchmarks_root + benchmark_id 推导 benchmark 目录。"""
    from ..config import settings
    if inst.benchmark_id:
        return os.path.join(settings.benchmarks_root, inst.benchmark_id) if settings.benchmarks_root else ""
    return ""


def start_existing(db: Session, inst: models.Instance) -> None:
    if inst.kind == "compose":
        from . import benchmark_service
        if not inst.project_name:
            raise DockerError("compose project 缺失")
        bdir = _benchmark_dir(inst)
        from .benchmark_service import _compose_files_args, compose_cmd, _run_cmd
        args = compose_cmd() + ["-p", inst.project_name] + _compose_files_args(inst.work_dir or "", bdir) + ["up", "-d", "--wait"]
        rc, out = _run_cmd(args, cwd=bdir, timeout=600)
        if rc != 0:
            raise DockerError(f"compose up 失败:\n{out[-1500:]}")
        inst.status = "running"
        if not inst.expires_at:
            inst.expires_at = _to_naive_utc(_now() + timedelta(seconds=settings.default_instance_timeout))
        db.commit()
        return
    if not inst.container_id:
        raise DockerError("容器尚未创建")
    docker_service.start(inst.container_id)
    inst.status = "running"
    if not inst.expires_at:
        inst.expires_at = _to_naive_utc(_now() + timedelta(seconds=settings.default_instance_timeout))
    db.commit()


def remove_instance(db: Session, inst: models.Instance, force: bool = True) -> None:
    if inst.kind == "compose":
        from . import benchmark_service
        if inst.project_name:
            benchmark_service.compose_down(inst.project_name, inst.work_dir or "", _benchmark_dir(inst))
            # 兜底：compose down 可能因文件缺失/异常 rc=0 但容器未删，操作后强删所有该 project 容器与网络。
            try:
                leftover = benchmark_service._compose_containers(inst.project_name)
                if leftover:
                    benchmark_service._force_remove_project(inst.project_name)
            except Exception:  # noqa: BLE001
                pass
        inst.status = "removed"
        inst.stopped_at = inst.stopped_at or _to_naive_utc(_now())
        db.commit()
        return
    if inst.container_id:
        try:
            docker_service.remove(inst.container_id, force=force)
        except DockerError:
            pass
    inst.status = "removed"
    inst.stopped_at = inst.stopped_at or _to_naive_utc(_now())
    db.commit()


def purge_instance(db: Session, inst: models.Instance) -> None:
    """永久删除实例记录（仅允许对已 removed 的实例调用）。

    与 remove_instance 的区别：
    - remove_instance：停止并移除 docker 容器/网络/镜像，DB 记录保留并置 status=removed（可追溯）。
    - purge_instance：DB 记录彻底删除，同时清理 compose work_dir 残留文件。
      容器/镜像此时应该已被 remove_instance 清理过，这里不重复操作 docker。
    """
    if inst.status != "removed":
        raise DockerError("只能永久删除状态为 removed 的实例；请先删除（remove）")
    # 清理 compose 工作目录残留文件（override.yml / compose.yml）
    work_dir = getattr(inst, "work_dir", None) or ""
    if work_dir:
        from pathlib import Path
        import shutil
        try:
            p = Path(work_dir)
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass
    db.delete(inst)
    db.commit()


def extend_instance(db: Session, inst: models.Instance, add_seconds: int, rs: RuntimeSettings) -> datetime:
    base = inst.expires_at
    if base is None:
        base = _now()
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    now = _now()
    new_exp = max(now, base) + timedelta(seconds=add_seconds)
    # 单次不超过 max_instance_timeout 续期（相对现在）
    if (new_exp - now).total_seconds() > rs.max_instance_timeout:
        new_exp = now + timedelta(seconds=rs.max_instance_timeout)
    inst.expires_at = _to_naive_utc(new_exp)
    db.commit()
    return new_exp


def set_instance_timeout(db: Session, inst: models.Instance, timeout_seconds: int, rs: RuntimeSettings) -> datetime:
    if timeout_seconds > rs.max_instance_timeout:
        timeout_seconds = rs.max_instance_timeout
    new_exp = _now() + timedelta(seconds=timeout_seconds)
    inst.expires_at = _to_naive_utc(new_exp)
    db.commit()
    return new_exp


def reap_expired(db: Session) -> List[int]:
    """扫描所有过期且仍在运行的实例，停止之。返回被停止的 instance id 列表。"""
    now = _now()
    # 同时收集 status in (running, creating, exited)
    candidates = (
        db.query(models.Instance)
        .filter(models.Instance.expires_at.isnot(None))
        .filter(models.Instance.status.in_(["running", "creating", "paused", "partial"]))
        .all()
    )
    stopped: List[int] = []
    for inst in candidates:
        exp = inst.expires_at
        if exp is None:
            continue
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= now:
            try:
                stop_instance(db, inst)
                stopped.append(inst.id)
            except Exception:  # noqa: BLE001
                pass
    return stopped


def sync_all_status(db: Session) -> None:
    """批量同步实例状态（用于列表刷新）。

    仅同步仍处于"活跃"类状态的实例；已停止/已删除的不再去查询。
    包含 partial（compose 部分服务停了）——重启后这类也应被回收修正。
    """
    insts = db.query(models.Instance).filter(
        models.Instance.status.in_(["creating", "running", "paused", "restarting", "partial"])
    ).all()
    for inst in insts:
        try:
            _apply_runtime_status(inst)
        except Exception:  # noqa: BLE001
            pass
    db.commit()


def commit_snapshot(db: Session, inst: models.Instance, image_tag: str, note: str) -> models.Snapshot:
    if not inst.container_id:
        raise DockerError("容器尚未创建")
    repo, _, tag = image_tag.partition(":")
    if not repo or not tag:
        # 自动补 tag
        repo = repo or f"xbow-cyber-range/snap-{inst.id}"
        tag = tag or datetime.now().strftime("%Y%m%d-%H%M%S")
    image_id, full_tag = docker_service.commit(inst.container_id, repo, tag, note)
    snap = models.Snapshot(
        instance_id=inst.id,
        image_id=image_id,
        image_tag=full_tag,
        note=note,
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap
