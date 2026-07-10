import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { ConfigProvider, App as AntdApp } from "antd";
import zhCN from "antd/locale/zh_CN";
import "antd/dist/reset.css";
import "@xterm/xterm/css/xterm.css";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: "#1677ff" } }}>
    <AntdApp>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </AntdApp>
  </ConfigProvider>
);
