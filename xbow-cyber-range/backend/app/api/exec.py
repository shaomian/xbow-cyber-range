"""终端 exec 路由（WebSocket）。"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from .. import models
from ..deps import get_db_dep, get_runtime_settings
from ..config import settings
from ..auth import decode_access_token
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


@router.websocket("/api/instances/{instance_id}/terminal")
async def terminal_ws(websocket: WebSocket, instance_id: int, token: Optional[str] = None):
    """浏览器 <-> 容器 TTY 双向中继。

    约定：
    - 客户端发送二进制 = 写入容器 stdin
    - 客户端发送文本 = 控制消息 JSON：{"type":"resize","cols":..,"rows":..}
    - 服务端发送二进制 = 容器 stdout/stderr
    """
    username = _authenticate_ws(token)
    if not username:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    db: Session = next(get_db_dep())
    sock = None
    try:
        rs = None
        try:
            rs = RuntimeSettings(db)
        except Exception:  # noqa: BLE001
            pass
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
        if not inst.container_id:
            await websocket.send_text(json.dumps({"type": "error", "message": "容器尚未创建（实例可能仍在构建中或已停止）"}, ensure_ascii=False))
            await websocket.close()
            return

        cmd = (rs.terminal_default_command if rs else settings.terminal_default_command) or "/bin/sh"

        try:
            exec_id = docker_service.create_exec(inst.container_id, command=cmd)
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

        await asyncio.gather(pump_out(), pump_in(), return_exceptions=True)
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
        if sock is not None:
            try:
                sock.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
        db.close()


def _recv(sock, n: int) -> bytes:
    try:
        return sock.recv(n)
    except Exception:  # noqa: BLE001
        return b""


def _sendall(sock, data: bytes) -> None:
    sock.sendall(data)
