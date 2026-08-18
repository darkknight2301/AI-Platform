import { api, setToken } from "./client";
import type { TokenResponse, UserPublic } from "./types";

export const authApi = {
  register: (input: { username: string; email: string; password: string; group_id?: string | null }) =>
    api.post<UserPublic>("/auth/register", input),

  login: async (input: { username_or_email: string; password: string }) => {
    const result = await api.post<TokenResponse>("/auth/login", input);
    setToken(result.access_token);
    return result;
  },

  logout: async () => {
    try {
      await api.post<void>("/auth/logout");
    } finally {
      setToken(null);
    }
  },

  me: () => api.get<UserPublic>("/auth/me"),
};
