import type {
  ApiErrorBody,
  BoardSnapshot,
  BoardSummary,
  SessionUser,
  Task,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly body: ApiErrorBody | null;

  constructor(status: number, body: ApiErrorBody | null, fallback: string) {
    super(body?.message ?? fallback);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

function cookie(name: string): string | null {
  const prefix = encodeURIComponent(name) + "=";
  for (const part of document.cookie.split(";")) {
    const value = part.trim();
    if (value.startsWith(prefix)) {
      return decodeURIComponent(value.slice(prefix.length));
    }
  }
  return null;
}

async function parseError(response: Response): Promise<ApiErrorBody | null> {
  try {
    const value: unknown = await response.json();
    if (
      typeof value === "object" &&
      value !== null &&
      "message" in value &&
      typeof (value as { message?: unknown }).message === "string"
    ) {
      return value as ApiErrorBody;
    }
  } catch {
    // The server may intentionally return an empty 401/403/500 response.
  }
  return null;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  options: { idempotentMutation?: boolean } = {},
): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");

  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = cookie("csrftoken");
    if (!csrf) {
      await bootstrapCsrf();
    }
    const refreshed = cookie("csrftoken");
    if (!refreshed) {
      throw new Error("CSRF token is unavailable.");
    }
    headers.set("X-CSRFToken", refreshed);
  }

  if (options.idempotentMutation) {
    headers.set("Idempotency-Key", crypto.randomUUID());
  }

  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers,
  });

  if (!response.ok) {
    const body = await parseError(response);
    throw new ApiError(response.status, body, response.statusText || "Request failed");
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function bootstrapCsrf(): Promise<void> {
  const response = await fetch("/api/v1/session/csrf/", {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new ApiError(response.status, await parseError(response), "Unable to initialize session");
  }
}

export async function getSessionUser(): Promise<SessionUser> {
  return request<SessionUser>("/api/v1/session/me/");
}

export async function login(username: string, password: string): Promise<SessionUser> {
  return request<SessionUser>("/api/v1/session/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function logout(): Promise<void> {
  return request<void>("/api/v1/session/logout", { method: "POST" });
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<SessionUser> {
  return request<SessionUser>("/api/v1/session/password-change", {
    method: "POST",
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
}

export async function getBoards(): Promise<BoardSummary[]> {
  return request<BoardSummary[]>("/api/v1/boards");
}

export async function createBoard(name: string, managerUserIds: string[]): Promise<BoardSummary> {
  return request<BoardSummary>(
    "/api/v1/boards",
    {
      method: "POST",
      body: JSON.stringify({
        name,
        manager_user_ids: managerUserIds,
      }),
    },
    { idempotentMutation: true },
  );
}

export async function getBoardSnapshot(boardId: string): Promise<BoardSnapshot> {
  return request<BoardSnapshot>(`/api/v1/boards/${encodeURIComponent(boardId)}/snapshot`);
}

export async function getTasks(query = ""): Promise<Task[]> {
  return request<Task[]>(`/api/v1/tasks${query ? `?${query}` : ""}`);
}

export async function createTask(input: {
  board_id: string;
  title: string;
  description?: string;
  priority: number;
  owner_id?: string | null;
  draft_due_at?: string | null;
  draft_acceptance_criteria?: string;
}): Promise<Task> {
  return request<Task>(
    "/api/v1/tasks",
    {
      method: "POST",
      body: JSON.stringify(input),
    },
    { idempotentMutation: true },
  );
}

export async function commandTask(
  taskId: string,
  command: string,
  payload: Record<string, unknown>,
): Promise<Task> {
  return request<Task>(
    `/api/v1/tasks/${encodeURIComponent(taskId)}/commands/${encodeURIComponent(command)}`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    { idempotentMutation: true },
  );
}
