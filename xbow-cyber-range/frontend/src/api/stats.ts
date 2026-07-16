import { http } from "./client";

export interface ContainerStats {
  instance_id: number;
  container_id: string;
  name: string;
  cpu_percent: number;
  memory_used_mb: number;
  memory_limit_mb: number;
  net_rx_kb: number;
  net_tx_kb: number;
  status: string;
}

export interface SystemStats {
  cpu_percent: number;
  memory_percent: number;
  memory_total_gb: number;
  disk_percent: number;
  containers_total: number;
  containers_running: number;
}

export const statsApi = {
  system: () => http.get<SystemStats>("/stats/system").then((r) => r.data),
  instances: () => http.get<ContainerStats[]>("/stats/instances").then((r) => r.data),
  instance: (id: number) => http.get<ContainerStats>(`/stats/instances/${id}`).then((r) => r.data),
};

export interface PlatformSettings {
  port_range_start: number;
  port_range_end: number;
  default_instance_timeout: number;
  max_instance_timeout: number;
  docker_host: string;
  terminal_default_command: string;
  reaper_interval_seconds: number;
  benchmarks_root: string;
  allow_registration: boolean;
}

export const settingsApi = {
  get: () => http.get<PlatformSettings>("/settings").then((r) => r.data),
  update: (payload: Partial<PlatformSettings>) => http.put<PlatformSettings>("/settings", payload).then((r) => r.data),
};
