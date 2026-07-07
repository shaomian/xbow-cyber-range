import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Switch,
  Table,
  Tag,
  Typography,
  Space,
  App,
} from "antd";
import { PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { usersApi, authApi, type UserOut } from "../api/auth";
import { getUser } from "../api/client";

export default function UsersPage() {
  const { message } = App.useApp();
  const [data, setData] = useState<UserOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [pwdOpen, setPwdOpen] = useState<UserOut | null>(null);
  const [pwd, setPwd] = useState("");
  const [regOpen, setRegOpen] = useState(false);
  const me = getUser();

  const refresh = async () => {
    setLoading(true);
    try {
      setData(await usersApi.list());
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div>
      <Space style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
        <Typography.Title level={4} style={{ marginTop: 0 }}>用户管理</Typography.Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={refresh} />
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setRegOpen(true)}>新建用户</Button>
        </Space>
      </Space>
      <Card>
        <Table
          rowKey="id"
          loading={loading}
          dataSource={data}
          pagination={false}
          columns={[
            { title: "ID", dataIndex: "id", width: 60 },
            { title: "用户名", dataIndex: "username" },
            {
              title: "角色",
              dataIndex: "is_admin",
              render: (v: boolean) => (v ? <Tag color="gold">管理员</Tag> : <Tag>普通用户</Tag>),
            },
            {
              title: "状态",
              dataIndex: "is_active",
              render: (v: boolean, r: UserOut) => (
                <Switch
                  checked={v}
                  disabled={r.username === me?.username}
                  onChange={async (checked) => {
                    await usersApi.update(r.id, { is_active: checked });
                    refresh();
                  }}
                />
              ),
            },
            { title: "注册时间", dataIndex: "created_at", render: (v: string) => new Date(v).toLocaleString() },
            {
              title: "操作",
              render: (_: any, r: UserOut) => (
                <Space>
                  <Button
                    type="link"
                    size="small"
                    onClick={async () => {
                      await usersApi.update(r.id, { is_admin: !r.is_admin });
                      refresh();
                    }}
                    disabled={r.username === me?.username}
                  >
                    {r.is_admin ? "取消管理员" : "设为管理员"}
                  </Button>
                  <Button type="link" size="small" onClick={() => { setPwdOpen(r); setPwd(""); }}>
                    改密码
                  </Button>
                  <Popconfirm
                    title="确认删除该用户？"
                    onConfirm={async () => { await usersApi.remove(r.id); refresh(); }}
                    disabled={r.username === me?.username}
                  >
                    <Button type="link" size="small" danger disabled={r.username === me?.username}>删除</Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={`修改密码：${pwdOpen?.username ?? ""}`}
        open={pwdOpen != null}
        onCancel={() => setPwdOpen(null)}
        onOk={async () => {
          if (!pwd || pwd.length < 6) {
            message.error("密码至少 6 位");
            return;
          }
          await usersApi.update(pwdOpen!.id, { password: pwd });
          message.success("密码已更新");
          setPwdOpen(null);
        }}
        okText="保存"
      >
        <Input.Password
          placeholder="新密码（至少 6 位）"
          value={pwd}
          onChange={(e) => setPwd(e.target.value)}
        />
      </Modal>

      <Modal
        title="新建用户"
        open={regOpen}
        onCancel={() => setRegOpen(false)}
        destroyOnClose
        footer={null}
      >
        <Form
          layout="vertical"
          onFinish={async (vals: { username: string; password: string }) => {
            try {
              await authApi.register(vals.username, vals.password);
              message.success("已创建");
              setRegOpen(false);
              refresh();
            } catch {
              /* noop */
            }
          }}
        >
          <Form.Item name="username" label="用户名" rules={[{ required: true }, { min: 3 }]}>
            <Input />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true }, { min: 6 }]}>
            <Input.Password />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>创建</Button>
        </Form>
      </Modal>
    </div>
  );
}
