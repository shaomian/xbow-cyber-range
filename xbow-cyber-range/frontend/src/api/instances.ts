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
  kind: string;
  project_name: string | null;
  benchmark_id: string | null;
  flag: string | null;
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

export const instancesApi = {
  list: (only_active = false, include_removed = false) =>
    http.get<InstanceOut[]>("/instances", { params: { only_active, include_removed } }).then((r) => r.data),
  get: (id: number) => http.get<InstanceOut>(`/instances/${id}`).then((r) => r.data),
  start: (payload: InstanceStartInput) => http.post<InstanceOut>("/instances", payload).then((r) => r.data),
  stop: (id: number, timeout = 10) => http.post<InstanceOut>(`/instances/${id}/stop`, null, { params: { timeout } }).then((r) => r.data),
  startExisting: (id: number) => http.post<InstanceOut>(`/instances/${id}/start`).then((r) => r.data),
  restart: (id: number, timeout = 10) => http.post<InstanceOut>(`/instances/${id}/restart`, null, { params: { timeout } }).then((r) => r.data),
  remove: (id: number, force = true) => http.delete(`/instances/${id}`, { params: { force } }).then((r) => r.data),
  purge: (id: number) => http.delete(`/instances/${id}/purge`).then((r) => r.data),
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
