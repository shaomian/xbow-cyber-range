"""终端 exec 路由（WebSocket）。"""
from __future__ import annotations

import asyncio
import json
import logging
import socket as socket_mod
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from .. import models
from ..config import settings
from ..auth import decode_access_token
from ..database import SessionLocal
from ..deps import RuntimeSettings
from ..services import instance_service
from ..services.docker_service import DockerError, docker_service

router = APIRouter(tags=["terminal"])
logger = logging.getLogger("xbow_cyber_range.terminal")


def _authenticate_ws(token: Optional[str]) -> Optional[str]:
    """从 query 参数鉴权，返回 username。"""
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        return None
    return payload["sub"]


def _shutdown_sock(sock) -> None:
    """尽力唤醒阻塞在 recv/send 上的线程：shutdown + close（幂等）。"""
    if sock is None:
        return
    try:
        sock.shutdown(socket_mod.SHUT_RDWR)
    except Exception:  # noqa: BLE001
        pass
    try:
        sock.close()
    except Exception:  # noqa: BLE001
        pass


@router.websocket("/api/instances/{instance_id}/terminal")
async def terminal_ws(websocket: WebSocket, instance_id: int, token: Optional[str] = None, service: Optional[str] = None):
    """浏览器 <-> 容器 TTY 双向中继。

    约定：
    - 客户端发送二进制 = 写入容器 stdin
    - 客户端发送文本 = 控制消息 JSON：{"type":"resize","cols":..,"rows":..}
    - 服务端发送二进制 = 容器 stdout/stderr
    - service 参数：compose 多服务栈时指定目标服务（仅在实例自己的 project
      内按服务 label 解析，不接受任意 container id，防止越权 exec）

    连接池安全（历史上曾因此打挂整个 backend，勿回退）：
    1. DB 会话只在初始鉴权/解析阶段短暂持有，TTY relay 期间不占用任何连接。
    2. relay 收尾用 wait(FIRST_COMPLETED) + 关闭 socket 唤醒阻塞线程，
       不能用 gather 等两个方向都结束——容器静默时 sock.recv 永不返回，
       gather 永不结束，handler 挂死，连接永久泄漏。
    """
    username = _authenticate_ws(token)
    if not username:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    # ---- 阶段 1：鉴权 + 解析目标容器（短会话，用完立即归还连接池）----
    try:
        db = SessionLocal()
        try:
            user = db.query(models.User).filter(models.User.username == username).first()
            if not user:
                await websocket.send_text(json.dumps({"type": "error", "message": "用户不存在"}, ensure_ascii=False))
                await websocket.close()
                return
            inst = instance_service.get_instance(db, instance_id, user)
            if not inst:
                await websocket.send_text(json.dumps({"type": "error", "message": "实例不存在或无权限"}, ensure_ascii=False))
                await websocket.close()
                return
            target_container_id = inst.container_id
            is_compose = inst.kind == "compose"
            compose_project = inst.project_name if is_compose else None
            try:
                cmd = RuntimeSettings(db).terminal_default_command
            except Exception:  # noqa: BLE001
                cmd = None
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001
        await websocket.send_text(json.dumps({"type": "error", "message": f"初始化失败: {e}"}, ensure_ascii=False))
        await websocket.close()
        return

    cmd = cmd or settings.terminal_default_command or "/bin/sh"

    if service and is_compose:
        from ..services import benchmark_service
        if compose_project:
            cs = await asyncio.to_thread(benchmark_service._compose_containers, compose_project)
        else:
            cs = []
        running = [c for c in cs if c["service"] == service and c["status"] == "running"]
        if not running:
            await websocket.send_text(json.dumps({"type": "error", "message": f"服务不存在或未运行: {service}"}, ensure_ascii=False))
            await websocket.close()
            return
        target_container_id = running[0]["id"]
    if not target_container_id:
        await websocket.send_text(json.dumps({"type": "error", "message": "容器尚未创建（实例可能仍在构建中或已停止）"}, ensure_ascii=False))
        await websocket.close()
        return

    try:
        exec_id = docker_service.create_exec(target_container_id, command=cmd)
    except DockerError as e:
        await websocket.send_text(json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False))
        await websocket.close()
        return

    # docker-py exec_start(socket=True) 返回底层 socket，在线程池执行避免阻塞事件循环
    try:
        sock = await asyncio.to_thread(docker_service.start_exec_socket, exec_id)
    except DockerError as e:
        await websocket.send_text(json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False))
        await websocket.close()
        return

    if sock is None:
        await websocket.send_text(json.dumps({"type": "error", "message": "无法建立终端连接"}, ensure_ascii=False))
        await websocket.close()
        return

    sock.setblocking(True)
    await websocket.send_text(json.dumps({"type": "ready", "command": cmd}, ensure_ascii=False))

    # 初始尺寸
    try:
        await asyncio.to_thread(
            docker_service.exec_resize, exec_id, settings.terminal_cols, settings.terminal_rows
        )
    except Exception:  # noqa: BLE001
        pass

    stop = asyncio.Event()

    async def pump_out():
        """容器 -> 浏览器"""
        loop = asyncio.get_event_loop()
        while not stop.is_set():
            try:
                data = await loop.run_in_executor(None, _recv, sock, 4096)
            except Exception:  # noqa: BLE001
                break
            if not data:
                break
            try:
                await websocket.send_bytes(data)
            except WebSocketDisconnect:
                break
            except Exception:  # noqa: BLE001
                break

    async def pump_in():
        """浏览器 -> 容器"""
        loop = asyncio.get_event_loop()
        try:
            while not stop.is_set():
                try:
                    msg = await websocket.receive()
                except WebSocketDisconnect:
                    break
                if msg.get("type") == "websocket.disconnect":
                    break
                if "bytes" in msg and msg["bytes"] is not None:
                    data = msg["bytes"]
                    try:
                        await loop.run_in_executor(None, _sendall, sock, data)
                    except Exception:  # noqa: BLE001
                        break
                elif "text" in msg and msg["text"] is not None:
                    try:
                        ctl = json.loads(msg["text"])
                    except json.JSONDecodeError:
                        continue
                    if ctl.get("type") == "resize":
                        try:
                            await loop.run_in_executor(
                                None,
                                docker_service.exec_resize,
                                exec_id,
                                int(ctl.get("cols", 80)),
                                int(ctl.get("rows", 24)),
                            )
                        except Exception:  # noqa: BLE001
                            pass
        finally:
            stop.set()

    try:
        # 任一方向结束即收尾：先 stop + 关 socket 唤醒阻塞在 recv 的线程，
        # 再限时等待/取消剩余任务。绝不无条件等两个方向都结束。
        tasks = [asyncio.create_task(pump_out()), asyncio.create_task(pump_in())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        stop.set()
        _shutdown_sock(sock)
        if pending:
            await asyncio.wait(pending, timeout=5)
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
    except WebSocketDisconnect:
        logger.debug("终端 ws 断开: instance=%s", instance_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("终端 ws 处理异常: instance=%s err=%s", instance_id, e)
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": f"终端内部错误: {e}"}, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            pass
    finally:
        # 清理
        _shutdown_sock(sock)
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass


def _recv(sock, n: int) -> bytes:
    try:
        return sock.recv(n)
    except Exception:  # noqa: BLE001
        return b""


def _sendall(sock, data: bytes) -> None:
    sock.sendall(data)
