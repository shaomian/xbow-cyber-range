# Backlog

代码审查发现的待修复问题（已完成：模板越权启动、删除用户清理容器、compose 启动前端超时、
不安全默认配置启动告警，见 git 历史）。

## 中优先级

- [ ] **修改密码走 query string，明文进日志**
  `POST /api/auth/change-password?old_password=...&new_password=...`，uvicorn 访问日志
  完整记录 URL，密码永久泄漏到日志文件。改为 request body 传参。
  位置：`backend/app/api/auth.py`（change_password 参数改为 Pydantic 模型）、
  `frontend/src/api/auth.ts:26`。
  附带：WebSocket 终端的 token 也在 query（`wsUrl()`），浏览器 WS 无法带 header 属协议
  限制，可接受；但访问日志同样会记录，可考虑改用一次性 ticket 换取 WS 连接。

- [ ] **reaper 会回收 creating 状态的实例**
  构建（最长 3600s）期间的 benchmark 若默认超时较短（如 600s），会被 reaper 强停，
  而后台构建线程仍在跑并最终把状态写回 running，状态错乱。
  修复思路：creating 状态不参与回收，或 expires_at 从 running 起算。
  位置：`backend/app/services/instance_service.py`（reap_expired 的 status 过滤）、
  `benchmark_service.py`（_build_and_up_thread 完成时刷新 expires_at）。

- [ ] **Dashboard 5s 轮询 × docker stats 串行 → 请求堆积**
  `c.stats(stream=False)` 单次约 1-2s，`/api/stats/instances` 逐实例串行统计；
  5+ 实例时单请求超过前端 5s 轮询间隔，请求堆积直至 axios 30s 超时报错。
  修复思路：并行化 stats 调用 / 用一次 `docker stats` 流聚合所有容器 / 降频轮询。
  位置：`backend/app/api/stats.py`、`frontend/src/pages/Dashboard.tsx`。

- [ ] **系统设置无数值校验**
  default_instance_timeout / max_instance_timeout 可设 0 或负数 → 实例秒过期。
  位置：`backend/app/schemas.py`（PlatformSettingsUpdateIn 加 gt=1 校验）。

## 低优先级

- [ ] **续期/设置超时弹窗 max=480 硬编码**：管理员调大 max_instance_timeout 后 UI 输不进去。
  位置：`frontend/src/pages/Instances.tsx`（extendMin）、`frontend/src/pages/InstanceDetail.tsx`。
  根因同"启动弹窗 480 硬编码"问题：需要一个登录用户可读的公开设置端点，
  或改为留空走后端默认（参考启动弹窗的修复方式）。

- [ ] **Countdown 对 removed 实例显示"不过期"**：语义错误，应显示"已删除"。
  位置：`frontend/src/components/Countdown.tsx`（`sec == null || status === "removed"` 分支）。

- [ ] **端口分配并发竞态**：两个同时启动可能选中同一空闲端口，后一个 docker create
  报"端口已被占用"。可加进程内锁 + 分配后重查。
  位置：`backend/app/services/docker_service.py`（allocate_ports）。

- [ ] **多服务 compose 终端连到列表第一个容器**：不一定是用户想进的目标服务。
  修复思路：实例详情终端加服务选择器（compose 实例列出 project 下各服务容器）。
  位置：`backend/app/services/benchmark_service.py:648`（cs[0] 回填）、
  `backend/app/api/exec.py`、`frontend/src/components/TerminalPanel.tsx`。

- [ ] **Dashboard"容器总数"统计宿主机全部容器**：含非平台管理的容器，数字与平台
  实例数对不上，易困惑。可按 managed label 过滤或区分展示。
  位置：`backend/app/api/stats.py`（system_stats）。
