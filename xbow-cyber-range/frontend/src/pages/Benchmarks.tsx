import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  Col,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  App,
} from "antd";
import {
  ReloadOutlined,
  RocketOutlined,
  CheckCircleTwoTone,
  ClockCircleTwoTone,
} from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { benchmarksApi, type BenchmarkOut } from "../api/benchmarks";
import { instancesApi } from "../api/instances";

export default function BenchmarksPage() {
  const { message } = App.useApp();
  const nav = useNavigate();
  const [data, setData] = useState<BenchmarkOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [launchId, setLaunchId] = useState<string | null>(null);
  const [timeoutMin, setTimeoutMin] = useState(60);
  const [launching, setLaunching] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      setData(await benchmarksApi.list());
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    const t = setInterval(() => {
      benchmarksApi.list().then(setData).catch(() => {});
    }, 15000);
    return () => clearInterval(t);
  }, []);

  const filtered = useMemo(() => {
    const k = keyword.trim().toLowerCase();
    if (!k) return data;
    return data.filter(
      (b) =>
        b.id.toLowerCase().includes(k) ||
        b.name.toLowerCase().includes(k) ||
        b.description.toLowerCase().includes(k) ||
        b.host_ports.join(",").includes(k)
    );
  }, [data, keyword]);

  const runningCount = data.filter((b) => b.running).length;

  const doLaunch = async () => {
    if (!launchId) return;
    setLaunching(true);
    try {
      const inst = await benchmarksApi.launch(launchId, Math.floor(timeoutMin * 60));
      message.success(`已提交构建：${launchId}（实例 #${inst.id}）`);
      setLaunchId(null);
      nav(`/instances/${inst.id}`);
    } finally {
      setLaunching(false);
    }
  };

  return (
    <div>
      <Row justify="space-between" align="middle">
        <Typography.Title level={4} style={{ marginTop: 0 }}>
          靶场目录（XBEN Benchmarks）
        </Typography.Title>
        <Space>
          <Statistic title="运行中" value={runningCount} prefix={<CheckCircleTwoTone twoToneColor="#52c41a" />} valueStyle={{ fontSize: 16 }} />
          <Statistic title="总数" value={data.length} prefix={<ClockCircleTwoTone />} valueStyle={{ fontSize: 16 }} />
          <Button icon={<ReloadOutlined />} onClick={refresh} />
        </Space>
      </Row>

      <Card style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="按 ID / 名称 / 端口 搜索，如 XBEN-001 或 8080"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          allowClear
          size="large"
        />
      </Card>

      <Table
        rowKey="id"
        loading={loading}
        dataSource={filtered}
        pagination={{ pageSize: 20, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 104] }}
        scroll={{ x: 1000 }}
        columns={[
          {
            title: "ID",
            dataIndex: "id",
            width: 140,
            render: (v: string, r: BenchmarkOut) => (
              <Space direction="vertical" size={0}>
                <a onClick={() => nav(`/instances/${r.instance_id}`)} style={{ fontWeight: r.running ? 600 : 400 }}>
                  {v}
                </a>
                {r.running && <Tag color="green" style={{ margin: 0 }}>运行中 #{r.instance_id}</Tag>}
              </Space>
            ),
          },
          { title: "名称", dataIndex: "name", width: 140 },
          {
            title: "服务",
            dataIndex: "services",
            width: 160,
            render: (svcs: BenchmarkOut["services"]) => (
              <Space wrap size={4}>
                {svcs?.map((s) => (
                  <Tag key={s.name}>{s.name}{s.has_build ? " 🔨" : ""}</Tag>
                ))}
              </Space>
            ),
          },
          {
            title: "端口(容器)",
            dataIndex: "host_ports",
            width: 120,
            render: (hp: number[], r: BenchmarkOut) => {
              const cps = Array.from(
                new Set(r.services.flatMap((s) => s.ports.map((p) => p.container)))
              );
              if (!cps.length) return <Tag>无</Tag>;
              return (
                <Space wrap size={4}>
                  {cps.map((p) => (
                    <Tag key={p} color="blue">{p}</Tag>
                  ))}
                </Space>
              );
            },
          },
          {
            title: "Flag",
            width: 110,
            render: (_: any, r: BenchmarkOut) => (
              <Tooltip title={r.computed_flag}>
                <Typography.Text code style={{ fontSize: 12 }}>
                  {r.computed_flag.slice(0, 12)}…
                </Typography.Text>
              </Tooltip>
            ),
          },
          {
            title: "操作",
            width: 160,
            render: (_: any, r: BenchmarkOut) => (
              <Space>
                {r.running ? (
                  <Button type="link" size="small" onClick={() => nav(`/instances/${r.instance_id}`)}>
                    查看实例
                  </Button>
                ) : (
                  <Button
                    type="primary"
                    size="small"
                    icon={<RocketOutlined />}
                    disabled={!r.has_compose}
                    onClick={() => { setLaunchId(r.id); setTimeoutMin(60); }}
                  >
                    启动
                  </Button>
                )}
              </Space>
            ),
          },
        ]}
      />

      <Modal
        title={`启动 ${launchId ?? ""}`}
        open={launchId != null}
        onCancel={() => setLaunchId(null)}
        onOk={doLaunch}
        okText="启动"
        confirmLoading={launching}
        destroyOnClose
      >
        <Typography.Paragraph type="secondary">
          将通过 <Typography.Text code>docker compose build</Typography.Text> 构建并启动该 benchmark。
          构建可能需要几分钟（取决于镜像是否已缓存与依赖下载），期间状态为 <Tag>creating</Tag>，
          完成后变为 <Tag color="green">running</Tag>。固定宿主端口会被重映射到平台随机端口范围内。
        </Typography.Paragraph>
        <div style={{ marginBottom: 8 }}>
          构建使用的 Flag（复刻 <Typography.Text code>make run</Typography.Text>）：
        </div>
        <Typography.Paragraph code copyable style={{ wordBreak: "break-all" }}>
          {data.find((b) => b.id === launchId)?.computed_flag ?? ""}
        </Typography.Paragraph>
        <div style={{ marginBottom: 8 }}>超时自动停止（分钟）：</div>
        <InputNumber min={1} max={480} value={timeoutMin} onChange={(v) => setTimeoutMin(v ?? 60)} style={{ width: 200 }} addonAfter="分钟" />
        <Typography.Paragraph type="warning" style={{ marginTop: 12, fontSize: 12 }}>
          注意：部分 benchmark 构建时需 apt 下载。若你的 Docker 受本地代理(如 127.0.0.1:7897)影响，
          apt 可能失败——这是环境问题，请在 Docker Desktop 代理设置中处理。
        </Typography.Paragraph>
      </Modal>
    </div>
  );
}
