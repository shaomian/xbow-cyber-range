"""Pydantic 请求/响应模型。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Annotated, Dict, List, Optional

from pydantic import BaseModel, Field, PlainSerializer


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """DB 中 datetime 为 naive UTC（无 tzinfo）；序列化时补上 UTC 时区，
    使输出带 +00:00 后缀，前端 new Date() 才能正确解析为 UTC 再转本地时区显示。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


UtcDatetime = Annotated[datetime, PlainSerializer(_as_utc, return_type=datetime)]


# ---- Auth ----
class LoginIn(BaseModel):
    username: str
    password: str


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    is_admin: bool
    username: str


class UserOut(BaseModel):
    id: int
    username: str
    is_admin: bool
    is_active: bool
    created_at: UtcDatetime

    class Config:
        from_attributes = True


class UserUpdateIn(BaseModel):
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


# ---- Template ----
class TemplateIn(BaseModel):
    name: str
    image: str
    description: str = ""
    command: str = ""
    entrypoint: str = ""
    env: List[str] = Field(default_factory=list)
    exposed_ports: List[int] = Field(default_factory=list)
    privileged: bool = False
    memory_limit_mb: int = 0
    cpu_quota: int = 0
    tags: str = ""
    is_public: bool = True


class TemplateOut(TemplateIn):
    id: int
    created_at: UtcDatetime

    class Config:
        from_attributes = True


# ---- Instance ----
class InstanceStartIn(BaseModel):
    template_id: Optional[int] = None
    name: Optional[str] = None
    image: Optional[str] = None  # 若无模板可直接给镜像
    command: str = ""
    env: List[str] = Field(default_factory=list)
    exposed_ports: List[int] = Field(default_factory=list)
    privileged: bool = False
    timeout_seconds: Optional[int] = None  # 不传走默认
    auto_remove: bool = False


class InstanceExtendIn(BaseModel):
    add_seconds: int = Field(..., gt=0, description="续期秒数")


class InstanceUpdateTimeoutIn(BaseModel):
    timeout_seconds: int = Field(..., gt=0)


class PortMapping(BaseModel):
    container_port: int
    host_port: int


class InstanceOut(BaseModel):
    id: int
    container_id: str
    name: str
    user_id: int
    template_id: Optional[int]
    image: str
    status: str
    ports: Dict[str, int]
    host: str
    expires_at: Optional[UtcDatetime]
    started_at: Optional[UtcDatetime]
    stopped_at: Optional[UtcDatetime]
    last_error: str
    auto_remove: bool
    remaining_seconds: Optional[int] = None  # 剩余倒计时，运行时计算
    renewed: Optional[bool] = None  # 启动已停实例时是否触发了自动续期（仅 start_existing 返回时可能为 True）
    kind: str = "container"
    project_name: Optional[str] = None
    benchmark_id: Optional[str] = None
    flag: Optional[str] = None

    class Config:
        from_attributes = True


# ---- Snapshot ----
class SnapshotCreateIn(BaseModel):
    image_tag: str
    note: str = ""


class SnapshotOut(BaseModel):
    id: int
    instance_id: int
    image_id: str
    image_tag: str
    note: str
    created_at: UtcDatetime

    class Config:
        from_attributes = True


# ---- Stats ----
class ContainerStatsOut(BaseModel):
    instance_id: int
    container_id: str
    name: str
    cpu_percent: float
    memory_used_mb: float
    memory_limit_mb: float
    net_rx_kb: float
    net_tx_kb: float
    status: str


class SystemStatsOut(BaseModel):
    cpu_percent: float
    memory_percent: float
    memory_total_gb: float
    disk_percent: float
    containers_total: int
    containers_running: int


# ---- Settings ----
class PlatformSettingsOut(BaseModel):
    port_range_start: int
    port_range_end: int
    default_instance_timeout: int
    max_instance_timeout: int
    docker_host: str
    terminal_default_command: str
    reaper_interval_seconds: int
    benchmarks_root: str


class PlatformSettingsUpdateIn(BaseModel):
    port_range_start: Optional[int] = None
    port_range_end: Optional[int] = None
    default_instance_timeout: Optional[int] = None
    max_instance_timeout: Optional[int] = None
    terminal_default_command: Optional[str] = None
    benchmarks_root: Optional[str] = None


# ---- 通用 ----
class MessageOut(BaseModel):
    message: str
    detail: Any = None


# ---- Benchmark ----
class BenchmarkServiceOut(BaseModel):
    name: str
    ports: List[Dict[str, Any]]
    has_build: bool


class BenchmarkOut(BaseModel):
    id: str
    name: str
    description: str
    win_condition: str
    dir: str
    has_compose: bool
    has_makefile: bool
    services: List[Any]
    host_ports: List[int]
    env_flag: Optional[str] = None
    computed_flag: str
    running: bool = False
    instance_id: Optional[int] = None


class BenchmarkLaunchIn(BaseModel):
    timeout_seconds: Optional[int] = None
