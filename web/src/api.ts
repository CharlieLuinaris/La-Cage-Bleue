export class ApiError extends Error {
  status: number;
  payload: any;

  constructor(message: string, status: number, payload: any) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

// 部署在子路径（如 Aubade 的 /cage/）时，API 请求必须带上同样的前缀才能走到反代。
const API_BASE = (import.meta.env.BASE_URL || "/").replace(/\/$/, "");

export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(API_BASE + path, init);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(String(payload?.message || payload?.error || `HTTP ${response.status}`), response.status, payload);
  }
  return payload as T;
}
