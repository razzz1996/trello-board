export type Role = "MEMBER" | "MANAGER";
export type TaskState = "BACKLOG" | "TODO" | "IN_PROGRESS" | "BLOCKED" | "REVIEW" | "DONE";

export interface SessionUser {
  id: string;
  username: string;
  force_password_change: boolean;
  is_admin: boolean;
  session_generation: number;
}

export interface BoardSummary {
  id: string;
  name: string;
  revision: number;
  archived: boolean;
}

export interface BoardMember {
  id: string;
  username: string;
  role: Role;
}

export interface ChecklistItem {
  id: string;
  text: string;
  required: boolean;
  position: number;
  checked: boolean;
  updated_at: string;
}

export interface Commitment {
  id: string;
  revision: number;
  owner_id: string;
  due_at: string;
  priority: number;
  acceptance_criteria: string;
  required_checklist_snapshot: Array<Record<string, unknown>>;
  reason: string;
  created_at: string;
}

export interface Review {
  id: string;
  reviewer_id: string;
  decision: "ACCEPTED" | "REJECTED";
  feedback: string;
  reviewed_at: string;
}

export interface Submission {
  id: string;
  commitment_id: string;
  accountable_owner_id: string;
  submitting_actor_id: string;
  result_summary: string;
  evidence_links: string[];
  target_value: string | null;
  actual_value: string | null;
  unit: string;
  submitted_at: string;
  is_current: boolean;
  review: Review | null;
}

export interface Task {
  id: string;
  board_id: string;
  column_id: string;
  column_state: TaskState;
  title: string;
  description: string;
  priority: 1 | 2 | 3;
  current_owner_id: string | null;
  original_owner_id: string | null;
  row_version: number;
  position: number;
  draft_due_at: string | null;
  draft_acceptance_criteria: string;
  committed_at: string | null;
  current_commitment: Commitment | null;
  is_cancelled: boolean;
  cancelled_at: string | null;
  cancelled_reason: string;
  checklist_items: ChecklistItem[];
  submissions: Submission[];
  created_at: string;
  updated_at: string;
}

export interface BoardColumn {
  id: string;
  state: TaskState;
  name: string;
  position: number;
  tasks: Task[];
}

export interface BoardSnapshot {
  board: BoardSummary;
  membership: { role: Role };
  members: BoardMember[];
  revision: number;
  columns: BoardColumn[];
}

export interface ApiErrorBody {
  code: string;
  message: string;
  field_errors: Record<string, string[]>;
  request_id: string | null;
}
