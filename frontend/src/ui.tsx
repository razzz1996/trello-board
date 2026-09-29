import type { ReactNode } from "react";

import type { Task } from "./types";

export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "Unexpected error.";
}

export function stars(priority: number): string {
  return "★".repeat(priority);
}

export function taskStateLabel(state: string): string {
  const labels: Record<string, string> = {
    BACKLOG: "Inbox",
    TODO: "To Do",
    IN_PROGRESS: "In Progress",
    BLOCKED: "Later",
    REVIEW: "Review",
    DONE: "Done",
  };
  return labels[state] ?? state.replaceAll("_", " ");
}

export function taskDue(task: Task): string | null {
  return task.current_commitment?.due_at ?? task.draft_due_at;
}

export function formatDateTime(value: string | null): string {
  if (!value) return "No deadline";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

export function isOverdue(task: Task): boolean {  const due = taskDue(task);
  if (!due || task.column_state === "DONE" || task.column_state === "REVIEW") return false;
  return new Date(due).valueOf() < Date.now();
}

export function Alert({
  kind = "error",
  children,
}: {
  kind?: "error" | "info" | "success";
  children: ReactNode;
}) {
  return (
    <div className={`alert alert--${kind}`} role={kind === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}

export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="modal__header">
          <h2>{title}</h2>
          <button className="button button--ghost" type="button" onClick={onClose}>
            Close
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}

export function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "danger";
}) {
  return (
    <div className={`metric ${tone === "danger" ? "metric--danger" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
