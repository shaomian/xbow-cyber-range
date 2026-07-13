"""XBEN benchmarks 管理服务。

每个 benchmark 是一个 docker-compose 多服务栈，从源码 build（带 FLAG build-arg）。
本服务负责：
- 扫描 benchmarks 根目录，解析 benchmark.json + docker-compose.yml
- 复刻 `make run` 行为：FLAG{sha256(name)} build-arg + docker compose build + up -d
- 把 compose 中固定宿主端口重映射到平台随机端口范围（避免多实例冲突）
- stop / down / 状态查询 / 日志
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..deps import RuntimeSettings
from .docker_service import DockerError, docker_service


# ---------- 通用 ----------

_PROXY_ENV_KEYS = [
    "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
    "all_proxy", "ALL_PROXY", "ftp_proxy", "FTP_PROXY",
]


def _clean_env() -> dict:
    """剥离代理环境变量。

    宿主机常配 127.0.0.1:xxxx 本地代理，但 Docker build 容器内的 127.0.0.1
    指向容器自身，无法访问宿主代理，导致 apt/git 等下载失败。
    若需代理，应在 Docker Desktop 的代理设置中配置（会自动转 host.docker.internal）。
    """
    env = dict(os.environ)
    for k in _PROXY_ENV_KEYS:
        env.pop(k, None)
    # no_proxy 同步清理（避免残留逗号分隔的 localhost 条目）
    for k in ("no_proxy", "NO_PROXY"):
        env.pop(k, None)
    return env


def _run_cmd(args: List[str], cwd: str, timeout: int = 600, capture: bool = True) -> Tuple[int, str]:
    """运行命令，返回 (returncode, output)。剥离代理 env 以适配 Docker build。"""
    try:
        p = subprocess.run(
            args,
            cwd=cwd,
            capture_output=capture,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            env=_clean_env(),
        )
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out
    except subprocess.TimeoutExpired as e:
        return 124, f"命令超时（{timeout}s）：{' '.join(args)}\n{e.stdout or ''}{e.stderr or ''}"
    except FileNotFoundError as e:
        return 127, f"命令未找到：{e}"
    except Exception as e:  # noqa: BLE001
        return 1, f"命令执行异常：{e}"


def compose_cmd() -> List[str]:
    """返回 docker compose 命令前缀。"""
    return ["docker", "compose"]


def compute_flag(benchmark_id: str) -> str:
    """复刻 common.mk: FLAG{sha256(upper(name))}。"""
    h = hashlib.sha256(benchmark_id.upper().encode("utf-8")).hexdigest()
    return f"FLAG{{{h}}}"


# ---------- 扫描与解析 ----------

class ServiceInfo:
    def __init__(self, name: str, ports: List[Dict], has_build: bool):
        self.name = name
        self.ports = ports  # [{"host": int|None, "container": int, "proto": str}]
        self.has_build = has_build

    def to_dict(self) -> dict:
        return {"name": self.name, "ports": self.ports, "has_build": self.has_build}


class BenchmarkInfo:
    def __init__(self, bench_id: str, dir_path: str):
        self.id = bench_id
        self.dir = dir_path
        self.name = bench_id
        self.description = ""
        self.win_condition = "flag"
        self.has_compose = False
        self.has_makefile = False
        self.services: List[dict] = []
        self.host_ports: List[int] = []
        self.env_flag: Optional[str] = None  # .env 里的 flag（如有）

    def to_dict(self, running: bool = False, instance_id: Optional[int] = None) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "win_condition": self.win_condition,
            "dir": self.dir,
            "has_compose": self.has_compose,
            "has_makefile": self.has_makefile,
            "services": self.services,
            "host_ports": self.host_ports,
            "env_flag": self.env_flag,
            "computed_flag": compute_flag(self.id),
            "running": running,
            "instance_id": instance_id,
        }


def _parse_port_entry(entry) -> Optional[Dict]:
    """解析 compose ports 列表的单个条目，返回 {host, container, proto}。"""
    if isinstance(entry, int):
        return {"host": None, "container": int(entry), "proto": "tcp"}
    if isinstance(entry, str):
        s = entry.strip()
        # 形如 "8080:80" / "8080:80/tcp" / "127.0.0.1:8080:80" / "80"
        proto = "tcp"
        if "/" in s:
            s, proto = s.rsplit("/", 1)
        parts = s.split(":")
        if len(parts) == 1:
            return {"host": None, "container": int(parts[0]), "proto": proto}
        if len(parts) == 2:
            return {"host": int(parts[0]), "container": int(parts[1]), "proto": proto}
        if len(parts) == 3:
            # ip:host:container
            return {"host": int(parts[1]), "container": int(parts[2]), "proto": proto}
    if isinstance(entry, dict):
        # {"target": 80, "published": 8080, "protocol": "tcp"}
        return {
            "host": entry.get("published"),
            "container": int(entry.get("target", 0)),
            "proto": entry.get("protocol", "tcp"),
        }
    return None


def parse_compose(compose_path: str) -> Tuple[List[dict], List[int]]:
    """解析 docker-compose.yml，返回 (services, host_ports)。"""
    try:
        with open(compose_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:  # noqa: BLE001
        raise DockerError(f"解析 compose 失败 {compose_path}: {e}") from e

    services_out: List[dict] = []
    host_ports: List[int] = []
    services = data.get("services", {}) or {}
    for svc_name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        ports_in = svc.get("ports", []) or []
        parsed_ports: List[dict] = []
        for entry in ports_in:
            p = _parse_port_entry(entry)
            if p:
                parsed_ports.append(p)
                if p["host"]:
                    host_ports.append(int(p["host"]))
        services_out.append({
            "name": svc_name,
            "ports": parsed_ports,
            "has_build": bool(svc.get("build")),
        })
    return services_out, sorted(set(host_ports))


def get_benchmark(bench_id: str, root: str) -> Optional[BenchmarkInfo]:
    root_path = Path(root)
    bdir = root_path / bench_id
    compose = bdir / "docker-compose.yml"
    bj = bdir / "benchmark.json"
    if not bdir.is_dir():
        return None
    info = BenchmarkInfo(bench_id, str(bdir))
    if bj.is_file():
        try:
            with open(bj, "r", encoding="utf-8") as f:
                data = json.load(f)
            info.name = data.get("name", bench_id)
            info.description = data.get("description", "")
            info.win_condition = data.get("win_condition", "flag")
        except Exception:  # noqa: BLE001
            pass
    info.has_compose = compose.is_file()
    info.has_makefile = (bdir / "Makefile").is_file()
    if info.has_compose:
        try:
            svcs, hps = parse_compose(str(compose))
            info.services = svcs
            info.host_ports = hps
        except DockerError:
            pass
    envf = bdir / ".env"
    if envf.is_file():
        try:
            for line in envf.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("FLAG"):
                    info.env_flag = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        except Exception:  # noqa: BLE001
            pass
    return info


def list_benchmarks(root: str) -> List[BenchmarkInfo]:
    root_path = Path(root)
    if not root_path.is_dir():
        return []
    out: List[BenchmarkInfo] = []
    for entry in sorted(os.listdir(root)):
        full = root_path / entry
        if full.is_dir() and (full / "benchmark.json").is_file():
            info = get_benchmark(entry, root)
            if info:
                out.append(info)
    return out


# ---------- 端口 override 生成 ----------

def _build_override(services_ports: Dict[str, List[dict]], port_map: Dict[int, int]) -> dict:
    """构造 compose override，仅覆盖每个 service 的 ports（重映射 host 端口）。"""
    override = {"services": {}}
    for svc_name, ports in services_ports.items():
        new_ports = []
        for p in ports:
            cp = p["container"]
            proto = p.get("proto", "tcp")
            host = port_map.get(cp)
            if host is None:
                # 未重映射的（如无 host 端口）保持原样
                new_ports.append(f"{cp}/{proto}" if p["host"] is None else f"{p['host']}:{cp}/{proto}")
            else:
                new_ports.append(f"{host}:{cp}/{proto}")
        if new_ports:
            override["services"][svc_name] = {"ports": new_ports}
    return override


def _abs_context(benchmark_dir: str, ctx: str) -> str:
    """把 build context 相对路径转绝对（基于 benchmark 目录）。"""
    if not ctx:
        return str(Path(benchmark_dir))
    p = Path(ctx)
    if p.is_absolute():
        return str(p)
    return str(Path(benchmark_dir) / ctx)


def normalize_compose(benchmark_dir: str, out_path: str) -> None:
    """规范化 compose：PyYAML 解析（去重复键）+ build context 转绝对路径 + 清空 ports，写到 out_path。

    这能透明修复诸如 XBEN-001-24 中重复 depends_on 之类被严格 YAML 解析器拒绝的问题。

    端口清空的原因：docker compose 对 ports 列表是 append 合并（不是 replace），
    若原始 compose 写了 "8000:80"，override 又写 "20015:80/tcp"，最终会同时绑定
    两个 host 端口——原始端口可能与宿主其它服务冲突（如后端 8000）。
    清空原始 ports 后，override 成为唯一的端口来源，杜绝冲突。
    """
    src = str(Path(benchmark_dir) / "docker-compose.yml")
    with open(src, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    services = data.get("services", {}) or {}
    for svc_name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        b = svc.get("build")
        if isinstance(b, str):
            svc["build"] = _abs_context(benchmark_dir, b)
        elif isinstance(b, dict):
            ctx = b.get("context")
            if ctx:
                b["context"] = _abs_context(benchmark_dir, ctx)
        # 清空原始端口：由 override 文件统一提供重映射后的端口
        if "ports" in svc:
            svc["ports"] = []
        # 移除 healthcheck：其检查的是容器内端口（如 localhost:5003），
        # 与平台重映射的宿主端口无关；且很多基础镜像（如 python:3.8-slim）
        # 缺 curl 导致 healthcheck 永远 unhealthy，误判启动失败。
        svc.pop("healthcheck", None)
        # depends_on 的 service_healthy 条件依赖 healthcheck，移除 healthcheck
        # 后 docker compose 会报 "has no healthcheck configured"。统一降级为
        # service_started（保持启动顺序但不等 healthcheck）。
        dep = svc.get("depends_on")
        if isinstance(dep, dict):
            for dep_name, dep_cfg in dep.items():
                if isinstance(dep_cfg, dict) and dep_cfg.get("condition") == "service_healthy":
                    dep_cfg["condition"] = "service_started"
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def _collect_container_ports(services: List[dict]) -> List[int]:
    """收集所有需要发布到宿主的容器端口。

    历史实现只收集"显式声明了 host 端口"的服务（如 `8080:80`），
    但 XBEN 中大量 benchmark 仅声明容器端口（如 `ports: - 5000`），
    这种写法在 compose 默认会把容器端口随机映射到宿主高位端口；
    但随机端口对多用户多实例不可控，且平台无法回填 instance.ports，
    导致用户在 Web/MCP 看不到端口、不同实例之间也无法保证互不冲突。

    现统一处理：任何声明了 ports 条目的服务（无论有无 host），
    都纳入随机范围分配，并在 override 中显式写 `host:container` 映射。
    """
    cps: List[int] = []
    for svc in services:
        for p in svc.get("ports", []):
            cp = p.get("container")
            if cp:
                cps.append(int(cp))
    # 去重并保持顺序（同一容器端口可能被多服务/多条目重复声明）
    seen = set()
    unique: List[int] = []
    for cp in cps:
        if cp not in seen:
            seen.add(cp)
            unique.append(cp)
    return unique


# ---------- compose 实例状态 ----------

def _compose_containers(project_name: str) -> List[dict]:
    """列出某 compose project 的所有容器（用 docker SDK 按 label 过滤）。"""
    try:
        label_filter = {"label": [f"com.docker.compose.project={project_name}"]}
        cs = docker_service.client.containers.list(all=True, filters=label_filter)
        return [
            {
                "id": (c.id or "")[:12],
                "name": c.name,
                "service": (c.labels or {}).get("com.docker.compose.service", ""),
                "status": c.status,
            }
            for c in cs
        ]
    except Exception:  # noqa: BLE001
        return []


def compose_status(project_name: str) -> str:
    """根据 project 下容器状态汇总：全 running=running；全 exited/exited=stopped；混合=partial。"""
    cs = _compose_containers(project_name)
    if not cs:
        return "removed"
    statuses = [c["status"] for c in cs]
    if all(s == "running" for s in statuses):
        return "running"
    if all(s in ("exited", "dead", "stopped") for s in statuses):
        return "stopped"
    running = sum(1 for s in statuses if s == "running")
    if running > 0:
        return "partial"
    return "stopped"


def compose_logs(project_name: str, tail: int = 500) -> str:
    """合并 project 下所有容器日志。"""
    label_filter = {"label": [f"com.docker.compose.project={project_name}"]}
    parts: List[str] = []
    try:
        cs = docker_service.client.containers.list(all=True, filters=label_filter)
        for c in cs:
            try:
                data = c.logs(tail=tail, timestamps=True)
                svc = (c.labels or {}).get("com.docker.compose.service", c.name)
                if isinstance(data, bytes):
                    data = data.decode("utf-8", errors="replace")
                parts.append(f"===== [{svc} / {c.name}] =====\n{data}")
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(parts)


def _compose_files_args(work_dir: str, benchmark_dir: str) -> List[str]:
    """构造 -p/--project-directory/-f 公共参数（用规范化 compose + override）。"""
    wd = Path(work_dir) if work_dir else None
    normalized = wd / "compose.yml" if wd else None
    override = wd / "override.yml" if wd else None
    args = []
    if normalized and normalized.is_file():
        args += ["--project-directory", benchmark_dir, "-f", str(normalized)]
        if override and override.is_file():
            args += ["-f", str(override)]
    return args


def compose_down(project_name: str, work_dir: str, benchmark_dir: str) -> None:
    """停止并移除 compose 栈。"""
    args = compose_cmd() + ["-p", project_name] + _compose_files_args(work_dir, benchmark_dir) + ["down", "--remove-orphans", "--rmi", "local", "-v"]
    rc, out = _run_cmd(args, cwd=benchmark_dir, timeout=120)
    if rc != 0:
        _force_remove_project(project_name)


def compose_stop(project_name: str, work_dir: str, benchmark_dir: str) -> None:
    """停止 compose 栈（不删除）。"""
    args = compose_cmd() + ["-p", project_name] + _compose_files_args(work_dir, benchmark_dir) + ["stop"]
    rc, _ = _run_cmd(args, cwd=benchmark_dir, timeout=120)
    if rc != 0:
        _force_stop_project(project_name)


def _force_stop_project(project_name: str) -> None:
    try:
        label_filter = {"label": [f"com.docker.compose.project={project_name}"]}
        for c in docker_service.client.containers.list(all=True, filters=label_filter):
            try:
                c.stop(timeout=10)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass


def _force_remove_project(project_name: str) -> None:
    """强删一个 compose project 的所有容器与网络（镜像不在这里删，由 down --rmi 处理）。"""
    try:
        label_filter = {"label": [f"com.docker.compose.project={project_name}"]}
        for c in docker_service.client.containers.list(all=True, filters=label_filter):
            try:
                c.remove(force=True)
            except Exception:  # noqa: BLE001
                pass
        # 同步清理该 project 的网络，否则 Docker 子网池耗尽后无法再启动新 compose 栈
        try:
            for n in docker_service.client.networks.list(filters=label_filter):
                try:
                    n.remove()
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass


# ---------- 启动 ----------

def launch_benchmark(
    db: Session,
    user: models.User,
    bench_id: str,
    rs: RuntimeSettings,
    timeout_seconds: Optional[int] = None,
    project_suffix: Optional[str] = None,
) -> Tuple[Optional[models.Instance], str]:
    """启动一个 benchmark 为 compose 实例（立即返回，构建在后台线程进行）。

    返回 (instance, error_message)。error_message 为空表示已进入构建流程。
    实际 build+up 在后台线程完成，期间 status=creating，完成后置为 running/exited。
    """
    root = rs.benchmarks_root
    if not root or not Path(root).is_dir():
        return None, f"靶场目录未配置或不存在: {root!r}"
    info = get_benchmark(bench_id, root)
    if not info:
        return None, f"benchmark 不存在: {bench_id}"
    if not info.has_compose:
        return None, f"benchmark 无 docker-compose.yml: {bench_id}"

    # 校验 compose 可用
    rc, _ = _run_cmd(["docker", "compose", "version"], cwd=root, timeout=15)
    if rc != 0:
        return None, "docker compose 不可用，请安装 Docker Compose v2"

    # 端口重映射
    container_ports = _collect_container_ports(info.services)
    port_map: Dict[int, int] = {}
    if container_ports:
        try:
            port_map = docker_service.allocate_ports(
                container_ports=container_ports,
                port_start=rs.port_range_start,
                port_end=rs.port_range_end,
            )
        except DockerError as e:
            return None, f"端口分配失败: {e}"

    # 生成 override
    services_ports = {s["name"]: s["ports"] for s in info.services}
    override = _build_override(services_ports, port_map)

    # 工作目录
    suffix = project_suffix or secrets.token_hex(3)
    project_name = f"cr-{bench_id.lower()}-{suffix}"
    work_dir = Path(settings.compose_work_dir) / project_name
    work_dir.mkdir(parents=True, exist_ok=True)
    override_path = work_dir / "override.yml"
    normalized_path = work_dir / "compose.yml"
    try:
        normalize_compose(info.dir, str(normalized_path))
        with open(override_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(override, f, allow_unicode=True)
    except Exception as e:  # noqa: BLE001
        return None, f"写入 compose 文件失败: {e}"

    # 超时
    max_to = rs.max_instance_timeout
    to = timeout_seconds if (timeout_seconds and timeout_seconds > 0) else rs.default_instance_timeout
    if to > max_to:
        to = max_to
    from datetime import datetime, timedelta, timezone
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=to)

    flag = compute_flag(bench_id)
    inst = models.Instance(
        container_id="",
        name=f"{bench_id}-{suffix}",
        user_id=user.id,
        template_id=None,
        image=bench_id,
        status="creating",
        ports={str(cp): hp for cp, hp in port_map.items()},
        host=(settings.public_host or "127.0.0.1"),
        expires_at=_to_naive_utc(expires_at),
        started_at=_to_naive_utc(datetime.now(timezone.utc)),
        kind="compose",
        project_name=project_name,
        benchmark_id=bench_id,
        work_dir=str(work_dir),
        flag=flag,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)

    # 后台线程执行 build + up
    import threading
    t = threading.Thread(
        target=_build_and_up_thread,
        args=(inst.id, info.dir, project_name, str(normalized_path), str(override_path), str(work_dir), flag),
        daemon=True,
    )
    t.start()
    return inst, ""


def _build_and_up_thread(instance_id: int, benchmark_dir: str, project_name: str,
                         normalized_path: str, override_path: str, work_dir: str, flag: str) -> None:
    """后台线程：build + up，更新 DB。使用规范化 compose + override + project-directory。"""
    from ..database import SessionLocal
    from . import instance_service
    db = SessionLocal()
    try:
        inst = db.query(models.Instance).filter(models.Instance.id == instance_id).first()
        if not inst:
            return
        common_args = compose_cmd() + [
            "-p", project_name,
            "--project-directory", benchmark_dir,
            "-f", normalized_path,
            "-f", override_path,
        ]
        # build（复刻 make run: --build-arg FLAG --build-arg flag）
        # 同时清空预定义代理 ARG，避免宿主 127.0.0.1 代理被注入容器导致 apt 失败
        build_args = common_args + [
            "build",
            "--build-arg", f"FLAG={flag}",
            "--build-arg", f"flag={flag}",
            "--build-arg", "http_proxy=",
            "--build-arg", "https_proxy=",
            "--build-arg", "HTTP_PROXY=",
            "--build-arg", "HTTPS_PROXY=",
            "--build-arg", "all_proxy=",
            "--build-arg", "ALL_PROXY=",
            "--build-arg", "no_proxy=*",
            "--build-arg", "NO_PROXY=*",
        ]
        rc, out = _run_cmd(build_args, cwd=benchmark_dir, timeout=1800)
        if rc != 0:
            inst.status = "exited"
            inst.last_error = f"build 失败:\n{out[-2000:]}"
            instance_service._set_stopped_now(inst)
            db.commit()
            # build 失败也要清理已建出的容器与网络，否则每次失败都留一个孤儿网络
            # 累积最终会把 Docker 默认子网池占满，触发 "all predefined address pools
            # have been fully subnetted" 导致后续任何 compose 都无法启动。
            try:
                _force_remove_project(project_name)
            except Exception:  # noqa: BLE001
                pass
            return
        # up: 不用 --wait（会因 healthcheck 失败如镜像缺 curl 而误判启动失败）
        up_args = common_args + ["up", "-d"]
        rc, out = _run_cmd(up_args, cwd=benchmark_dir, timeout=300)
        if rc != 0:
            inst.status = "exited"
            inst.last_error = f"up 失败:\n{out[-2000:]}"
            instance_service._set_stopped_now(inst)
            db.commit()
            # up 失败同样清理残留，避免网络泄漏
            try:
                _force_remove_project(project_name)
            except Exception:  # noqa: BLE001
                pass
            return
        # 等容器实际进入 running 状态（短轮询，不依赖 healthcheck）
        import time as _t
        running = False
        for _ in range(10):
            _t.sleep(1)
            cs = _compose_containers(project_name)
            if cs and any(c.get("status") == "running" for c in cs):
                running = True
                break
        if not running:
            inst.status = "exited"
            inst.last_error = "up 后容器未进入 running 状态"
            instance_service._set_stopped_now(inst)
            db.commit()
            try:
                _force_remove_project(project_name)
            except Exception:  # noqa: BLE001
                pass
            return
        # 回填主容器 id（up 刚完成时容器列表可能短暂为空，重试一次）
        cs = _compose_containers(project_name)
        if not cs:
            import time as _t
            _t.sleep(2)
            cs = _compose_containers(project_name)
        if cs:
            inst.container_id = cs[0]["id"]
        inst.status = "running"
        inst.last_error = ""
        db.commit()
    except Exception as e:  # noqa: BLE001
        try:
            inst = db.query(models.Instance).filter(models.Instance.id == instance_id).first()
            if inst:
                inst.status = "exited"
                inst.last_error = f"后台构建异常: {e}"
                instance_service._set_stopped_now(inst)
                db.commit()
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()


def _to_naive_utc(dt):
    if dt.tzinfo is not None:
        return dt.astimezone(__import__("datetime").timezone.utc).replace(tzinfo=None)
    return dt
