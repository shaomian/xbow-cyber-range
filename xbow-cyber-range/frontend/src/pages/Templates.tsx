import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  App,
} from "antd";
import { PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { templatesApi, type Template, type TemplateInput } from "../api/templates";
import { instancesApi } from "../api/instances";

const empty: TemplateInput = {
  name: "",
  image: "",
  description: "",
  command: "",
  entrypoint: "",
  env: [],
  exposed_ports: [],
  privileged: false,
  memory_limit_mb: 0,
  cpu_quota: 0,
  tags: "",
  is_public: true,
};

export default function TemplatesPage() {
  const { message } = App.useApp();
  const [data, setData] = useState<Template[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Template | null>(null);
  const [form] = Form.useForm<TemplateInput>();
  const [startLoadingId, setStartLoadingId] = useState<number | null>(null);

  const refresh = async () => {
    setLoading(true);
    try {
      setData(await templatesApi.list());
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue(empty);
    setModalOpen(true);
  };

  const openEdit = (tpl: Template) => {
    setEditing(tpl);
    form.setFieldsValue({
      ...tpl,
      env: tpl.env ?? [],
      exposed_ports: tpl.exposed_ports ?? [],
    });
    setModalOpen(true);
  };

  const parseList = (v: any): any[] => {
    if (Array.isArray(v)) return v;
    if (v == null || v === "") return [];
    return String(v)
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  };

  const parsePorts = (v: any): number[] =>
    parseList(v)
      .map((x) => parseInt(x, 10))
      .filter((n) => !Number.isNaN(n));

  const onSubmit = async () => {
    const vals = await form.validateFields();
    const payload: TemplateInput = {
      ...vals,
      env: parseList(vals.env),
      exposed_ports: parsePorts(vals.exposed_ports),
    };
    if (editing) {
      await templatesApi.update(editing.id, payload);
      message.success("已更新");
    } else {
      await templatesApi.create(payload);
      message.success("已创建");
    }
    setModalOpen(false);
    refresh();
  };

  const startOne = async (tpl: Template) => {
    setStartLoadingId(tpl.id);
    try {
      const inst = await instancesApi.start({ template_id: tpl.id, name: tpl.name });
      message.success(`实例已启动：${inst.name}`);
    } finally {
      setStartLoadingId(null);
    }
  };

  return (
    <div>
      <Row justify="space-between" align="middle">
        <Col>
          <Typography.Title level={4} style={{ marginTop: 0 }}>
            靶机模板
          </Typography.Title>
        </Col>
        <Col>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={refresh} />
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              新建模板
            </Button>
          </Space>
        </Col>
      </Row>

      <Card>
        <Table
          rowKey="id"
          loading={loading}
          dataSource={data}
          pagination={{ pageSize: 10 }}
          columns={[
            { title: "名称", dataIndex: "name", render: (v: string, r: Template) => <a onClick={() => openEdit(r)}>{v}</a> },
            { title: "镜像", dataIndex: "image" },
            { title: "暴露端口", dataIndex: "exposed_ports", render: (v: number[]) => v?.join(", ") || "-" },
            { title: "内存上限", dataIndex: "memory_limit_mb", render: (v: number) => (v ? `${v} MB` : "不限") },
            { title: "标签", dataIndex: "tags", render: (v: string) => v || "-" },
            {
              title: "可见",
              dataIndex: "is_public",
              render: (v: boolean) => (v ? <Tag color="green">公开</Tag> : <Tag>私有</Tag>),
            },
            {
              title: "操作",
              render: (_: any, r: Template) => (
                <Space>
                  <Button type="link" loading={startLoadingId === r.id} onClick={() => startOne(r)}>
                    启动
                  </Button>
                  <Button type="link" onClick={() => openEdit(r)}>
                    编辑
                  </Button>
                  <Popconfirm title="确认删除？" onConfirm={async () => { await templatesApi.remove(r.id); refresh(); }}>
                    <Button type="link" danger>删除</Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={editing ? "编辑模板" : "新建模板"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={onSubmit}
        okText="保存"
        width={680}
        destroyOnClose
      >
        <Form form={form} layout="vertical" initialValues={empty}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="name" label="模板名称" rules={[{ required: true }]}>
                <Input placeholder="如 kali-linux" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="image" label="镜像 (image:tag)" rules={[{ required: true }]}>
                <Input placeholder="如 kali/kali-rolling" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="command" label="启动命令 (command)">
                <Input placeholder="/bin/bash" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="entrypoint" label="Entrypoint">
                <Input placeholder="（可空）" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="env" label="环境变量（逗号分隔 KEY=val）">
            <Input placeholder="KEY1=v1, KEY2=v2" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="exposed_ports" label="容器暴露端口（逗号分隔）">
                <Input placeholder="22, 80, 8080" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="tags" label="标签（逗号分隔）">
                <Input placeholder="web, pwn" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="memory_limit_mb" label="内存上限 (MB, 0=不限)">
                <InputNumber min={0} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="cpu_quota" label="CPU 核数 (0=不限)">
                <InputNumber min={0} step={0.5} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={8} style={{ display: "flex", alignItems: "center", gap: 16, paddingTop: 30 }}>
              <Form.Item name="privileged" label=" " colon={false} valuePropName="checked">
                <Switch /> <span>特权模式</span>
              </Form.Item>
              <Form.Item name="is_public" label=" " colon={false} valuePropName="checked">
                <Switch /> <span>公开</span>
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  );
}
