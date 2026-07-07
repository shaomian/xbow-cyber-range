import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Row,
  Statistic,
  Typography,
  App,
  Tag,
} from "antd";
import { ReloadOutlined, SaveOutlined } from "@ant-design/icons";
import { settingsApi, type PlatformSettings } from "../api/stats";

export default function SettingsPage() {
  const { message } = App.useApp();
  const [data, setData] = useState<PlatformSettings | null>(null);
  const [form] = Form.useForm<PlatformSettings>();
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    const s = await settingsApi.get();
    setData(s);
    form.setFieldsValue(s);
  };

  useEffect(() => {
    refresh();
  }, []);

  const onSave = async () => {
    setLoading(true);
    try {
      const vals = await form.validateFields();
      const updated = await settingsApi.update({
        port_range_start: vals.port_range_start,
        port_range_end: vals.port_range_end,
        default_instance_timeout: vals.default_instance_timeout,
        max_instance_timeout: vals.max_instance_timeout,
        terminal_default_command: vals.terminal_default_command,
        benchmarks_root: vals.benchmarks_root,
      });
      setData(updated);
      form.setFieldsValue(updated);
      message.success("已保存");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>系统设置</Typography.Title>
      <Row gutter={[16, 16]}>
        <Col xs={24} md={16}>
          <Card title="平台参数">
            <Form form={form} layout="vertical">
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item name="port_range_start" label="端口范围起始" rules={[{ required: true }]}>
                    <InputNumber min={1} max={65535} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="port_range_end" label="端口范围结束" rules={[{ required: true }]}>
                    <InputNumber min={1} max={65535} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="default_instance_timeout" label="默认实例超时（秒）" rules={[{ required: true }]}>
                    <InputNumber min={60} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="max_instance_timeout" label="单次最大超时（秒）" rules={[{ required: true }]}>
                    <InputNumber min={60} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col span={24}>
                  <Form.Item name="terminal_default_command" label="终端默认命令">
                    <Input placeholder="/bin/sh" />
                  </Form.Item>
                </Col>
                <Col span={24}>
                  <Form.Item name="benchmarks_root" label="靶场目录（XBEN benchmarks 根目录）">
                    <Input placeholder="留空则自动探测；如 D:\path\to\benchmarks" />
                  </Form.Item>
                </Col>
              </Row>
              <Button type="primary" icon={<SaveOutlined />} loading={loading} onClick={onSave}>
                保存
              </Button>
            </Form>
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card title="连接信息">
            {data && (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <Statistic title="Docker Host" value={data.docker_host} />
                <Statistic title="后台扫描间隔" value={data.reaper_interval_seconds} suffix="秒" />
                <Tag color="blue">修改后立即对所有新实例生效</Tag>
                <Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button>
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
