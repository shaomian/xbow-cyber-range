# Backlog

代码审查发现的问题清单。**2026-11 首轮全部修复完毕**，保留作历史记录。

## 中优先级（已完成）

- [x] **修改密码走 query string，明文进日志**
  已改为 request body（`ChangePasswordIn`），前端同步改为 POST body。
  位置：`backend/app/api/auth.py`、`frontend/src/api/auth.ts`。
  备注：WebSocket 终端 token 仍在 query（浏览器 WS 无法带 header 属协议限制），
  如后续需要可改为一次性 ticket 换取连接。

- [x] **reaper 会回收 creating 状态的实例**
  creating 状态不按 expires_at 回收；仅当过期后仍超出 3600s 构建宽限期仍停在
  creating（构建线程死亡/重启残留）才回收。构建成功转 running 时按原定超时
  重新起算 expires_at（构建耗时不吃存活时长），受 max_instance_timeout 约束。
  位置：`instance_service.py`（reap_expired）、`benchmark_service.py`（_build_and_up_thread）。

- [x] **Dashboard 5s 轮询 × docker stats 串行 → 请求堆积**
  后端 `/api/stats/instances` 改为线程池并行采集（max 8 workers）；前端 refresh
  加 in-flight 防重入守卫，上次未完成跳过本轮。
  位置：`backend/app/api/stats.py`、`frontend/src/pages/Dashboard.tsx`。

- [x] **系统设置无数值校验**
  超时字段加 `gt=1`（0/负数 422）；端口范围加 `gt=0, lt=65536`；默认超时 >
  单次最大超时返回 400 交叉校验。
  位置：`backend/app/schemas.py`、`backend/app/api/settings.py`。

## 低优先级（已完成）

- [x] **续期/设置超时弹窗 max=480 硬编码**
  新增 `GET /api/settings/public`（仅需登录），返回 default/max_instance_timeout；
  前端模块级缓存获取，Instances/InstanceDetail/Benchmarks 弹窗上限与"留空默认"
  提示全部动态取值。
  位置：`backend/app/api/settings.py`、`frontend/src/api/stats.ts`、三个页面。

- [x] **Countdown 对 removed 实例显示"不过期"**
  removed 单独分支显示"已删除"。
  位置：`frontend/src/components/Countdown.tsx`。

- [x] **端口分配并发竞态**
  进程内锁串行化分配决策 + 带 TTL（15min，覆盖 compose build+up 时长）的预留表，
  端口在真正绑定到容器前对后续分配可见。单进程部署下有效。
  位置：`backend/app/services/docker_service.py`（allocate_ports）。

- [x] **多服务 compose 终端连到列表第一个容器**
  实例详情返回运行中的服务列表（`compose_services`）；终端 WebSocket 支持
  `service` 参数，仅在实例自己的 project 内按服务 label 解析容器（防越权 exec）；
  详情页终端 Tab 多服务时显示服务选择器。
  位置：`backend/app/api/exec.py`、`backend/app/api/instances.py`、
  `frontend/src/components/TerminalPanel.tsx`、`frontend/src/pages/InstanceDetail.tsx`。

- [x] **Dashboard"容器总数"统计宿主机全部容器**
  改名"宿主机容器总数" + Tooltip 说明含非平台管理的容器（compose 容器无
  managed label，按 label 过滤会漏，故采用语义化标注）。
  位置：`frontend/src/pages/Dashboard.tsx`。
