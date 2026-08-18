import { api } from "./client";
import type { QuotaStatusResponse } from "./types";

export const quotaApi = {
  mine: () => api.get<QuotaStatusResponse>("/users/me/quota"),
};
