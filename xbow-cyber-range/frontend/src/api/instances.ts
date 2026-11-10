import { http } from "./client";

export interface InstanceOut {
  id: number;
  container_id: string;
  name: string;
  user_id: number;
  template_id: number | null;
  image: string;
  status: string;
  ports: Record<string, number>;
  host: string;
  expires_at: string | null;
  started_at: string | null;
  stopped_at: string | null;
  last_error: string;
  auto_remove: boolean;
  remaining_seconds: number | null;
  renewed?: boolean | null;
  kind: string;
  project_name: string | null;
  benchmark_id: string | null;
  flag: string | null;
  compose_services?: string[];
}

export interface InstanceStartInput {
  template_id?: number | null;
  name?: string;
  image?: string;
  command?: string;
  env?: string[];
  exposed_ports?: number[];
  privileged?: boolean;
  timeout_seconds?: number;
  auto_remove?: boolean;
}

export type InstanceStatusFilter = "active" | "stopped" | "removed" | "all";

export const instancesApi = {
  // status 为空 = 默认视图（全部，不含已删除）
  list: (status?: InstanceStatusFilter) =>
    http.get<InstanceOut[]>("/instances", { params: status ? { status } : undefined }).then((r) => r.data),
  get: (id: number) => http.get<InstanceOut>(`/instances/${id}`).then((r) => r.data),
  start: (payload: InstanceStartInput) => http.post<InstanceOut>("/instances", payload).then((r) => r.data),
  // stop：compose 栈停止后端最长约 120s，超过全局 30s 上限，故放宽请求超时
  stop: (id: number, timeout = 10) =>
    http.post<InstanceOut>(`/instances/${id}/stop`, null, { params: { timeout }, timeout: 180000 }).then((r) => r.data),
  // startExisting：compose up --wait 后端最长 600s（镜像可能需重建），放宽请求超时避免前端先超时报假错
  startExisting: (id: number, timeout_seconds?: number) =>
    http.post<InstanceOut>(
      `/instances/${id}/start`,
      null,
      { params: timeout_seconds ? { timeout_seconds } : undefined, timeout: 660000 }
    ).then((r) => r.data),
  restart: (id: number, timeout = 10) => http.post<InstanceOut>(`/instances/${id}/restart`, null, { params: { timeout } }).then((r) => r.data),
  remove: (id: number, force = true) => http.delete(`/instances/${id}`, { params: { force } }).then((r) => r.data),
  purge: (id: number) => http.delete(`/instances/${id}/purge`).then((r) => r.data),
  purgeRemoved: () => http.post<{ message: string }>("/instances/purge-removed").then((r) => r.data),
  extend: (id: number, add_seconds: number) => http.post<InstanceOut>(`/instances/${id}/extend`, { add_seconds }).then((r) => r.data),
  setTimeout: (id: number, timeout_seconds: number) => http.put<InstanceOut>(`/instances/${id}/timeout`, { timeout_seconds }).then((r) => r.data),
  logs: (id: number, tail = 500) => http.get<{ logs: string }>(`/instances/${id}/logs`, { params: { tail } }).then((r) => r.data),
};

export interface SnapshotOut {
  id: number;
  instance_id: number;
  image_id: string;
  image_tag: string;
  note: string;
  created_at: string;
}

export const snapshotsApi = {
  list: (instanceId: number) => http.get<SnapshotOut[]>(`/instances/${instanceId}/snapshots`).then((r) => r.data),
  create: (instanceId: number, image_tag: string, note: string) =>
    http.post<SnapshotOut>(`/instances/${instanceId}/snapshots`, { image_tag, note }).then((r) => r.data),
  remove: (instanceId: number, id: number) => http.delete(`/instances/${instanceId}/snapshots/${id}`).then((r) => r.data),
};
