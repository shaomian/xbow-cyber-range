import axios, { AxiosError } from "axios";
import { message } from "antd";

export const TOKEN_KEY = "xbow_cyber_range_token";
export const USER_KEY = "xbow_cyber_range_user";

export const http = axios.create({
  baseURL: "/api",
  timeout: 30000,
});

http.interceptors.request.use((cfg) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) cfg.headers.Authorization = `Bearer ${token}`;
  return cfg;
});

http.interceptors.response.use(
  (res) => res,
  (err: AxiosError<{ detail?: string | { msg: string }[] }>) => {
    let msg = "请求失败";
    if (err.response?.data) {
      const d = err.response.data.detail;
      if (typeof d === "string") msg = d;
      else if (Array.isArray(d)) msg = d.map((x) => x.msg).join("; ");
    } else if (err.message) {
      msg = err.message;
    }
    if (err.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
      if (!location.pathname.startsWith("/login")) {
        message.error("登录已过期，请重新登录");
        setTimeout(() => (location.href = "/login"), 600);
      }
    } else {
      message.error(msg);
    }
    return Promise.reject(err);
  }
);

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setAuth(token: string, user: { username: string; is_admin: boolean }) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getUser(): { username: string; is_admin: boolean } | null {
  const raw = localStorage.getItem(USER_KEY);
  return raw ? JSON.parse(raw) : null;
}

export function logout() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  location.href = "/login";
}

export function wsUrl(path: string): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}${path}?token=${getToken() ?? ""}`;
}
