import { createIdempotencyKey } from "./idempotency";

import type {
  AdminUser,
  ApiErrorBody,
  BoardMembershipAdmin,
  BoardSnapshot,
  BoardSummary,
  HealthDetail,
  NotificationRow,
  ReportSummary,
  Role,
  ScheduleOccurrencePreview,
  ScheduleRow,
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
    headers.set("Idempotency-Key", createIdempotencyKey());
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

export async function getBoards(includeAll = false): Promise<BoardSummary[]> {
  return request<BoardSummary[]>(includeAll ? "/api/v1/boards?all=1" : "/api/v1/boards");
}

export async function createBoard(name: string, managerUserIds: string[] = []): Promise<BoardSummary> {
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

export async function deleteBoard(
  boardId: string,
  confirmName: string,
): Promise<{ deleted: boolean; board_id: string; board_name: string }> {
  return request(
    `/api/v1/boards/${encodeURIComponent(boardId)}/delete`,
    {
      method: "POST",
      body: JSON.stringify({ confirm_name: confirmName }),
    },
    { idempotentMutation: true },
  );
}

export async function getBoardSnapshot(
  boardId: string,
  knownRevision?: number,
): Promise<BoardSnapshot | null> {
  const headers = new Headers({ Accept: "application/json" });
  if (knownRevision !== undefined) {
    headers.set("If-None-Match", `"board-${boardId}-${knownRevision}"`);
  }
  const response = await fetch(
    `/api/v1/boards/${encodeURIComponent(boardId)}/snapshot`,
    {
      credentials: "same-origin",
      headers,
    },
  );
  if (response.status === 304) {
    return null;
  }
  if (!response.ok) {
    throw new ApiError(
      response.status,
      await parseError(response),
      response.statusText || "Unable to load board",
    );
  }
  return (await response.json()) as BoardSnapshot;
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


export async function deleteTask(
  taskId: string,
  expectedVersion: number,
  expectedBoardRevision: number,
): Promise<{ deleted: boolean; task_id: string; board_id: string; board_revision: number }> {
  return request(
    `/api/v1/tasks/${encodeURIComponent(taskId)}/delete`,
    {
      method: "POST",
      body: JSON.stringify({
        expected_version: expectedVersion,
        expected_board_revision: expectedBoardRevision,
      }),
    },
    { idempotentMutation: true },
  );
}
export async function getAdminUsers(): Promise<AdminUser[]> {
  return request<AdminUser[]>("/api/v1/admin/users");
}

export async function createAdminUser(input: {
  username: string;
  temporary_password: string;
  is_admin: boolean;
  reason: string;
}): Promise<AdminUser> {
  return request<AdminUser>(
    "/api/v1/admin/users",
    {
      method: "POST",
      body: JSON.stringify(input),
    },
    { idempotentMutation: true },
  );
}

export async function commandAdminUser(
  userId: string,
  command: "reset_password" | "disable" | "enable" | "set_admin",
  payload: Record<string, unknown>,
): Promise<AdminUser> {
  return request<AdminUser>(
    `/api/v1/admin/users/${encodeURIComponent(userId)}/commands/${command}`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    { idempotentMutation: true },
  );
}

export async function getBoardMemberships(
  boardId: string,
): Promise<BoardMembershipAdmin[]> {
  return request<BoardMembershipAdmin[]>(
    `/api/v1/boards/${encodeURIComponent(boardId)}/memberships`,
  );
}

export async function addBoardMembership(
  boardId: string,
  userId: string,
  role: Role,
  reason: string,
): Promise<BoardMembershipAdmin> {
  return request<BoardMembershipAdmin>(
    `/api/v1/boards/${encodeURIComponent(boardId)}/memberships`,
    {
      method: "POST",
      body: JSON.stringify({
        user_id: userId,
        role,
        reason,
      }),
    },
    { idempotentMutation: true },
  );
}

export async function addBoardMembershipByUsername(
  boardId: string,
  username: string,
  role: Role,
): Promise<BoardMembershipAdmin> {
  return request<BoardMembershipAdmin>(
    `/api/v1/boards/${encodeURIComponent(boardId)}/memberships`,
    {
      method: "POST",
      body: JSON.stringify({
        username,
        role,
        reason: "Shared from board",
      }),
    },
    { idempotentMutation: true },
  );
}
export async function commandBoardMembership(
  boardId: string,
  userId: string,
  command: "set_role" | "remove",
  payload: Record<string, unknown>,
): Promise<BoardMembershipAdmin> {
  return request<BoardMembershipAdmin>(
    `/api/v1/boards/${encodeURIComponent(boardId)}/memberships/${encodeURIComponent(
      userId,
    )}/commands/${command}`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    { idempotentMutation: true },
  );
}

export async function getNotifications(unreadOnly = false): Promise<NotificationRow[]> {
  return request<NotificationRow[]>(
    `/api/v1/notifications${unreadOnly ? "?unread=1" : ""}`,
  );
}

export async function markNotificationRead(id: string): Promise<NotificationRow> {
  return request<NotificationRow>(
    `/api/v1/notifications/${encodeURIComponent(id)}/read`,
    { method: "POST", body: JSON.stringify({}) },
    { idempotentMutation: true },
  );
}

export async function getReports(): Promise<ReportSummary[]> {
  return request<ReportSummary[]>("/api/v1/reports");
}

export async function createReport(reportDate: string): Promise<ReportSummary> {
  return request<ReportSummary>(
    "/api/v1/reports",
    {
      method: "POST",
      body: JSON.stringify({ report_date: reportDate }),
    },
    { idempotentMutation: true },
  );
}

export async function getReport(id: string): Promise<ReportSummary> {
  return request<ReportSummary>(
    `/api/v1/reports/${encodeURIComponent(id)}`,
  );
}

export async function getSchedules(boardId?: string): Promise<ScheduleRow[]> {
  const query = boardId ? `?board=${encodeURIComponent(boardId)}` : "";
  return request<ScheduleRow[]>(`/api/v1/schedules${query}`);
}

export async function createSchedule(input: {
  board_id: string;
  name: string;
  timezone: string;
}): Promise<ScheduleRow> {
  return request<ScheduleRow>(
    "/api/v1/schedules",
    {
      method: "POST",
      body: JSON.stringify(input),
    },
    { idempotentMutation: true },
  );
}

export async function previewSchedule(input: {
  board_id: string;
  rule: Record<string, unknown>;
  after: string;
  pauses?: Array<Record<string, unknown>>;
}): Promise<ScheduleOccurrencePreview[]> {
  const result = await request<{ occurrences: ScheduleOccurrencePreview[] }>(
    "/api/v1/schedules/preview",
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
  return result.occurrences;
}

export async function commandSchedule(
  scheduleId: string,
  command: "publish" | "revise" | "pause" | "resume",
  payload: Record<string, unknown>,
): Promise<ScheduleRow> {
  return request<ScheduleRow>(
    `/api/v1/schedules/${encodeURIComponent(scheduleId)}/commands/${command}`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    { idempotentMutation: true },
  );
}

export async function getHealthDetail(): Promise<HealthDetail> {
  return request<HealthDetail>("/api/v1/health/detail");
}
