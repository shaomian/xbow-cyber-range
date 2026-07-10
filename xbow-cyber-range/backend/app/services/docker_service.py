"""Docker SDK 封装：容器生命周期、随机端口分配、资源监控、exec 终端。"""
from __future__ import annotations

import socket
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import docker
from docker.errors import APIError, ContainerError, ImageNotFound, NotFound
from docker.models.containers import Container

from ..config import settings


class DockerError(Exception):
    pass


class DockerService:
    """单例式 Docker 客户端封装。"""

    def __init__(self) -> None:
        self._client: Optional[docker.DockerClient] = None

    @property
    def client(self) -> docker.DockerClient:
        if self._client is None:
            try:
                self._client = docker.DockerClient(base_url=settings.docker_host)
                self._client.ping()
            except Exception as e:  # noqa: BLE001
                raise DockerError(f"无法连接 Docker ({settings.docker_host}): {e}") from e
        return self._client

    def reset(self) -> None:
        self._client = None

    # ---- 基础信息 ----
    def ping(self) -> bool:
        try:
            self.client.ping()
            return True
        except Exception:  # noqa: BLE001
            return False

    def list_local_images(self) -> List[dict]:
        try:
            imgs = self.client.images.list()
            out = []
            for im in imgs:
                tags = im.attrs.get("RepoTags") or []
                out.append({
                    "id": (im.id or "").replace("sha256:", "")[:12],
                    "tags": tags,
                    "size_mb": round((im.attrs.get("Size", 0) or 0) / 1024 / 1024, 1),
                })
            return out
        except APIError as e:
            raise DockerError(str(e)) from e

    def has_image(self, image: str) -> bool:
        try:
            self.client.images.get(image)
            return True
        except ImageNotFound:
            return False
        except APIError:
            return False

    # ---- 端口分配 ----
    @staticmethod
    def _is_port_free(port: int, host: str = "0.0.0.0") -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return True
            except OSError:
                return False

    def used_host_ports(self) -> set:
        """已分配的宿主端口（来自所有正在运行的容器）。"""
        used = set()
        try:
            for c in self.client.containers.list(all=True):
                ports = c.attrs.get("NetworkSettings", {}).get("Ports", {}) or {}
                for _, bindings in ports.items():
                    if not bindings:
                        continue
                    for b in bindings:
                        if b and "HostPort" in b:
                            try:
                                used.add(int(b["HostPort"]))
                            except (TypeError, ValueError):
                                pass
        except APIError:
            pass
        return used

    def allocate_ports(
        self,
        container_ports: List[int],
        port_start: int,
        port_end: int,
        requested: Optional[Dict[int, int]] = None,
    ) -> Dict[int, int]:
        """为容器内端口在 [start, end] 范围内随机分配宿主端口。"""
        if port_end <= port_start:
            raise DockerError(f"端口范围无效: [{port_start}, {port_end}]")
        used = self.used_host_ports()
        result: Dict[int, int] = {}
        # 先处理用户指定
        if requested:
            for cp, hp in requested.items():
                if hp and hp not in used and self._is_port_free(hp):
                    result[int(cp)] = int(hp)
                    used.add(int(hp))
        # 剩余的随机分配
        import random
        pool = [p for p in range(port_start, port_end + 1) if p not in used]
        random.shuffle(pool)
        idx = 0
        for cp in container_ports:
            if cp in result:
                continue
            allocated = None
            while idx < len(pool):
                cand = pool[idx]
                idx += 1
                if self._is_port_free(cand):
                    allocated = cand
                    break
            if allocated is None:
                # 再扫一遍已使用集合之外
                for cand in range(port_start, port_end + 1):
                    if cand in used or cand in result.values():
                        continue
                    if self._is_port_free(cand):
                        allocated = cand
                        break
            if allocated is None:
                raise DockerError(f"端口范围内无可用端口分配给容器端口 {cp}")
            result[int(cp)] = allocated
            used.add(allocated)
        return result

    # ---- 容器生命周期 ----
    def _labels(self, extra: Optional[dict] = None) -> dict:
        base = {settings.container_label_key: settings.container_label_value}
        if extra:
            base.update(extra)
        return base

    def create_and_start(
        self,
        *,
        name: str,
        image: str,
        command: str = "",
        entrypoint: str = "",
        env: Optional[List[str]] = None,
        exposed_ports: Optional[List[int]] = None,
        port_bindings: Optional[Dict[int, int]] = None,
        privileged: bool = False,
        memory_limit_mb: int = 0,
        cpu_quota: int = 0,
        network: str = "",
        labels: Optional[dict] = None,
        auto_remove: bool = False,
    ) -> Tuple[str, str]:
        """创建并启动容器，返回 (container_id, status)。"""
        env = env or []
        exposed_ports = exposed_ports or []
        port_bindings = port_bindings or {}

        # 构造 ports 字典：{"22/tcp": ("0.0.0.0", 21012)}
        ports_dict = {f"{p}/tcp": ("0.0.0.0", hp) for p, hp in port_bindings.items()}

        # 拉取镜像（如不存在）
        if not self.has_image(image):
            try:
                self.client.images.pull(image)
            except APIError as e:
                raise DockerError(f"拉取镜像 {image} 失败: {e}") from e

        mem_limit = f"{memory_limit_mb}m" if memory_limit_mb > 0 else None
        cpu_quota_val = cpu_quota * 100000 if cpu_quota > 0 else 0  # 1 CPU = 100000

        kwargs = dict(
            image=image,
            name=name,
            detach=True,
            labels=self._labels(labels),
            ports=ports_dict or None,
            environment=env or None,
            privileged=privileged,
            mem_limit=mem_limit,
            auto_remove=auto_remove,
            stdin_open=True,
            tty=True,
        )
        if command:
            kwargs["command"] = command
        if entrypoint:
            kwargs["entrypoint"] = entrypoint
        if cpu_quota_val > 0:
            kwargs["cpu_quota"] = cpu_quota_val
            kwargs["cpu_period"] = 100000
        if network:
            kwargs["network"] = network

        try:
            container = self.client.containers.run(**kwargs)
        except (APIError, ContainerError, ImageNotFound) as e:
            raise DockerError(str(e)) from e

        # 刷新 attrs
        try:
            container.reload()
        except Exception:  # noqa: BLE001
            pass
        status = (container.status or "created")
        return container.id, status

    def get_container(self, container_id: str) -> Optional[Container]:
        try:
            return self.client.containers.get(container_id)
        except NotFound:
            return None
        except APIError:
            return None

    def container_status(self, container_id: str) -> str:
        c = self.get_container(container_id)
        if not c:
            return "removed"
        try:
            c.reload()
            return c.status or "unknown"
        except Exception:  # noqa: BLE001
            return "unknown"

    def stop(self, container_id: str, timeout: int = 10) -> None:
        c = self.get_container(container_id)
        if not c:
            return
        try:
            c.stop(timeout=timeout)
        except Exception as e:  # noqa: BLE001
            raise DockerError(f"停止失败: {e}") from e

    def start(self, container_id: str) -> None:
        c = self.get_container(container_id)
        if not c:
            raise DockerError("容器不存在")
        try:
            c.start()
        except Exception as e:  # noqa: BLE001
            raise DockerError(f"启动失败: {e}") from e

    def restart(self, container_id: str, timeout: int = 10) -> None:
        c = self.get_container(container_id)
        if not c:
            raise DockerError("容器不存在")
        try:
            c.restart(timeout=timeout)
        except Exception as e:  # noqa: BLE001
            raise DockerError(f"重启失败: {e}") from e

    def remove(self, container_id: str, force: bool = True) -> None:
        c = self.get_container(container_id)
        if not c:
            return
        try:
            c.remove(force=force)
        except Exception as e:  # noqa: BLE001
            raise DockerError(f"删除失败: {e}") from e

    def remove_image(self, ref: str, force: bool = True) -> bool:
        """删除本地镜像，ref 可为 repo:tag 或镜像 id（短/长）。返回是否尝试删除。

        镜像不存在或删除失败不抛错，返回 False 即可，避免主流程被镜像清理阻断。
        """
        if not ref:
            return False
        try:
            self.client.images.remove(ref, force=force)
            return True
        except ImageNotFound:
            return False
        except APIError:
            # 可能被其它引用占用，尝试按前缀去重等失败时忽略，交由后续 prune 兜底
            return False

    def logs(self, container_id: str, tail: int = 500, since: Optional[int] = None) -> str:
        c = self.get_container(container_id)
        if not c:
            return ""
        try:
            data = c.logs(tail=tail, since=since, timestamps=True)
            if isinstance(data, bytes):
                return data.decode("utf-8", errors="replace")
            return str(data)
        except Exception as e:  # noqa: BLE001
            return f"[读取日志失败: {e}]"

    # ---- 端口绑定读取 ----
    def get_port_bindings(self, container_id: str) -> Dict[int, int]:
        c = self.get_container(container_id)
        if not c:
            return {}
        try:
            c.reload()
        except Exception:  # noqa: BLE001
            pass
        ports = c.attrs.get("NetworkSettings", {}).get("Ports", {}) or {}
        out: Dict[int, int] = {}
        for key, bindings in ports.items():
            if not bindings:
                continue
            try:
                cp = int(str(key).split("/", 1)[0])
            except ValueError:
                continue
            for b in bindings:
                if b and "HostPort" in b:
                    try:
                        out[cp] = int(b["HostPort"])
                        break
                    except (TypeError, ValueError):
                        continue
        return out

    # ---- 资源监控 ----
    def stats(self, container_id: str) -> dict:
        c = self.get_container(container_id)
        if not c:
            return {}
        try:
            s = c.stats(stream=False)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

        # CPU
        cpu_delta = 0.0
        cpu_system = 0.0
        cpu_percent = 0.0
        try:
            cpu = s.get("cpu_stats", {})
            pre_cpu = s.get("precpu_stats", {})
            cpu_total = cpu.get("cpu_usage", {}).get("total_usage", 0) or 0
            pre_total = pre_cpu.get("cpu_usage", {}).get("total_usage", 0) or 0
            cpu_system = cpu.get("system_cpu_usage", 0) or 0
            pre_system = pre_cpu.get("system_cpu_usage", 0) or 0
            cpu_delta = cpu_total - pre_total
            sys_delta = cpu_system - pre_system
            ncpu = cpu.get("online_cpus", 1) or 1
            if sys_delta > 0 and cpu_delta > 0:
                cpu_percent = (cpu_delta / sys_delta) * ncpu * 100.0
        except Exception:  # noqa: BLE001
            pass

        # Memory
        mem_used_mb = 0.0
        mem_limit_mb = 0.0
        try:
            mem = s.get("memory_stats", {})
            usage = mem.get("usage", 0) or 0
            limit = mem.get("limit", 0) or 0
            # 减去 cache（更接近实际使用）
            cache = mem.get("stats", {}).get("cache", 0) or 0
            mem_used_mb = max(0.0, (usage - cache) / 1024 / 1024)
            mem_limit_mb = (limit / 1024 / 1024) if limit else 0.0
        except Exception:  # noqa: BLE001
            pass

        # Network
        net_rx_kb = 0.0
        net_tx_kb = 0.0
        try:
            nets = s.get("networks", {}) or {}
            for _, v in nets.items():
                net_rx_kb += (v.get("rx_bytes", 0) or 0) / 1024
                net_tx_kb += (v.get("tx_bytes", 0) or 0) / 1024
        except Exception:  # noqa: BLE001
            pass

        return {
            "cpu_percent": round(cpu_percent, 2),
            "memory_used_mb": round(mem_used_mb, 2),
            "memory_limit_mb": round(mem_limit_mb, 2),
            "net_rx_kb": round(net_rx_kb, 2),
            "net_tx_kb": round(net_tx_kb, 2),
            "status": (c.status or "unknown"),
        }

    # ---- 快照 commit ----
    def commit(self, container_id: str, repository: str, tag: str, note: str = "") -> Tuple[str, str]:
        c = self.get_container(container_id)
        if not c:
            raise DockerError("容器不存在")
        try:
            img = c.commit(repository=repository, tag=tag, message=note or None)
            return (img.id or "").replace("sha256:", "")[:12], f"{repository}:{tag}"
        except Exception as e:  # noqa: BLE001
            raise DockerError(f"快照失败: {e}") from e

    # ---- exec 终端 ----
    def create_exec(self, container_id: str, command: str = "/bin/sh") -> str:
        c = self.get_container(container_id)
        if not c:
            raise DockerError("容器不存在")
        try:
            exec_id = self.client.api.exec_create(container=container_id, cmd=command, stdin=True, tty=True)
            return exec_id["Id"]
        except Exception as e:  # noqa: BLE001
            raise DockerError(f"创建 exec 失败: {e}") from e

    def start_exec_socket(self, exec_id: str):
        """返回 docker 的 exec websocket/socket，调用方需自行处理读写。"""
        try:
            return self.client.api.exec_start(exec_id=exec_id, socket=True, tty=True, demux=False)
        except Exception as e:  # noqa: BLE001
            raise DockerError(f"启动 exec 失败: {e}") from e

    def exec_resize(self, exec_id: str, cols: int, rows: int) -> None:
        try:
            self.client.api.exec_resize(exec_id=exec_id, height=rows, width=cols)
        except Exception:  # noqa: BLE001
            pass


docker_service = DockerService()
