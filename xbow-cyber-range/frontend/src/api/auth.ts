import { http } from "./client";

export interface UserOut {
  id: number;
  username: string;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
}

export interface TokenOut {
  access_token: string;
  token_type: string;
  is_admin: boolean;
  username: string;
}

export const authApi = {
  login: (username: string, password: string) =>
    http.post<TokenOut>("/auth/login", { username, password }).then((r) => r.data),
  register: (username: string, password: string) =>
    http.post<UserOut>("/auth/register", { username, password }).then((r) => r.data),
  me: () => http.get<UserOut>("/auth/me").then((r) => r.data),
  registrationStatus: () => http.get<{ allow_registration: boolean }>("/auth/registration-status").then((r) => r.data),
  changePassword: (old_password: string, new_password: string) =>
    http.post(`/auth/change-password?old_password=${encodeURIComponent(old_password)}&new_password=${encodeURIComponent(new_password)}`).then((r) => r.data),
};

export const usersApi = {
  list: () => http.get<UserOut[]>("/users").then((r) => r.data),
  update: (id: number, payload: Partial<{ is_admin: boolean; is_active: boolean; password: string }>) =>
    http.patch<UserOut>(`/users/${id}`, payload).then((r) => r.data),
  remove: (id: number) => http.delete(`/users/${id}`).then((r) => r.data),
};
