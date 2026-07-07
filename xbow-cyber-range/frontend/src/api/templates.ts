import { http } from "./client";

export interface Template {
  id: number;
  name: string;
  image: string;
  description: string;
  command: string;
  entrypoint: string;
  env: string[];
  exposed_ports: number[];
  privileged: boolean;
  memory_limit_mb: number;
  cpu_quota: number;
  tags: string;
  is_public: boolean;
  created_at: string;
}

export interface TemplateInput {
  name: string;
  image: string;
  description: string;
  command: string;
  entrypoint: string;
  env: string[];
  exposed_ports: number[];
  privileged: boolean;
  memory_limit_mb: number;
  cpu_quota: number;
  tags: string;
  is_public: boolean;
}

export const templatesApi = {
  list: () => http.get<Template[]>("/templates").then((r) => r.data),
  create: (payload: TemplateInput) => http.post<Template>("/templates", payload).then((r) => r.data),
  update: (id: number, payload: TemplateInput) => http.put<Template>(`/templates/${id}`, payload).then((r) => r.data),
  remove: (id: number) => http.delete(`/templates/${id}`).then((r) => r.data),
  images: () => http.get<{ id: string; tags: string[]; size_mb: number }[]>("/templates/images").then((r) => r.data),
};
