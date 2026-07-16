"""MCP (Model Context Protocol) Server for XBow CyberRange.

将容器生命周期管理能力以 MCP 工具形式暴露给 agent / LLM 工具调用：
列表 / 启动 / 停止 / 重启 / 删除 / 日志查看 / 续期 / 模板 / benchmarks / 资源监控。

复用现有 services（docker_service / instance_service / benchmark_service），
以管理员身份 impersonate 平台用户（见 settings.mcp_admin_username）。

运行方式：
1) 独立 stdio 进程（典型，用于 Claude Desktop / opencode 等 agent）：
       python -m app.mcp_server
2) 挂载到 FastAPI HTTP / SSE 端点（供远程 agent 通过 HTTP 接入）：
       见 app.main 中的自动挂载逻辑；端点路径见 settings.mcp_http_path。
"""
from __future__ import annotations

import logging
from datetime import timezone
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from . import models
from .config import settings
from .database import SessionLocal, init_db
from .deps import RuntimeSettings
from .services import benchmark_service, instance_service
from .services.docker_service import DockerError, docker_service

logger = logging.getLogger("xbow_cyber_range.mcp")

SERVER_NAME = "xbow-cyber-range"
SERVER_INSTRUCTIONS = (
    "XBow CyberRange 靶场平台的容器生命周期管理工具集。"
    "可通过本工具列出/启动/停止/重启/删除容器实例、查看日志、续期、"
    "管理靶机模板与 XBEN benchmarks、查看系统资源。"
    "所有操作以管理员身份执行。"
    "注意：flag 不会通过任何 MCP 工具返回；flag 只能通过对目标实例"
    "进行 Web 安全漏洞利用后在靶机环境中实际获取。"
)


# ---- DB / 用户辅助 ----

def _db():
    """返回一个新的 DB 会话，供各工具自行 with 使用。"""
    return SessionLocal()


def _get_admin_user(db) -> Optional[models.User]:
    """获取 MCP 代理身份：优先 settings.mcp_admin_username，否则首个活跃管理员。"""
    uname = (settings.mcp_admin_username or "").strip()
    if uname:
        u = db.query(models.User).filter(models.User.username == uname).first()
        if u and u.is_active:
            return u
    u = (
        db.query(models.User)
        .filter(models.User.is_admin.is_(True), models.User.is_active.is_(True))
        .order_by(models.User.id)
        .first()
    )
    if u:
        return u
    return db.query(models.User).filter(models.User.is_active.is_(True)).first()


def _runtime_settings(db) -> RuntimeSettings:
    return RuntimeSettings(db)


def _iso(dt) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()

# MCP 工具绝不返回 flag 相关字段——flag 只能由 agent 在靶机内利用漏洞获取。
_FLAG_KEYS = ("flag", "computed_flag", "env_flag")


def _scrub_flag(d):
    """从 benchmark/instance 字典中剥离 flag 相关字段（原地修改并返回）。"""
    if not isinstance(d, dict):
        return d
    for k in _FLAG_KEYS:
        if k in d:
            d[k] = "hidden (obtain by exploiting the target, not via MCP)"
    return d


def _inst_to_dict(inst: models.Instance, refresh_runtime: bool = False, rs: Optional[RuntimeSettings] = None) -> Dict[str, Any]:
    """将 Instance ORM 对象转为可 JSON 序列化的字典（镜像 schemas.InstanceOut）。"""
    if refresh_runtime:
        try:
            instance_service._apply_runtime_status(inst)
        except Exception:  # noqa: BLE001
            pass
    out = {
        "id": inst.id,
        "container_id": (inst.container_id or "")[:12],
        "full_container_id": inst.container_id or "",
        "name": inst.name,
        "user_id": inst.user_id,
        "template_id": inst.template_id,
        "image": inst.image,
        "status": inst.status,
        "ports": inst.ports or {},
        # 对外访问地址优先用平台配置 public_host（容器端口实际监听 0.0.0.0，
        # 远程用户/agent 需用对外可达地址访问，而非 127.0.0.1）。
        "host": (settings.public_host or inst.host or "127.0.0.1"),
        "expires_at": _iso(inst.expires_at),
        "started_at": _iso(inst.started_at),
        "stopped_at": _iso(inst.stopped_at),
        "last_error": inst.last_error or "",
        "auto_remove": inst.auto_remove,
        "kind": inst.kind,
        "project_name": inst.project_name,
        "benchmark_id": inst.benchmark_id,
        "flag": inst.flag,
        "remaining_seconds": instance_service.remaining_seconds(inst.expires_at),
    }
    return _scrub_flag(out)


