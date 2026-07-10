import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Button,
  Card,
  Col,
  Descriptions,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Space,
  Statistic,
  Tabs,
  Tag,
  Typography,
  App,
} from "antd";
import {
  ArrowLeftOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  ClockCircleOutlined,
  CameraOutlined,
  DeleteOutlined,
} from "@ant-design/icons";
import { instancesApi, snapshotsApi, type InstanceOut, type SnapshotOut } from "../api/instances";
import { statsApi, type ContainerStats } from "../api/stats";
import Countdown from "../components/Countdown";
import TerminalPanel from "../components/TerminalPanel";

export default function InstanceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [sp] = useSearchParams();
  const nav = useNavigate();
  const { message } = App.useApp();
  const [inst, setInst] = useState<InstanceOut | null>(null);
  const [stats, setStats] = useState<ContainerStats | null>(null);
  const [snapshots, setSnapshots] = useState<SnapshotOut[]>([]);
  const [activeTab, setActiveTab] = useState(sp.get("tab") || "info");
  const [snapOpen, setSnapOpen] = useState(false);
  const [snapTag, setSnapTag] = useState("");
  const [snapNote, setSnapNote] = useState("");
  const [extendMin, setExtendMin] = useState(30);
  const [extendOpen, setExtendOpen] = useState(false);
  const [timeoutMin, setTimeoutMin] = useState(60);
  const [timeoutOpen, setTimeoutOpen] = useState(false);

  const instanceId = Number(id);

  const refresh = async () => {
    if (!id) return;
    const [i, snaps] = await Promise.all([
      instancesApi.get(instanceId),
      snapshotsApi.list(instanceId).catch(() => []),
    ]);
    setInst(i);
    setSnapshots(snaps);
    if (i.status === "running") {
      statsApi.instance(instanceId).then(setStats).catch(() => {});
    }
  };

  useEffect(() => {
    refresh();
    const t = setInterval(() => {
      if (instanceId) instancesApi.get(instanceId).then(setInst).catch(() => {});
    }, 10000);
    return () => clearInterval(t);
  }, [instanceId]);

  if (!inst) return <Typography.Text>加载中...</Typography.Text>;

  const ports = Object.entries(inst.ports || {});

  const doSnapshot = async () => {
    const tag = snapTag || `snap-${inst.id}-${Date.now()}`;
    await snapshotsApi.create(instanceId, tag, snapNote);
    message.success("快照已生成");
    setSnapOpen(false);
    setSnapTag("");
    setSnapNote("");
    refresh();
  };

  const doExtend = async () => {
    await instancesApi.extend(instanceId, Math.floor(extendMin * 60));
    message.success("已续期");
    setExtendOpen(false);
    refresh();
  };

  const doSetTimeout = async () => {
    await instancesApi.setTimeout(instanceId, Math.floor(timeoutMin * 60));
    message.success("超时已更新");
    setTimeoutOpen(false);
    refresh();
  };

  return (
    <div>
      <Row justify="space-between" align="middle">
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => nav("/instances")}>返回</Button>
          <Typography.Title level={4} style={{ margin: 0 }}>
            实例详情 - {inst.name}
          </Typography.Title>
          <Tag color={inst.status === "running" ? "green" : "default"}>{inst.status}</Tag>
        </Space>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={refresh} />
          {inst.status === "running" ? (
            <Popconfirm title="确认停止？" onConfirm={async () => { await instancesApi.stop(instanceId); refresh(); }}>
              <Button icon={<PauseCircleOutlined />}>停止</Button>
            </Popconfirm>
          ) : (
            <Button
              icon={<PlayCircleOutlined />}
              disabled={inst.status === "removed"}
              onClick={async () => { await instancesApi.startExisting(instanceId); refresh(); }}
            >
              启动
            </Button>
          )}
          <Button icon={<ClockCircleOutlined />} disabled={inst.status === "removed"} onClick={() => { setExtendMin(30); setExtendOpen(true); }}>
            续期
          </Button>
          <Button icon={<ClockCircleOutlined />} disabled={inst.status === "removed"} onClick={() => { setTimeoutMin(60); setTimeoutOpen(true); }}>
            改超时
          </Button>
          <Button icon={<CameraOutlined />} disabled={inst.status === "removed"} onClick={() => setSnapOpen(true)}>
            快照
          </Button>
          <Popconfirm title="确认删除该实例？" onConfirm={async () => { await instancesApi.remove(instanceId); nav("/instances"); }}>
            <Button danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      </Row>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        style={{ marginTop: 16 }}
        items={[
          {
            key: "info",
            label: "基本信息",
            children: (
              <Row gutter={[16, 16]}>
                <Col span={24}>
                  <Card>
                    <Descriptions column={2} bordered size="small">
                      <Descriptions.Item label="实例 ID">{inst.id}</Descriptions.Item>
                      <Descriptions.Item label="容器 ID">{inst.container_id?.slice(0, 12) || "-"}</Descriptions.Item>
                      <Descriptions.Item label="名称">{inst.name}</Descriptions.Item>
                      <Descriptions.Item label="镜像/Benchmark">
                        {inst.kind === "compose" && inst.benchmark_id ? (
                          <Tag color="geekblue">{inst.benchmark_id}</Tag>
                        ) : (
                          inst.image
                        )}
                      </Descriptions.Item>
                      <Descriptions.Item label="类型">
                        {inst.kind === "compose" ? <Tag color="purple">compose 多服务栈</Tag> : <Tag>单容器</Tag>}
                      </Descriptions.Item>
                      <Descriptions.Item label="状态">
                        <Tag color={inst.status === "running" ? "green" : "default"}>{inst.status}</Tag>
                      </Descriptions.Item>
                      <Descriptions.Item label="自动删除">{inst.auto_remove ? "是" : "否"}</Descriptions.Item>
                      {inst.kind === "compose" && inst.project_name && (
                        <Descriptions.Item label="Compose Project" span={2}>
                          <Typography.Text code>{inst.project_name}</Typography.Text>
                        </Descriptions.Item>
                      )}
                      {inst.flag && (
                        <Descriptions.Item label="Flag" span={2}>
                          <Typography.Paragraph code copyable style={{ margin: 0, wordBreak: "break-all" }}>
                            {inst.flag}
                          </Typography.Paragraph>
                        </Descriptions.Item>
                      )}
                      <Descriptions.Item label="启动时间">
                        {inst.started_at ? new Date(inst.started_at).toLocaleString() : "-"}
                      </Descriptions.Item>
                      <Descriptions.Item label="停止时间">
                        {inst.stopped_at ? new Date(inst.stopped_at).toLocaleString() : "-"}
                      </Descriptions.Item>
                      <Descriptions.Item label="过期时间">
                        {inst.expires_at ? new Date(inst.expires_at).toLocaleString() : "不过期"}
                      </Descriptions.Item>
                      <Descriptions.Item label="剩余时间">
                        <Countdown remaining={inst.remaining_seconds} status={inst.status} />
                      </Descriptions.Item>
                      <Descriptions.Item label="访问地址" span={2}>
                        {ports.length ? (
                          <Space wrap>
                            {ports.map(([cp, hp]) => (
                              <Tag key={cp} color="blue">
                                <a href={`http://${window.location.hostname}:${hp}`} target="_blank" rel="noreferrer">
                                  {window.location.hostname}:{hp} → 容器:{cp}
                                </a>
                              </Tag>
                            ))}
                          </Space>
                        ) : (
                          <Tag>无端口映射</Tag>
                        )}
                      </Descriptions.Item>
                      {inst.last_error && (
                        <Descriptions.Item label="错误信息" span={2}>
                          <Typography.Text type="danger">{inst.last_error}</Typography.Text>
                        </Descriptions.Item>
                      )}
                    </Descriptions>
                  </Card>
                </Col>
                {inst.status === "running" && stats && (
                  <Col span={24}>
                    <Card title="资源占用">
                      <Row gutter={16}>
                        <Col span={6}><Statistic title="CPU" value={stats.cpu_percent} suffix="%" /></Col>
                        <Col span={6}>
                          <Statistic
                            title="内存"
                            value={stats.memory_used_mb}
                            suffix={`/ ${stats.memory_limit_mb.toFixed(0)} MB`}
                          />
                        </Col>
                        <Col span={6}><Statistic title="入网" value={stats.net_rx_kb} suffix="KB" /></Col>
                        <Col span={6}><Statistic title="出网" value={stats.net_tx_kb} suffix="KB" /></Col>
                      </Row>
                    </Card>
                  </Col>
                )}
              </Row>
            ),
          },
          {
            key: "terminal",
            label: "终端",
            children: inst.status === "running" ? (
              <TerminalPanel instanceId={instanceId} />
            ) : (
              <Typography.Text type="secondary">实例未运行，无法连接终端。请先启动实例。</Typography.Text>
            ),
          },
          {
            key: "logs",
            label: "日志",
            children: <LogsPanel instanceId={instanceId} />,
          },
          {
            key: "snapshots",
            label: "快照/历史",
            children: (
              <Card>
                <Space style={{ marginBottom: 12 }}>
                  <Button icon={<CameraOutlined />} onClick={() => setSnapOpen(true)}>新建快照</Button>
                  <Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button>
                </Space>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      {["ID", "镜像 ID", "Tag", "备注", "时间", "操作"].map((h) => (
                        <th key={h} style={{ textAlign: "left", padding: 8, borderBottom: "1px solid #eee" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {snapshots.length === 0 && (
                      <tr><td colSpan={6} style={{ padding: 16, textAlign: "center", color: "#999" }}>暂无快照</td></tr>
                    )}
                    {snapshots.map((s) => (
                      <tr key={s.id}>
                        <td style={{ padding: 8 }}>{s.id}</td>
                        <td style={{ padding: 8, fontFamily: "monospace" }}>{s.image_id}</td>
                        <td style={{ padding: 8 }}>{s.image_tag}</td>
                        <td style={{ padding: 8 }}>{s.note || "-"}</td>
                        <td style={{ padding: 8 }}>{new Date(s.created_at).toLocaleString()}</td>
                        <td style={{ padding: 8 }}>
                          <Popconfirm title="删除该快照记录？" onConfirm={async () => { await snapshotsApi.remove(instanceId, s.id); refresh(); }}>
                            <Button type="link" danger size="small">删除</Button>
                          </Popconfirm>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            ),
          },
        ]}
      />

      <Modal title="创建快照" open={snapOpen} onCancel={() => setSnapOpen(false)} onOk={doSnapshot} okText="生成">
        <div style={{ marginBottom: 8 }}>镜像 Tag（留空自动生成）：</div>
        <InputNumber
          style={{ display: "none" }}
        />
        <input
          className="ant-input"
          style={{ width: "100%", padding: "4px 11px", marginBottom: 12 }}
          placeholder="如 myorg/myenv:20240101"
          value={snapTag}
          onChange={(e) => setSnapTag((e.target as HTMLInputElement).value)}
        />
        <div style={{ marginBottom: 8 }}>备注：</div>
        <input
          className="ant-input"
          style={{ width: "100%", padding: "4px 11px" }}
          placeholder="快照说明"
          value={snapNote}
          onChange={(e) => setSnapNote((e.target as HTMLInputElement).value)}
        />
      </Modal>

      <Modal title="续期" open={extendOpen} onCancel={() => setExtendOpen(false)} onOk={doExtend} okText="续期">
        <div style={{ marginBottom: 8 }}>延长时长（分钟）：</div>
        <InputNumber min={1} max={480} value={extendMin} onChange={(v) => setExtendMin(v ?? 30)} style={{ width: 200 }} addonAfter="分钟" />
      </Modal>

      <Modal title="设置超时" open={timeoutOpen} onCancel={() => setTimeoutOpen(false)} onOk={doSetTimeout} okText="设置">
        <div style={{ marginBottom: 8 }}>从现在起 N 分钟后自动停止：</div>
        <InputNumber min={1} max={480} value={timeoutMin} onChange={(v) => setTimeoutMin(v ?? 60)} style={{ width: 200 }} addonAfter="分钟" />
      </Modal>
    </div>
  );
}

function LogsPanel({ instanceId }: { instanceId: number }) {
  const [logs, setLogs] = useState("");
  const [tail, setTail] = useState(500);

  const load = async () => {
    const res = await instancesApi.logs(instanceId, tail);
    setLogs(res.logs || "(空)");
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [instanceId, tail]);

  return (
    <Card
      title="容器日志"
      extra={
        <Space>
          <span>行数</span>
          <InputNumber min={50} max={5000} value={tail} onChange={(v) => setTail(v ?? 500)} step={50} />
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        </Space>
      }
    >
      <pre
        style={{
          background: "#1e1e1e",
          color: "#d4d4d4",
          padding: 12,
          borderRadius: 6,
          maxHeight: 480,
          overflow: "auto",
          fontSize: 12,
          whiteSpace: "pre-wrap",
          wordBreak: "break-all",
        }}
      >
        {logs}
      </pre>
    </Card>
  );
}
