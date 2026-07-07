"""数据库会话与运行时键值配置读写。

ORM 模型定义在 models.py 中，本模块只负责：
- engine / SessionLocal / get_db
- init_db 建表
- get_setting / set_setting 运行时配置读写（覆盖 config.py 默认值）
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import settings
from .models import Base, Setting

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args=connect_args,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    ensure_schema()


# ---- 幂等 schema 迁移：为旧库补全新增列（SQLite ALTER TABLE ADD COLUMN）----
_NEW_INSTANCE_COLUMNS = {
    "kind": "VARCHAR(16) DEFAULT 'container' NOT NULL",
    "project_name": "VARCHAR(128)",
    "benchmark_id": "VARCHAR(64)",
    "work_dir": "VARCHAR(256)",
    "flag": "VARCHAR(128)",
}


def _existing_columns(table: str) -> set:
    from sqlalchemy import inspect
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def ensure_schema() -> None:
    """对已存在的表补齐后续新增的列（仅支持可空或有默认的列）。"""
    from sqlalchemy import text

    have = _existing_columns("instances")
    with engine.begin() as conn:
        for col, typedef in _NEW_INSTANCE_COLUMNS.items():
            if col not in have:
                try:
                    conn.execute(text(f'ALTER TABLE instances ADD COLUMN "{col}" {typedef}'))
                except Exception:  # noqa: BLE001
                    pass


# ---- 运行时配置读写（DB 优先，回退默认）----
_NUMERIC_KEYS = {
    "port_range_start": int,
    "port_range_end": int,
    "default_instance_timeout": int,
    "max_instance_timeout": int,
}


def get_setting(db, key: str, default):
    row = db.query(Setting).filter(Setting.key == key).first()
    if row is None or row.value == "":
        return default
    caster = _NUMERIC_KEYS.get(key)
    if caster:
        try:
            return caster(row.value)
        except (TypeError, ValueError):
            return default
    return row.value


def set_setting(db, key: str, value) -> None:
    row = db.query(Setting).filter(Setting.key == key).first()
    text = "" if value is None else str(value)
    if row is None:
        row = Setting(key=key, value=text)
        db.add(row)
    else:
        row.value = text
    db.commit()
