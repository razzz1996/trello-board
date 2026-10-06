export type Role = "MEMBER" | "MANAGER";
export type TaskState =
  | "BACKLOG"
  | "TODO"
  | "IN_PROGRESS"
  | "BLOCKED"
  | "REVIEW"
  | "DONE"
  | `CUSTOM_${string}`;
export type RecurrenceFrequency = "NONE" | "DAILY" | "WEEKLY" | "MONTHLY";

export interface SessionUser {
  id: string;
  username: string;
  force_password_change: boolean;
  is_admin: boolean;
  session_generation: number;
}

export interface AdminUser extends SessionUser {
  is_active: boolean;
  disabled_at: string | null;
  slack_destination_generation: number;
  slack_verified: boolean;
}

export interface BoardMembershipAdmin {
  user_id: string;
  username: string;
  role: Role;
  is_active: boolean;
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

export interface CommentEditHistory {
  id: string;
  editor_id: string;
  previous_body: string;
  replacement_body: string;
  edited_at: string;
}

export interface Comment {
  id: string;
  author_id: string;
  author_username: string;
  body: string;
  created_at: string;
  corrected_at: string | null;
  history: CommentEditHistory[];
}

export interface ChangeProposal {
  id: string;
  proposer_id: string;
  proposed_changes: Record<string, unknown>;
  reason: string;
  status: "PENDING" | "ACCEPTED" | "DECLINED";
  resolved_by_id: string | null;
  resolution_reason: string;
  created_at: string;
  resolved_at: string | null;
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
  column_name: string;
  title: string;
  description: string;
  priority: 1 | 2 | 3;
  current_owner_id: string | null;
  original_owner_id: string | null;
  row_version: number;
  position: number;
  draft_due_at: string | null;
  draft_acceptance_criteria: string;
  recurrence_frequency: RecurrenceFrequency;
  recurrence_next_at: string | null;
  recurrence_last_triggered_at: string | null;
  recurrence_generation: number;
  committed_at: string | null;
  current_commitment: Commitment | null;
  is_cancelled: boolean;
  cancelled_at: string | null;
  cancelled_reason: string;
  checklist_items: ChecklistItem[];
  comments: Comment[];
  change_proposals: ChangeProposal[];
  submissions: Submission[];
  created_at: string;
  updated_at: string;
}

export interface BoardColumn {
  id: string;
  state: TaskState;
  name: string;
  position: number;
  is_custom: boolean;
  tasks: Task[];
}

export interface BoardSnapshot {
  board: BoardSummary;
  membership: { role: Role };
  members: BoardMember[];
  revision: number;
  columns: BoardColumn[];
}

export interface NotificationRow {
  id: string;
  kind: string;
  task_id: string | null;
  report_id: string | null;
  scheduled_for: string;
  observed_at: string | null;
  status: string;
  message: string;
  read_at: string | null;
}

export interface ReportSummary {
  id: string;
  report_date: string;
  scheduled_for: string;
  observation_started_at: string;
  generated_at: string;
  timezone: string;
  definition_version: number;
  generation: number;
  delayed: boolean;
  metrics: Record<string, unknown>;
  scope_board_ids: string[];
  rows?: Array<Record<string, unknown>>;
}

export interface ScheduleRevision {
  id: string;
  revision: number;
  rule: Record<string, unknown>;
  template_fields: Record<string, unknown>;
  effective_base_period: string;
  reason: string;
  published_at: string;
}

export interface ScheduleRow {
  id: string;
  board_id: string;
  name: string;
  timezone: string;
  active: boolean;
  generation: number;
  cursor_period_key: string;
  current_revision: ScheduleRevision | null;
  paused: boolean;
}

export interface ScheduleOccurrencePreview {
  period_key: string;
  base_release_date: string;
  adjusted_release_date: string;
  adjusted_due_date: string;
  release_at: string;
  due_at: string;
  explanations: string[];
}

export interface ApiErrorBody {
  code: string;
  message: string;
  field_errors: Record<string, string[]>;
  request_id: string | null;
}


export interface HealthDetail {
  observed_at: string;
  heartbeats: Record<
    string,
    {
      last_seen_at: string | null;
      age_seconds: number | null;
      stale: boolean;
    }
  >;
  queue: {
    oldest_ready_age_seconds: number;
    failed: number;
    unknown: number;
  };
  disk: {
    free_bytes: number;
    total_bytes: number;
    free_percent: number;
  };
  backup: {
    status: string;
    age_hours: number | null;
  };
  warnings: string[];
}