def _template_to_dict(t: models.Template) -> Dict[str, Any]:
    return {
        "id": t.id,
        "name": t.name,
        "image": t.image,
        "description": t.description or "",
        "command": t.command or "",
        "entrypoint": t.entrypoint or "",
        "env": t.env or [],
        "exposed_ports": t.exposed_ports or [],
        "privileged": bool(t.privileged),
        "memory_limit_mb": t.memory_limit_mb or 0,
        "cpu_quota": t.cpu_quota or 0,
        "tags": t.tags or "",
        "is_public": bool(t.is_public),
        "created_at": _iso(t.created_at),
    }


# ---- 工具实现（同步；FastMCP 会在线程池执行）----

def _list_instances(only_active: bool = False) -> List[Dict[str, Any]]:
    db = _db()
    try:
        user = _get_admin_user(db)
        if not user:
            return []
        instance_service.sync_all_status(db)
        insts = instance_service.list_instances(db, user, only_active=only_active)
        rs = _runtime_settings(db)
        return [_inst_to_dict(i, refresh_runtime=True, rs=rs) for i in insts]
    finally:
        db.close()


def _get_instance(instance_id: int) -> Dict[str, Any]:
    db = _db()
    try:
        user = _get_admin_user(db)
        if not user:
            return {"error": "未找到可用的管理员账户"}
        inst = instance_service.get_instance(db, instance_id, user)
        if not inst:
            return {"error": "实例不存在"}
        instance_service._apply_runtime_status(inst)
        db.commit()
        rs = _runtime_settings(db)
        return _inst_to_dict(inst, rs=rs)
    finally:
        db.close()


def _start_instance(
    template_id: Optional[int],
    image: Optional[str],
    name: Optional[str],
    command: str,
    env: List[str],
    exposed_ports: List[int],
    privileged: bool,
    timeout_seconds: Optional[int],
    auto_remove: bool,
) -> Dict[str, Any]:
    from . import schemas
    db = _db()
    try:
        user = _get_admin_user(db)
        if not user:
            return {"error": "未找到可用的管理员账户"}
        rs = _runtime_settings(db)
        payload = schemas.InstanceStartIn(
            template_id=template_id,
            name=name,
            image=image,
            command=command,
            env=env,
            exposed_ports=exposed_ports,
            privileged=privileged,
            timeout_seconds=timeout_seconds,
            auto_remove=auto_remove,
        )
        inst, err = instance_service.start_instance(db, user, payload, rs)
        if inst is None:
            return {"error": err}
        return _inst_to_dict(inst, rs=rs)
    except Exception as e:  # noqa: BLE001
        return {"error": f"启动实例异常: {e}"}
    finally:
        db.close()


def _start_stopped_instance(instance_id: int, timeout_seconds: Optional[int] = None) -> Dict[str, Any]:
    db = _db()
    try:
        user = _get_admin_user(db)
        if not user:
            return {"error": "未找到可用的管理员账户"}
        inst = instance_service.get_instance(db, instance_id, user)
        if not inst:
            return {"error": "实例不存在"}
        rs = _runtime_settings(db)
        try:
            renewed = instance_service.start_existing(db, inst, rs=rs, timeout_seconds=timeout_seconds)
        except DockerError as e:
            return {"error": str(e)}
        out = _inst_to_dict(inst, rs=rs)
        if renewed:
            out["renewed"] = True
        return out
    finally:
        db.close()


