import { useEffect, useState } from "react";
import { Card, Form, Input, Tabs, Typography, Button, App } from "antd";
import { LockOutlined, UserOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { authApi } from "../api/auth";
import { setAuth } from "../api/client";

export default function LoginPage() {
  const nav = useNavigate();
  const { message } = App.useApp();
  const [allowReg, setAllowReg] = useState(true);

  useEffect(() => {
    authApi.registrationStatus()
      .then((s) => setAllowReg(s.allow_registration))
      .catch(() => {});
  }, []);

  const onLogin = async (vals: { username: string; password: string }) => {
    try {
      const res = await authApi.login(vals.username, vals.password);
      setAuth(res.access_token, { username: res.username, is_admin: res.is_admin });
      message.success("登录成功");
      nav("/");
    } catch {
      /* 错误提示由 axios 拦截器处理 */
    }
  };

  const onRegister = async (vals: { username: string; password: string }) => {
    try {
      await authApi.register(vals.username, vals.password);
      message.success("注册成功，请登录");
    } catch {
      /* noop */
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "linear-gradient(135deg,#1e3c72,#2a5298)",
      }}
    >
      <Card style={{ width: 420, boxShadow: "0 10px 40px rgba(0,0,0,0.25)" }}>
        <Typography.Title level={3} style={{ textAlign: "center", marginBottom: 8 }}>
          XBow CyberRange 靶场平台
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ textAlign: "center", marginBottom: 24 }}>
          容器化靶场管理与启动
        </Typography.Paragraph>
        <Tabs
          centered
          defaultActiveKey="login"
          items={[
            {
              key: "login",
              label: "登录",
              children: (
                <Form onFinish={onLogin} layout="vertical" size="large">
                  <Form.Item name="username" rules={[{ required: true, message: "请输入用户名" }]}>
                    <Input prefix={<UserOutlined />} placeholder="用户名" />
                  </Form.Item>
                  <Form.Item name="password" rules={[{ required: true, message: "请输入密码" }]}>
                    <Input.Password prefix={<LockOutlined />} placeholder="密码" />
                  </Form.Item>
                  <Typography.Link type="secondary" style={{ float: "right", fontSize: 12, marginBottom: 8 }}>
                    首次使用？默认管理员 admin / admin123
                  </Typography.Link>
                  <Form.Item style={{ marginBottom: 0 }}>
                    <Button type="primary" htmlType="submit" block>
                      登录
                    </Button>
                  </Form.Item>
                </Form>
              ),
            },
            ...(allowReg
              ? [
                  {
                    key: "register",
                    label: "注册",
                    children: (
                      <Form onFinish={onRegister} layout="vertical" size="large">
                        <Form.Item
                          name="username"
                          rules={[{ required: true, message: "请输入用户名" }, { min: 3, message: "至少 3 个字符" }]}
                        >
                          <Input prefix={<UserOutlined />} placeholder="用户名" />
                        </Form.Item>
                        <Form.Item
                          name="password"
                          rules={[{ required: true, message: "请输入密码" }, { min: 6, message: "至少 6 个字符" }]}
                        >
                          <Input.Password prefix={<LockOutlined />} placeholder="密码" />
                        </Form.Item>
                        <Form.Item style={{ marginBottom: 0 }}>
                          <Button type="primary" htmlType="submit" block>
                            注册
                          </Button>
                        </Form.Item>
                      </Form>
                    ),
                  },
                ]
              : []),
          ]}
          tabBarStyle={{ justifyContent: "center" }}
        />
        {!allowReg && (
          <Typography.Paragraph type="secondary" style={{ textAlign: "center", marginTop: 12 }}>
            注册功能已关闭，如需账号请联系管理员
          </Typography.Paragraph>
        )}
      </Card>
    </div>
  );
}
