// Thin fetch wrapper. Cookie auth is automatic (same-origin), so we just
// need to send credentials and parse JSON. Errors throw with a typed shape.

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown
): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return undefined as T;
  const contentType = res.headers.get("content-type") ?? "";
  const data = contentType.includes("application/json")
    ? await res.json()
    : await res.text();
  if (!res.ok) {
    const detail =
      typeof data === "object" && data !== null && "detail" in (data as object)
        ? String((data as { detail: unknown }).detail)
        : String(data);
    throw new ApiError(res.status, detail, data);
  }
  return data as T;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, body?: unknown) => request<T>("POST", p, body),
  patch: <T>(p: string, body?: unknown) => request<T>("PATCH", p, body),
  del: <T>(p: string) => request<T>("DELETE", p),
};