def _stop_instance(instance_id: int, timeout: int) -> Dict[str, Any]:
    db = _db()
    try:
        user = _get_admin_user(db)
        if not user:
            return {"error": "未找到可用的管理员账户"}
        inst = instance_service.get_instance(db, instance_id, user)
        if not inst:
            return {"error": "实例不存在"}
        try:
            instance_service.stop_instance(db, inst, timeout=timeout)
        except DockerError as e:
            return {"error": f"停止失败: {e}"}
        except Exception as e:  # noqa: BLE001
            return {"error": f"停止异常: {e}"}
        rs = _runtime_settings(db)
        out = _inst_to_dict(inst, rs=rs)
        out["docker_verified"] = _verify_docker_gone(inst)
        return out
    finally:
        db.close()


def _restart_instance(instance_id: int, timeout: int) -> Dict[str, Any]:
    db = _db()
    try:
        user = _get_admin_user(db)
        if not user:
            return {"error": "未找到可用的管理员账户"}
        inst = instance_service.get_instance(db, instance_id, user)
        if not inst:
            return {"error": "实例不存在"}
        if not inst.container_id:
            return {"error": "容器尚未创建"}
        try:
            docker_service.restart(inst.container_id, timeout=timeout)
            inst.status = "running"
            db.commit()
        except DockerError as e:
            return {"error": str(e)}
        except Exception as e:  # noqa: BLE001
            return {"error": f"重启异常: {e}"}
        rs = _runtime_settings(db)
        return _inst_to_dict(inst, rs=rs)
    finally:
        db.close()


def _remove_instance(instance_id: int, force: bool) -> Dict[str, Any]:
    db = _db()
    try:
        user = _get_admin_user(db)
        if not user:
            return {"error": "未找到可用的管理员账户"}
        inst = instance_service.get_instance(db, instance_id, user)
        if not inst:
            return {"error": "实例不存在"}
        try:
            instance_service.remove_instance(db, inst, force=force)
        except DockerError as e:
            return {"error": f"删除失败: {e}"}
        except Exception as e:  # noqa: BLE001
            return {"error": f"删除异常: {e}"}
        rs = _runtime_settings(db)
        out = _inst_to_dict(inst, rs=rs)
        out["docker_verified"] = _verify_docker_gone(inst)
        return out
    finally:
        db.close()


def _verify_docker_gone(inst: models.Instance) -> Dict[str, Any]:
    """停止/删除后核对 Docker 层面是否还有该实例的容器（供 agent 判断是否真正生效）。"""
    if inst.kind == "compose":
        if not inst.project_name:
            return {"still_present": False, "still_running": 0, "note": "无 project_name"}
        try:
            cs = benchmark_service._compose_containers(inst.project_name)
            running = sum(1 for c in cs if c.get("status") == "running")
            return {"still_present": len(cs) > 0, "still_running": running, "containers": cs}
        except Exception as e:  # noqa: BLE001
            return {"still_present": None, "error": str(e)}
    if not inst.container_id:
        return {"still_present": False, "note": "无 container_id"}
    st = docker_service.container_status(inst.container_id)
    return {"still_present": st not in ("removed", "unknown"), "status": st}


def _get_instance_logs(instance_id: int, tail: int) -> Dict[str, Any]:
    db = _db()
    try:
        user = _get_admin_user(db)
        if not user:
            return {"logs": "", "error": "未找到可用的管理员账户"}
        inst = instance_service.get_instance(db, instance_id, user)
        if not inst:
            return {"logs": "", "error": "实例不存在"}
        if inst.kind == "compose":
            if not inst.project_name:
                return {"logs": ""}
            return {"logs": benchmark_service.compose_logs(inst.project_name, tail=tail)}
        if not inst.container_id:
            return {"logs": ""}
        return {"logs": docker_service.logs(inst.container_id, tail=tail)}
    finally:
        db.close()


def _extend_instance(instance_id: int, add_seconds: int) -> Dict[str, Any]:
    db = _db()
    try:
        user = _get_admin_user(db)
        if not user:
            return {"error": "未找到可用的管理员账户"}
        inst = instance_service.get_instance(db, instance_id, user)
        if not inst:
            return {"error": "实例不存在"}
        rs = _runtime_settings(db)
        instance_service.extend_instance(db, inst, add_seconds, rs)
        return _inst_to_dict(inst, rs=rs)
    finally:
        db.close()


