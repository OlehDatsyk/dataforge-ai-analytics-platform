/** Backend client. It sends session cookies, the CSRF header, and the active workspace on every call. */

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const WORKSPACE_KEY = "dataforge.workspace";

function storageGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSet(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* Browser storage can be unavailable; the app still works without remembering this. */
  }
}

export const remember = { get: storageGet, set: storageSet };
export const getWorkspaceId = () => storageGet(WORKSPACE_KEY);
export const setWorkspaceId = (id: string | null) => storageSet(WORKSPACE_KEY, id);

function csrfToken(): string | null {
  const match = document.cookie.match(/(?:^|; )dataforge_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

function buildHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { ...extra };
  const token = csrfToken();
  if (token) headers["X-CSRF-Token"] = token;
  const workspace = getWorkspaceId();
  if (workspace) headers["X-Workspace-Id"] = workspace;
  return headers;
}

let onUnauthorised: (() => void) | null = null;
export const setUnauthorisedHandler = (handler: () => void) => {
  onUnauthorised = handler;
};

async function errorFrom(response: Response): Promise<ApiError> {
  let message = `The request failed (status ${response.status}).`;
  try {
    const body = await response.json();
    if (typeof body.detail === "string") message = body.detail;
  } catch {
    /* A non-JSON error body keeps the generic message. */
  }
  return new ApiError(response.status, message);
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api${url}`, {
    method,
    credentials: "same-origin",
    headers: buildHeaders(body !== undefined ? { "Content-Type": "application/json" } : undefined),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    if (response.status === 401 && !url.startsWith("/auth/login")) onUnauthorised?.();
    throw await errorFrom(response);
  }
  return response.json() as Promise<T>;
}

export const api = {
  get: <T,>(url: string) => request<T>("GET", url),
  post: <T,>(url: string, body?: unknown) => request<T>("POST", url, body ?? {}),
  patch: <T,>(url: string, body: unknown) => request<T>("PATCH", url, body),
  put: <T,>(url: string, body: unknown) => request<T>("PUT", url, body),
  delete: <T,>(url: string) => request<T>("DELETE", url),
};

/** Upload through XMLHttpRequest, which is what reports upload progress. */
export function uploadFile<T>(file: File, onProgress: (percent: number) => void, projectId?: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    if (projectId) form.append("project_id", projectId);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/datasets");
    Object.entries(buildHeaders()).forEach(([k, v]) => xhr.setRequestHeader(k, v));
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      let parsed: { detail?: string } = {};
      try {
        parsed = JSON.parse(xhr.responseText);
      } catch {
        /* handled by the status check below */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(parsed as T);
      else reject(new ApiError(xhr.status, parsed.detail ?? `Upload failed (status ${xhr.status}).`));
    };
    xhr.onerror = () => reject(new ApiError(0, "The upload was interrupted. Check your connection and try again."));
    xhr.send(form);
  });
}

function filenameFrom(response: Response, fallback: string): string {
  const match = response.headers.get("Content-Disposition")?.match(/filename="?([^";]+)"?/);
  return match ? match[1] : fallback;
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export async function download(url: string, fallback: string, body?: unknown): Promise<void> {
  const response = await fetch(`/api${url}`, {
    method: body !== undefined ? "POST" : "GET",
    credentials: "same-origin",
    headers: buildHeaders(body !== undefined ? { "Content-Type": "application/json" } : undefined),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw await errorFrom(response);
  saveBlob(await response.blob(), filenameFrom(response, fallback));
}
