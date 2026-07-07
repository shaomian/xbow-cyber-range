import { useEffect, useState } from "react";
import { Card, Col, Row, Statistic, Progress, Table, Typography, Tag } from "antd";
import {
  ContainerOutlined,
  DashboardOutlined,
  HddOutlined,
  PlayCircleOutlined,
} from "@ant-design/icons";
import { statsApi, type ContainerStats, type SystemStats } from "../api/stats";
import { instancesApi, type InstanceOut } from "../api/instances";

export default function DashboardPage() {
  const [sys, setSys] = useState<SystemStats | null>(null);
  const [instStats, setInstStats] = useState<ContainerStats[]>([]);
  const [instances, setInstances] = useState<InstanceOut[]>([]);

  const refresh = async () => {
    const [s, ist, ins] = await Promise.all([statsApi.system(), statsApi.instances(), instancesApi.list()]);
    setSys(s);
    setInstStats(ist);
    setInstances(ins);
  };

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, []);

  const running = instances.filter((i) => i.status === "running").length;

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>仪表盘</Typography.Title>
      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title="运行中实例" value={running} prefix={<PlayCircleOutlined />} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title="容器总数" value={sys?.containers_total ?? 0} prefix={<ContainerOutlined />} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title="系统 CPU" value={sys?.cpu_percent ?? 0} suffix="%" prefix={<DashboardOutlined />} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title="内存使用" value={sys?.memory_percent ?? 0} suffix="%" prefix={<HddOutlined />} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} md={8}>
          <Card title="CPU 使用率">
            <Progress percent={Math.round(sys?.cpu_percent ?? 0)} status="active" />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card title="内存使用率">
            <Progress percent={Math.round(sys?.memory_percent ?? 0)} status="active" strokeColor="#722ed1" />
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card title="磁盘使用率">
            <Progress percent={Math.round(sys?.disk_percent ?? 0)} strokeColor="#fa8c16" />
          </Card>
        </Col>
      </Row>

      <Card title="运行中实例资源占用" style={{ marginTop: 16 }}>
        <Table
          rowKey="instance_id"
          size="small"
          dataSource={instStats}
          pagination={{ pageSize: 8 }}
          columns={[
            { title: "实例", dataIndex: "name" },
            { title: "容器", dataIndex: "container_id" },
            {
              title: "状态",
              dataIndex: "status",
              render: (s: string) => <Tag color={s === "running" ? "green" : "default"}>{s}</Tag>,
            },
            { title: "CPU %", dataIndex: "cpu_percent", render: (v: number) => v.toFixed(2) },
            {
              title: "内存",
              render: (_: any, r: ContainerStats) =>
                `${r.memory_used_mb.toFixed(1)} / ${r.memory_limit_mb.toFixed(0)} MB`,
            },
            { title: "入网 KB", dataIndex: "net_rx_kb", render: (v: number) => v.toFixed(1) },
            { title: "出网 KB", dataIndex: "net_tx_kb", render: (v: number) => v.toFixed(1) },
          ]}
        />
      </Card>
    </div>
  );
}