def _set_instance_timeout(instance_id: int, timeout_seconds: int) -> Dict[str, Any]:
    db = _db()
    try:
        user = _get_admin_user(db)
        if not user:
            return {"error": "未找到可用的管理员账户"}
        inst = instance_service.get_instance(db, instance_id, user)
        if not inst:
            return {"error": "实例不存在"}
        rs = _runtime_settings(db)
        instance_service.set_instance_timeout(db, inst, timeout_seconds, rs)
        return _inst_to_dict(inst, rs=rs)
    finally:
        db.close()


def _list_templates() -> List[Dict[str, Any]]:
    db = _db()
    try:
        tpls = db.query(models.Template).order_by(models.Template.id).all()
        return [_template_to_dict(t) for t in tpls]
    finally:
        db.close()


def _list_benchmarks() -> List[Dict[str, Any]]:
    db = _db()
    try:
        rs = _runtime_settings(db)
        root = rs.benchmarks_root
        if not root:
            return []
        running: Dict[str, models.Instance] = {}
        for inst in db.query(models.Instance).filter(models.Instance.kind == "compose").all():
            if inst.benchmark_id and inst.status in ("running", "creating", "partial", "stopped"):
                cur = running.get(inst.benchmark_id)
                if cur is None or inst.id > cur.id:
                    running[inst.benchmark_id] = inst
        out = []
        for b in benchmark_service.list_benchmarks(root):
            r = running.get(b.id)
            out.append(_scrub_flag(b.to_dict(
                running=bool(r) and r.status in ("running", "creating", "partial"),
                instance_id=r.id if r else None,
            )))
        return out
    finally:
        db.close()


def _get_benchmark(bench_id: str) -> Dict[str, Any]:
    db = _db()
    try:
        rs = _runtime_settings(db)
        info = benchmark_service.get_benchmark(bench_id, rs.benchmarks_root)
        if not info:
            return {"error": "benchmark 不存在"}
        r = (
            db.query(models.Instance)
            .filter(models.Instance.kind == "compose", models.Instance.benchmark_id == bench_id)
            .order_by(models.Instance.id.desc())
            .first()
        )
        return _scrub_flag(info.to_dict(
            running=bool(r) and r.status in ("running", "creating", "partial"),
            instance_id=r.id if r else None,
        ))
    finally:
        db.close()


def _launch_benchmark(bench_id: str, timeout_seconds: Optional[int]) -> Dict[str, Any]:
    db = _db()
    try:
        user = _get_admin_user(db)
        if not user:
            return {"error": "未找到可用的管理员账户"}
        rs = _runtime_settings(db)
        inst, err = benchmark_service.launch_benchmark(db, user, bench_id, rs, timeout_seconds=timeout_seconds)
        if inst is None:
            return {"error": err}
        return _inst_to_dict(inst, rs=rs)
    finally:
        db.close()


def _get_system_stats() -> Dict[str, Any]:
    import platform as _pf
    import shutil
    import psutil
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    disk_path = "C:\\" if _pf.system() == "Windows" else "/"
    disk = shutil.disk_usage(disk_path)
    disk_percent = round(disk.used / disk.total * 100, 1) if disk.total else 0.0
    try:
        containers = docker_service.client.containers.list(all=True)
        running = [c for c in containers if c.status == "running"]
    except Exception:  # noqa: BLE001
        containers, running = [], []
    return {
        "cpu_percent": round(cpu, 2),
        "memory_percent": round(mem.percent, 2),
        "memory_total_gb": round(mem.total / 1024 ** 3, 2),
        "disk_percent": disk_percent,
        "containers_total": len(containers),
        "containers_running": len(running),
    }


