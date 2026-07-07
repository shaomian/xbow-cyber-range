import { http } from "./client";
import type { InstanceOut } from "./instances";

export interface BenchmarkService {
  name: string;
  ports: { host: number | null; container: number; proto: string }[];
  has_build: boolean;
}

export interface BenchmarkOut {
  id: string;
  name: string;
  description: string;
  win_condition: string;
  dir: string;
  has_compose: boolean;
  has_makefile: boolean;
  services: BenchmarkService[];
  host_ports: number[];
  env_flag: string | null;
  computed_flag: string;
  running: boolean;
  instance_id: number | null;
}

export const benchmarksApi = {
  list: () => http.get<BenchmarkOut[]>("/benchmarks").then((r) => r.data),
  get: (id: string) => http.get<BenchmarkOut>(`/benchmarks/${id}`).then((r) => r.data),
  launch: (id: string, timeout_seconds?: number) =>
    http.post<InstanceOut>(`/benchmarks/${id}/launch`, { timeout_seconds }).then((r) => r.data),
};
