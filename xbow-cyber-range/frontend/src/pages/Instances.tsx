import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  Tooltip,
  App,
} from "antd";
import {
  PlusOutlined,
  ReloadOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
  DeleteOutlined,
  ClockCircleOutlined,
  CodeOutlined,
} from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { instancesApi, type InstanceOut } from "../api/instances";
import { templatesApi, type Template } from "../api/templates";
import Countdown from "../components/Countdown";

const statusColor: Record<string, string> = {
  running: "green",
  creating: "blue",
  stopped: "default",
  exited: "orange",
  removed: "red",
  paused: "gold",
  restarting: "cyan",
};

export default function InstancesPage() {
  const { message } = App.useApp();
  const nav = useNavigate();
  const [data, setData] = useState<InstanceOut[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(false);
  const [onlyActive, setOnlyActive] = useState(false);
  const [startOpen, setStartOpen] = useState(false);
  const [extendId, setExtendId] = useState<number | null>(null);
  const [extendMin, setExtendMin] = useState(30);

  const refresh = async () => {
    setLoading(true);
    try {
      const [ins, tpls] = await Promise.all([
        instancesApi.list(onlyActive),
        templatesApi.list(),
      ]);
      setData(ins);
      setTemplates(tpls);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, [onlyActive]);

  // 定时刷新（倒计时本地秒级递减，但每 15s 同步一次后端）
  useEffect(() => {
    const t = setInterval(() => {
      instancesApi.list(onlyActive).then(setData).catch(() => {});
    }, 15000);
    return () => clearInterval(t);
  }, [onlyActive]);

  const doStart = async (payload: any) => {
    const inst = await instancesApi.start(payload);
    message.success(`已启动：${inst.name}`);
    setStartOpen(false);
    refresh();
  };

  const doExtend = async () => {
    if (extendId == null) return;
    await instancesApi.extend(extendId, Math.floor(extendMin * 60));
    message.success("已续期");
    setExtendId(null);
    refresh();
  };

  const columns = useMemo(
    () => [
      { title: "名称", dataIndex: "name", render: (v: string, r: InstanceOut) => <a onClick={() => nav(`/instances/${r.id}`)}>{v}</a> },
      {
        title: "类型",
        dataIndex: "kind",
        width: 90,
        render: (v: string, r: InstanceOut) =>
          v === "compose" ? (
            <Tooltip title={r.benchmark_id ?? ""}>
              <Tag color="purple">compose</Tag>
            </Tooltip>
          ) : (
            <Tag>容器</Tag>
          ),
      },
      { title: "镜像/Benchmark", dataIndex: "image", ellipsis: true, render: (v: string, r: InstanceOut) => r.benchmark_id ? <Tag color="geekblue">{r.benchmark_id}</Tag> : v },
      {
        title: "状态",
        dataIndex: "status",
        render: (v: string) => <Tag color={statusColor[v] ?? "default"}>{v}</Tag>,
      },
      {
        title: "端口映射",
        dataIndex: "ports",
        render: (ports: Record<string, number>, r: InstanceOut) => {
          const entries = Object.entries(ports || {});
          if (!entries.length) return <Tag>无</Tag>;
          return (
            <Space wrap size={4}>
              {entries.map(([cp, hp]) => (
                <Tag key={cp} color="blue" style={{ fontFamily: "monospace" }}>
                  <a href={`http://${window.location.hostname}:${hp}`} target="_blank" rel="noreferrer">
                    {hp}→{cp}
                  </a>
                </Tag>
              ))}
            </Space>
          );
        },
      },
      {
        title: "剩余时间",
        render: (_: any, r: InstanceOut) => (
          <Countdown remaining={r.remaining_seconds} status={r.status} />
        ),
      },
      { title: "启动时间", dataIndex: "started_at", render: (v: string) => (v ? new Date(v).toLocaleString() : "-") },
      {
        title: "操作",
        render: (_: any, r: InstanceOut) => (
          <Space size={0} wrap>
            <Button
              type="link"
              size="small"
              icon={<CodeOutlined />}
              disabled={r.status !== "running"}
              onClick={() => nav(`/instances/${r.id}?tab=terminal`)}
            >
              终端
            </Button>
            {r.status === "running" ? (
              <Popconfirm title="确认停止该实例？" onConfirm={async () => { await instancesApi.stop(r.id); refresh(); }}>
                <Button type="link" size="small" icon={<PauseCircleOutlined />}>停止</Button>
              </Popconfirm>
            ) : (
              <Button
                type="link"
                size="small"
                icon={<PlayCircleOutlined />}
                disabled={r.status === "removed"}
                onClick={async () => { await instancesApi.startExisting(r.id); refresh(); }}
              >
                启动
              </Button>
            )}
            <Button
              type="link"
              size="small"
              icon={<ClockCircleOutlined />}
              disabled={r.status === "removed"}
              onClick={() => { setExtendId(r.id); setExtendMin(30); }}
            >
              续期
            </Button>
            <Popconfirm
              title="确认删除该实例？"
              description="将同时删除对应容器（强制）。"
              onConfirm={async () => { await instancesApi.remove(r.id); refresh(); }}
            >
              <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
            </Popconfirm>
          </Space>
        ),
      },
    ],
    [nav]
  );

  return (
    <div>
      <Row justify="space-between" align="middle">
        <Typography.Title level={4} style={{ marginTop: 0 }}>实例管理</Typography.Title>
        <Space>
          <span>仅看运行中</span>
          <Switch checked={onlyActive} onChange={setOnlyActive} />
          <Button icon={<ReloadOutlined />} onClick={refresh} />
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setStartOpen(true)}>启动实例</Button>
        </Space>
      </Row>

      <Card>
        <Table
          rowKey="id"
          loading={loading}
          dataSource={data}
          columns={columns}
          pagination={{ pageSize: 15 }}
          scroll={{ x: 1100 }}
        />
      </Card>

      <StartModal
        open={startOpen}
        templates={templates}
        onClose={() => setStartOpen(false)}
        onSubmit={doStart}
      />

      <Modal
        title="续期实例"
        open={extendId != null}
        onCancel={() => setExtendId(null)}
        onOk={doExtend}
        okText="续期"
      >
        <div style={{ marginBottom: 8 }}>选择要延长的时长（分钟）：</div>
        <InputNumber
          min={1}
          max={480}
          value={extendMin}
          onChange={(v) => setExtendMin(v ?? 30)}
          style={{ width: 200 }}
          addonAfter="分钟"
        />
      </Modal>
    </div>
  );
}

function StartModal({
  open,
  templates,
  onClose,
  onSubmit,
}: {
  open: boolean;
  templates: Template[];
  onClose: () => void;
  onSubmit: (p: any) => void;
}) {
  const [mode, setMode] = useState<"template" | "image">("template");
  const [templateId, setTemplateId] = useState<number | undefined>();
  const [image, setImage] = useState("");
  const [name, setName] = useState("");
  const [ports, setPorts] = useState("");
  const [timeoutMin, setTimeoutMin] = useState<number>(60);
  const [autoRemove, setAutoRemove] = useState(false);

  useEffect(() => {
    if (open) {
      setMode("template");
      setTemplateId(templates[0]?.id);
      setImage("");
      setName("");
      setPorts("");
      setTimeoutMin(60);
      setAutoRemove(false);
    }
  }, [open, templates]);

  const submit = () => {
    const payload: any = { name: name || undefined, timeout_seconds: Math.floor(timeoutMin * 60), auto_remove: autoRemove };
    if (mode === "template") {
      payload.template_id = templateId;
    } else {
      payload.image = image;
      payload.exposed_ports = ports
        .split(",")
        .map((s) => parseInt(s.trim(), 10))
        .filter((n) => !Number.isNaN(n));
    }
    onSubmit(payload);
  };

  return (
    <Modal title="启动实例" open={open} onCancel={onClose} onOk={submit} okText="启动" width={560} destroyOnClose>
      <div style={{ marginBottom: 12 }}>
        <Select
          value={mode}
          onChange={setMode}
          style={{ width: 160 }}
          options={[
            { value: "template", label: "从模板启动" },
            { value: "image", label: "自定义镜像" },
          ]}
        />
      </div>
      {mode === "template" ? (
        <div style={{ marginBottom: 12 }}>
          <Select
            placeholder="选择模板"
            value={templateId}
            onChange={setTemplateId}
            style={{ width: "100%" }}
            options={templates.map((t) => ({ value: t.id, label: `${t.name} (${t.image})` }))}
          />
        </div>
      ) : (
        <>
          <Input
            placeholder="镜像 image:tag"
            value={image}
            onChange={(e) => setImage(e.target.value)}
            style={{ marginBottom: 12 }}
          />
          <Input
            placeholder="容器端口（逗号分隔，如 22,80）"
            value={ports}
            onChange={(e) => setPorts(e.target.value)}
            style={{ marginBottom: 12 }}
          />
        </>
      )}
      <Input
        placeholder="实例名称（可空，自动生成）"
        value={name}
        onChange={(e) => setName(e.target.value)}
        style={{ marginBottom: 12 }}
      />
      <Space style={{ width: "100%", justifyContent: "space-between" }}>
        <div>
          超时（分钟）：
          <InputNumber min={1} max={480} value={timeoutMin} onChange={(v) => setTimeoutMin(v ?? 60)} />
        </div>
        <div>
          退出自动删除：
          <Switch checked={autoRemove} onChange={setAutoRemove} style={{ marginLeft: 8 }} />
        </div>
      </Space>
    </Modal>
  );
}
