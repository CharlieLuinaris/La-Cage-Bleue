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

const API_BASE = (import.meta.env.BASE_URL || "/").replace(/\/+$/, "");

export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(API_BASE + path, init);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(String(payload?.message || payload?.error || `HTTP ${response.status}`), response.status, payload);
  }
  return payload as T;
}