def _get_instance_stats(instance_id: int) -> Dict[str, Any]:
    db = _db()
    try:
        user = _get_admin_user(db)
        if not user:
            return {"error": "未找到可用的管理员账户"}
        inst = instance_service.get_instance(db, instance_id, user)
        if not inst:
            return {"error": "实例不存在"}
        if not inst.container_id:
            return {"error": "容器尚未创建"}
        try:
            s = docker_service.stats(inst.container_id)
        except DockerError as e:
            return {"error": str(e)}
        return {
            "instance_id": inst.id,
            "container_id": inst.container_id[:12],
            "name": inst.name,
            **s,
        }
    finally:
        db.close()


def _ping_docker() -> Dict[str, Any]:
    return {
        "reachable": docker_service.ping(),
        "docker_host": settings.docker_host,
    }


def _list_images() -> List[Dict[str, Any]]:
    try:
        return docker_service.list_local_images()
    except DockerError as e:
        return [{"error": str(e)}]


# ---- FastMCP 装配 ----

def build_server() -> FastMCP:
    """构造并注册所有 MCP 工具，返回 FastMCP 实例。

    streamable_http_path 设为 "/" 以便可通过 ASGI mount 前缀灵活挂载。
    """
    mcp = FastMCP(
        SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
        streamable_http_path="/",
        log_level="INFO",
        # 远程 agent 通过公网 IP / 域名访问时，MCP SDK 默认会因 host 为 127.0.0.1
        # 而自动启用 DNS 重绑定保护（仅允许 127.0.0.1/localhost 的 Host 头），
        # 公网访问会被拒为 "Invalid Host header"。这里显式关闭该保护；
        # 端点鉴权由 _BearerAuthASGI 的 Bearer Token 中间件负责。
        host="0.0.0.0",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
            allowed_hosts=["*"],
            allowed_origins=["*"],
        ),
    )

    @mcp.tool()
    def list_instances(only_active: bool = False) -> str:
        """列出容器实例（容器 + compose 统一）。

        Args:
            only_active: 仅返回运行中/构建中的实例（默认 False 列出全部）。

        Returns:
            JSON 数组，每项含 id/name/image/status/ports/host/remaining_seconds 等。
        """
        import json
        return json.dumps(_list_instances(only_active=only_active), ensure_ascii=False, indent=2)

    @mcp.tool()
    def get_instance(instance_id: int) -> str:
        """查询单个容器实例的详情与实时状态。

        Args:
            instance_id: 实例 ID（list_instances 返回的 id）。
        """
        import json
        return json.dumps(_get_instance(instance_id), ensure_ascii=False, indent=2)

    @mcp.tool()
    def start_instance(
        template_id: Optional[int] = None,
        image: Optional[str] = None,
        name: Optional[str] = None,
        command: str = "",
        env: Optional[List[str]] = None,
        exposed_ports: Optional[List[int]] = None,
        privileged: bool = False,
        timeout_seconds: Optional[int] = None,
        auto_remove: bool = False,
    ) -> str:
        """启动一个新的容器实例。需提供 template_id 或 image 至少其一。

        Args:
            template_id: 靶机模板 ID（优先）。可先用 list_templates 查看。
            image: 镜像名（无模板时直接给，如 ubuntu:22.04）。
            name: 实例名称（可选，留空自动生成）。
            command: 启动命令（可选，覆盖模板/镜像默认）。
            env: 环境变量列表，形如 ["KEY=val"]。
            exposed_ports: 容器内需暴露的端口列表，如 [22, 80]。
            privileged: 是否特权模式（危险，谨慎使用）。
            timeout_seconds: 实例存活超时秒数（到点自动停止）；留空走平台默认。
            auto_remove: 容器停止后是否自动删除。
        """
        import json
        return json.dumps(
            _start_instance(
                template_id=template_id,
                image=image,
                name=name,
                command=command,
                env=env or [],
                exposed_ports=exposed_ports or [],
                privileged=privileged,
                timeout_seconds=timeout_seconds,
                auto_remove=auto_remove,
            ),
            ensure_ascii=False, indent=2,
        )

    @mcp.tool()
    def start_stopped_instance(instance_id: int, timeout_seconds: Optional[int] = None) -> str:
        """启动一个已停止的容器实例（不重新创建容器）。

        若该实例已过期，会自动续期到默认超时上限内（避免启动后被 reaper 立即停止）；
        可通过 timeout_seconds 指定续期秒数（受 max_instance_timeout 限制）。

        Args:
            instance_id: 实例 ID。
            timeout_seconds: 可选，续期秒数；不传则用平台默认超时。
        """
        import json
        return json.dumps(_start_stopped_instance(instance_id, timeout_seconds=timeout_seconds), ensure_ascii=False, indent=2)

    @mcp.tool()
    def stop_instance(instance_id: int, timeout: int = 10) -> str:
        """停止一个运行中的实例（不删除，可后续 start）。

        Args:
            instance_id: 实例 ID。
            timeout: 发送 SIGTERM 后等待秒数，超时强杀。
        """
        import json
        return json.dumps(_stop_instance(instance_id, timeout=timeout), ensure_ascii=False, indent=2)

    @mcp.tool()
    def restart_instance(instance_id: int, timeout: int = 10) -> str:
        """重启一个实例（容器内重启，保留容器与端口映射）。

        Args:
            instance_id: 实例 ID。
            timeout: 停止等待秒数。
        """
        import json
        return json.dumps(_restart_instance(instance_id, timeout=timeout), ensure_ascii=False, indent=2)

    @mcp.tool()
    def remove_instance(instance_id: int, force: bool = True) -> str:
        """删除一个实例（停止并移除容器/compose 栈）。

        Args:
            instance_id: 实例 ID。
            force: 是否强制删除（即使运行中）。
        """
        import json
        return json.dumps(_remove_instance(instance_id, force=force), ensure_ascii=False, indent=2)

    @mcp.tool()
    def get_instance_logs(instance_id: int, tail: int = 500) -> str:
        """查看实例日志（单容器或 compose 多服务合并）。

        Args:
            instance_id: 实例 ID。
            tail: 末尾行数（默认 500）。
        """
        import json
        return json.dumps(_get_instance_logs(instance_id, tail=tail), ensure_ascii=False, indent=2)

    @mcp.tool()
    def extend_instance(instance_id: int, add_seconds: int) -> str:
        """延长实例存活时间（续期，受平台最大超时上限约束）。

        Args:
            instance_id: 实例 ID。
            add_seconds: 续期秒数（须 > 0）。
        """
        import json
        return json.dumps(_extend_instance(instance_id, add_seconds=add_seconds), ensure_ascii=False, indent=2)

    @mcp.tool()
    def set_instance_timeout(instance_id: int, timeout_seconds: int) -> str:
        """重设实例超时（自现在起多少秒后过期，受平台最大超时上限约束）。

        Args:
            instance_id: 实例 ID。
            timeout_seconds: 新的超时秒数（须 > 0）。
        """
        import json
        return json.dumps(_set_instance_timeout(instance_id, timeout_seconds=timeout_seconds), ensure_ascii=False, indent=2)

    @mcp.tool()
    def list_templates() -> str:
        """列出所有靶机模板（含镜像/端口/资源限制等），用于 start_instance 选模板。"""
        import json
        return json.dumps(_list_templates(), ensure_ascii=False, indent=2)

    @mcp.tool()
    def list_benchmarks() -> str:
        """列出所有可用 XBEN benchmarks（docker-compose 多服务靶场），含是否在运行。

        注意：返回结果不含 flag；flag 需启动实例后通过实际漏洞利用在靶机内获取。"""
        import json
        return json.dumps(_list_benchmarks(), ensure_ascii=False, indent=2)

    @mcp.tool()
    def get_benchmark(bench_id: str) -> str:
        """查询单个 XBEN benchmark 详情（端口/服务/描述等，不含 flag）。

        flag 不会通过本工具返回——需启动实例后对目标进行 Web 安全漏洞利用，在靶机环境中获取。

        Args:
            bench_id: benchmark ID，如 XBEN-086-24。
        """
        import json
        return json.dumps(_get_benchmark(bench_id), ensure_ascii=False, indent=2)

    @mcp.tool()
    def launch_benchmark(bench_id: str, timeout_seconds: Optional[int] = None) -> str:
        """启动一个 XBEN benchmark 为 compose 实例（异步构建，立即返回 creating）。

        启动后返回的实例信息不含 flag——flag 需对运行中的目标进行 Web 安全漏洞利用，在靶机环境中实际获取。

        Args:
            bench_id: benchmark ID。
            timeout_seconds: 存活超时秒数（留空走默认）。
        """
        import json
        return json.dumps(_launch_benchmark(bench_id, timeout_seconds=timeout_seconds), ensure_ascii=False, indent=2)

    @mcp.tool()
    def get_system_stats() -> str:
        """宿主机系统资源概览：CPU/内存/磁盘 + 容器总数与运行数。"""
        import json
        return json.dumps(_get_system_stats(), ensure_ascii=False, indent=2)

    @mcp.tool()
    def get_instance_stats(instance_id: int) -> str:
        """查询单个实例的实时资源占用（CPU/内存/网络）。

        Args:
            instance_id: 实例 ID。
        """
        import json
        return json.dumps(_get_instance_stats(instance_id), ensure_ascii=False, indent=2)

    @mcp.tool()
    def ping_docker() -> str:
        """测试 Docker Daemon 连通性。"""
        import json
        return json.dumps(_ping_docker(), ensure_ascii=False, indent=2)

    @mcp.tool()
    def list_images() -> str:
        """列出本地已存在的 Docker 镜像（用于选择 start_instance 的 image 参数）。"""
        import json
        return json.dumps(_list_images(), ensure_ascii=False, indent=2)

    return mcp


