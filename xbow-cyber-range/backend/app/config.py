"""应用配置：从环境变量读取，含端口范围、超时等可调项。"""
from __future__ import annotations

import platform
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_docker_host() -> str:
    """按平台返回 Docker 默认连接地址。"""
    if platform.system() == "Windows":
        return "npipe:////./pipe/docker_engine"
    return "unix:///var/run/docker.sock"


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="XBOW_CYBER_RANGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 基础 ----
    app_name: str = "XBow CyberRange 靶场平台"
    secret_key: str = "change-me-in-production-please-use-a-long-random-string"
    access_token_expire_minutes: int = 60 * 24  # 登录 token 1 天
    algorithm: str = "HS256"

    # ---- 数据库（默认 SQLite，零配置开箱即用；可改 MySQL）----
    database_url: str = "sqlite:///./xbow_cyber_range.db"

    # ---- Docker ----
    docker_host: str = ""  # 留空则按平台自动选择；可被环境变量覆盖
    docker_network: str = ""  # 启动容器附加的网络，空则默认
    container_label_key: str = "xbow_cyber_range.managed"
    container_label_value: str = "true"

    # ---- 端口随机范围（管理员可在线修改）----
    port_range_start: int = 20000
    port_range_end: int = 30000

    # ---- 容器超时（秒）：到点自动停止；管理员可在线修改默认值 ----
    default_instance_timeout: int = 60 * 60  # 1 小时
    max_instance_timeout: int = 60 * 60 * 8  # 单次续期最长 8 小时
    # 后台扫描间隔
    reaper_interval_seconds: int = 15

    # ---- 终端 ----
    terminal_default_command: str = "/bin/sh"
    terminal_cols: int = 120
    terminal_rows: int = 32

    # ---- 靶场目录（XBEN benchmarks 根目录，留空则自动探测）----
    benchmarks_root: str = ""

    # ---- compose 工作目录（存放端口 override 文件）----
    compose_work_dir: str = ""

    # ---- CORS ----
    cors_origins: List[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    @field_validator("docker_host", mode="after")
    @classmethod
    def _resolve_docker_host(cls, v: str) -> str:
        if not v:
            return _default_docker_host()
        return v

    @field_validator("benchmarks_root", mode="after")
    @classmethod
    def _resolve_benchmarks_root(cls, v: str) -> str:
        if v:
            return v
        # 自动探测：backend 上两级目录下的 xbow-validation-benchmarks-main/benchmarks
        candidates = [
            BASE_DIR.parent / "xbow-validation-benchmarks-main" / "benchmarks",
            BASE_DIR.parent.parent / "xbow-validation-benchmarks-main" / "benchmarks",
        ]
        for c in candidates:
            if c.is_dir():
                return str(c)
        return ""

    @field_validator("compose_work_dir", mode="after")
    @classmethod
    def _resolve_compose_work_dir(cls, v: str) -> str:
        if v:
            return v
        return str(BASE_DIR / ".compose-work")


settings = Settings()
