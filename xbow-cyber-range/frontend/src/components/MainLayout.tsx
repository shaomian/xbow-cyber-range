import { Layout, Menu, Avatar, Dropdown, Space, Typography, theme } from "antd";
import {
  DashboardOutlined,
  AppstoreOutlined,
  ContainerOutlined,
  UserOutlined,
  SettingOutlined,
  LogoutOutlined,
  DesktopOutlined,
  RocketOutlined,
} from "@ant-design/icons";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { getUser, logout } from "../api/client";

const { Header, Sider, Content } = Layout;

export default function MainLayout() {
  const loc = useLocation();
  const nav = useNavigate();
  const user = getUser();
  const { token: themeToken } = theme.useToken();

  const items = [
    { key: "/", icon: <DashboardOutlined />, label: "仪表盘" },
    { key: "/benchmarks", icon: <RocketOutlined />, label: "靶场目录" },
    { key: "/templates", icon: <AppstoreOutlined />, label: "靶机模板" },
    { key: "/instances", icon: <ContainerOutlined />, label: "实例管理" },
    ...(user?.is_admin
      ? [
          { key: "/users", icon: <UserOutlined />, label: "用户管理" },
          { key: "/settings", icon: <SettingOutlined />, label: "系统设置" },
        ]
      : []),
  ];

  const selectedKey = (() => {
    if (loc.pathname.startsWith("/instances")) return "/instances";
    return loc.pathname;
  })();

  const userMenu = {
    items: [
      { key: "info", label: `用户：${user?.username ?? "-"}`, disabled: true },
      { type: "divider" as const },
      { key: "logout", icon: <LogoutOutlined />, label: "退出登录" },
    ],
    onClick: ({ key }: { key: string }) => {
      if (key === "logout") logout();
    },
  };

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider breakpoint="lg" collapsible theme="dark">
        <div style={{ height: 56, margin: 8, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <DesktopOutlined style={{ color: "#fff", fontSize: 22, marginRight: 8 }} />
          <Typography.Text strong style={{ color: "#fff", fontSize: 16 }}>
XBow CyberRange
           </Typography.Text>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          onClick={({ key }) => nav(key)}
          items={items}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: themeToken.colorBgContainer,
            padding: "0 24px",
            display: "flex",
            justifyContent: "flex-end",
            alignItems: "center",
            borderBottom: `1px solid ${themeToken.colorBorderSecondary}`,
          }}
        >
          <Dropdown menu={userMenu}>
            <Space style={{ cursor: "pointer" }}>
              <Avatar style={{ backgroundColor: themeToken.colorPrimary }} icon={<UserOutlined />} />
              <span>{user?.username}</span>
              {user?.is_admin && <Typography.Text type="secondary">管理员</Typography.Text>}
            </Space>
          </Dropdown>
        </Header>
        <Content style={{ padding: 24, background: themeToken.colorBgLayout }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