# 全局单例（HTTP 挂载与 stdio 复用同一实例）
_server: Optional[FastMCP] = None


def get_server() -> FastMCP:
    global _server
    if _server is None:
        _server = build_server()
    return _server


def run_stdio() -> None:
    """以 stdio 传输运行 MCP server（agent 进程通过 stdin/stdout 通信）。"""
    import sys

    log_file = (settings.mcp_stdio_log_file or "").strip()
    if not log_file:
        from pathlib import Path
        log_file = str(Path(settings.compose_work_dir) / "mcp.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8")],
    )
    # stdio 模式下禁用 stderr 干扰输出，确保协议只走 stdin/stdout
    sys.stderr.write(f"[mcp] starting stdio server, log -> {log_file}\n")
    init_db()
    mcp = get_server()
    mcp.run(transport="stdio")


def streamable_http_asgi():
    """返回可挂载到 FastAPI/Starlette 的 ASGI 子应用（streamable HTTP 传输）。

    若 settings.mcp_http_token 非空，则在外层包裹一层 Bearer Token 鉴权：
    客户端必须在请求头携带 `Authorization: Bearer <token>`，否则返回 401。
    """
    inner = get_server().streamable_http_app()
    token = (settings.mcp_http_token or "").strip()
    if not token:
        return inner
    return _BearerAuthASGI(inner, token)


class _BearerAuthASGI:
    """极简 ASGI 中间件：校验 `Authorization: Bearer <token>` 请求头。

    通过 OPTIONS（CORS 预检）与已通过校验的请求透传给内部应用，其余返回 401。
    """

    def __init__(self, app, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "")
        # 放行 CORS 预检
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return
        # 取 Authorization 头
        auth_header: str = ""
        for name, value in scope.get("headers", []) or []:
            if name == b"authorization":
                auth_header = value.decode("latin-1", "replace")
                break
        expected = f"Bearer {self.token}"
        if auth_header == expected:
            await self.app(scope, receive, send)
            return
        # 鉴权失败：JSON 错误 + WWW-Authenticate 提示
        body = b'{"jsonrpc":"2.0","error":{"code":-32001,"message":"unauthorized: invalid or missing Authorization header"}}'
        await send({"type": "http.response.start", "status": 401, "headers": [
            (b"content-type", b"application/json"),
            (b"www-authenticate", b'Bearer realm="xbow-cyber-range-mcp"'),
            (b"content-length", str(len(body)).encode("ascii")),
        ]})
        await send({"type": "http.response.body", "body": body})


def main() -> None:
    run_stdio()


if __name__ == "__main__":
    main()