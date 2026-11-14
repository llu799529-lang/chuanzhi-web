/**
 * MedTriage API 客户端：全前端唯一的请求出口（JSON、上传、SSE 都从这里拿头部与错误解析）。
 *
 * 后端所有错误都是 `{detail, code}`（见 backend/api/app.py）。这里把它变成 `ApiError`：
 *   - `code`        机器可读的错误码（UNAUTHORIZED / RATE_LIMITED / PAYLOAD_TOO_LARGE / UNAVAILABLE …）
 *   - `retryAfter`  429 时后端给的 Retry-After 秒数，页面可以据此倒计时
 * 以前 EyePage / LabPage / useAgentStream 各自 `fetch` + 各自解析错误，三处写法不同，
 * 而且没有一处处理「登录过期」：token 过期后页面只显示「未登录」，用户得自己去找退出按钮。
 * 现在任何非登录接口返回 401，都会触发 `setUnauthorizedHandler` 注册的处理器（main.ts：清登录态并跳登录页）。
 *
 * dev 模式走 Vite proxy（同源），生产构建后可用 VITE_API_BASE 指向后端绝对地址。
 */
import { useAuthStore } from "@/stores/auth";

const API_BASE: string = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfter: number | null;

  constructor(message: string, status: number, code = "", retryAfter: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  get isRateLimited(): boolean {
    return this.status === 429;
  }
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

/** 从失败的 Response 构造 ApiError。`detail` 不是字符串（比如旧版 422 的对象数组）时用兜底文案，不显示 [object Object]。 */
export async function errorFromResponse(resp: Response, fallback = "请求失败"): Promise<ApiError> {
  const data: unknown = await resp.json().catch(() => null);
  const detail = isRecord(data) && typeof data.detail === "string" && data.detail ? data.detail : `${fallback}（${resp.status}）`;
  const code = isRecord(data) && typeof data.code === "string" ? data.code : "";
  const ra = Number(resp.headers?.get?.("Retry-After"));
  return new ApiError(detail, resp.status, code, Number.isFinite(ra) && ra > 0 ? ra : null);
}

// ---------------------------------------------------------------- 登录过期
type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;

/** 由 main.ts 注册（需要 router 与 pinia 都就绪）。这里不直接 import router，避免循环依赖。 */
export function setUnauthorizedHandler(fn: UnauthorizedHandler | null): void {
  unauthorizedHandler = fn;
}

/** 登录 / 注册接口的 401 是「密码错了」，不是「登录过期」，不能把用户踢回登录页（他就在登录页）。 */
const AUTH_ENDPOINTS = ["/api/auth/login", "/api/auth/register", "/api/auth/logout"];

export function notifyIfUnauthorized(path: string, err: ApiError): void {
  if (err.isUnauthorized && !AUTH_ENDPOINTS.includes(path)) unauthorizedHandler?.();
}

// ---------------------------------------------------------------- 请求
export function authHeaders(): Record<string, string> {
  const auth = useAuthStore();
  return auth.token ? { Authorization: `Bearer ${auth.token}` } : {};
}

export interface ApiOptions extends Omit<RequestInit, "body"> {
  /** 普通对象自动 JSON 序列化，FormData / Blob 原样透传 */
  body?: unknown;
  /** 失败且后端没给 detail 时的提示前缀，如「分析失败」 */
  fallbackMessage?: string;
}

export async function api<T = unknown>(path: string, options: ApiOptions = {}): Promise<T> {
  const { fallbackMessage, ...init } = options;
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>), ...authHeaders() };
  let body = init.body as BodyInit | undefined;
  if (body && !(body instanceof FormData) && !(body instanceof Blob)) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }
  const resp = await fetch(API_BASE + path, { ...init, headers, body: body as BodyInit | undefined });
  if (!resp.ok) {
    const err = await errorFromResponse(resp, fallbackMessage);
    notifyIfUnauthorized(path, err);
    throw err;
  }
  return (await resp.json().catch(() => ({}))) as T;
}

/** 上传一个文件（字段名 file）。所有图片接口共用：眼底、化验单。 */
export function upload<T = unknown>(path: string, file: File, fallbackMessage = "上传失败"): Promise<T> {
  const fd = new FormData();
  fd.append("file", file, file.name);
  return api<T>(path, { method: "POST", body: fd, fallbackMessage });
}

export { API_BASE };

/** 读取同源静态文件为 File（如内置示例图）。失败抛 ApiError，调用方据此提示，而不是静默失败。 */
export async function fetchFile(path: string, name: string, type = "application/octet-stream"): Promise<File> {
  const resp = await fetch(path);
  if (!resp.ok) throw new ApiError(`文件加载失败（${resp.status}）`, resp.status);
  const blob = await resp.blob();
  return new File([blob], name, { type: blob.type || type });
}
