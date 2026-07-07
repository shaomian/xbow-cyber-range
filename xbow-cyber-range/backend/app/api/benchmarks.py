"""XBEN benchmarks 路由：列表/详情/启动。停止/续期/删除复用 /api/instances。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..deps import get_db_dep, get_current_user, get_runtime_settings
from ..services import benchmark_service, instance_service

router = APIRouter(prefix="/api/benchmarks", tags=["benchmarks"])


def _running_map(db: Session, user: models.User) -> dict:
    """返回 benchmark_id -> instance 映射（仅活跃 compose 实例）。"""
    q = db.query(models.Instance).filter(models.Instance.kind == "compose")
    if not user.is_admin:
        q = q.filter(models.Instance.user_id == user.id)
    out = {}
    for inst in q.all():
        if inst.benchmark_id and inst.status in ("running", "creating", "partial", "stopped"):
            # 同一 benchmark 取最新一条
            if inst.benchmark_id not in out or (inst.id > out[inst.benchmark_id].id):
                out[inst.benchmark_id] = inst
    return out


@router.get("", response_model=list[schemas.BenchmarkOut])
def list_benchmarks(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
    rs=Depends(get_runtime_settings),
):
    root = rs.benchmarks_root
    if not root:
        return []
    benchs = benchmark_service.list_benchmarks(root)
    running = _running_map(db, user)
    out = []
    for b in benchs:
        r = running.get(b.id)
        out.append(b.to_dict(running=bool(r) and r.status in ("running", "creating", "partial"), instance_id=r.id if r else None))
    return out


@router.get("/{bench_id}", response_model=schemas.BenchmarkOut)
def get_benchmark(
    bench_id: str,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
    rs=Depends(get_runtime_settings),
):
    info = benchmark_service.get_benchmark(bench_id, rs.benchmarks_root)
    if not info:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "benchmark 不存在")
    running = _running_map(db, user)
    r = running.get(bench_id)
    return info.to_dict(running=bool(r) and r.status in ("running", "creating", "partial"), instance_id=r.id if r else None)


@router.post("/{bench_id}/launch", response_model=schemas.InstanceOut, status_code=status.HTTP_201_CREATED)
def launch_benchmark(
    bench_id: str,
    payload: schemas.BenchmarkLaunchIn,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db_dep),
    rs=Depends(get_runtime_settings),
):
    inst, err = benchmark_service.launch_benchmark(
        db, user, bench_id, rs, timeout_seconds=payload.timeout_seconds
    )
    if inst is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, err)
    out = schemas.InstanceOut.model_validate(inst)
    out.remaining_seconds = instance_service.remaining_seconds(inst.expires_at)
    return out
