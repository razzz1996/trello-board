import { type FormEvent, useState } from "react";

import { commandTask, createTask } from "./api";
import { TaskWorkspaceExtras } from "./TaskWorkspaceExtras";
import type { BoardSnapshot, SessionUser, Task } from "./types";
import { Alert, errorMessage, formatDateTime, isOverdue, Modal, stars, taskDue } from "./ui";

export function CreateTaskButton({
  snapshot,
  user,
  onChanged,
}: {
  snapshot: BoardSnapshot;
  user: SessionUser;
  onChanged: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState(1);
  const [due, setDue] = useState("");
  const [criteria, setCriteria] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (priority === 3 && !due) {
      setError("Three-star drafts require a deadline.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await createTask({
        board_id: snapshot.board.id,
        title,
        priority,
        owner_id: user.id,
        draft_due_at: due ? new Date(due).toISOString() : null,
        draft_acceptance_criteria: criteria,
      });
      setTitle("");
      setPriority(1);
      setDue("");
      setCriteria("");
      setOpen(false);
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button className="button button--primary" type="button" onClick={() => setOpen(true)}>
        + Add card
      </button>
    );
  }

  return (
    <Modal title="Create draft card" onClose={() => setOpen(false)}>
      {error && <Alert>{error}</Alert>}
      <form className="stack" onSubmit={submit}>
        <label>Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} required />
        </label>
        <label>Priority
          <select value={priority} onChange={(e) => setPriority(Number(e.target.value))}>
            <option value={1}>★ — Can wait</option>
            <option value={2}>★★ — Average</option>
            <option value={3}>★★★ — Main priority</option>
          </select>
        </label>
        <label>Draft deadline
          <input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} />
        </label>
        <label>Draft acceptance criteria
          <textarea value={criteria} onChange={(e) => setCriteria(e.target.value)} rows={4} />
        </label>
        <div className="modal__actions">
          <button className="button button--ghost" type="button" onClick={() => setOpen(false)}>Cancel</button>
          <button className="button button--primary" disabled={busy}>
            {busy ? "Creating…" : "Create draft"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function CommitModal({
  task,
  snapshot,
  onClose,
  onChanged,
}: {
  task: Task;
  snapshot: BoardSnapshot;
  onClose: () => void;
  onChanged: () => Promise<void>;
}) {
  const [ownerId, setOwnerId] = useState(task.current_owner_id ?? snapshot.members[0]?.id ?? "");
  const [due, setDue] = useState(task.draft_due_at ? new Date(task.draft_due_at).toISOString().slice(0, 16) : "");
  const [criteria, setCriteria] = useState(task.draft_acceptance_criteria ?? "");
  const [reason, setReason] = useState("Initial commitment");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await commandTask(task.id, "commit_task", {
        expected_version: task.row_version,
        expected_board_revision: snapshot.revision,
        owner_id: ownerId,
        due_at: new Date(due).toISOString(),
        acceptance_criteria: criteria,
        reason,
      });
      await onChanged();
      onClose();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Commit task" onClose={onClose}>
      <p className="muted">This freezes the original owner, deadline, stars, criteria, and checklist baseline.</p>
      {error && <Alert>{error}</Alert>}
      <form className="stack" onSubmit={submit}>
        <label>Accountable owner
          <select value={ownerId} onChange={(e) => setOwnerId(e.target.value)} required>
            <option value="">Select owner</option>
            {snapshot.members.map((member) => (
              <option key={member.id} value={member.id}>{member.username} · {member.role.toLowerCase()}</option>
            ))}
          </select>
        </label>
        <label>Deadline
          <input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} required />
        </label>
        <label>Measurable acceptance criteria
          <textarea value={criteria} onChange={(e) => setCriteria(e.target.value)} rows={5} required />
        </label>
        <label>Reason
          <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000} required />
        </label>
        <div className="modal__actions">
          <button className="button button--ghost" type="button" onClick={onClose}>Cancel</button>
          <button className="button button--primary" disabled={busy}>
            {busy ? "Committing…" : "Commit to To Do"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function SubmitModal({
  task,
  snapshot,
  onClose,
  onChanged,
}: {
  task: Task;
  snapshot: BoardSnapshot;
  onClose: () => void;
  onChanged: () => Promise<void>;
}) {
  const [summary, setSummary] = useState("");
  const [evidence, setEvidence] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const links = evidence.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
    setBusy(true);
    setError("");
    try {
      await commandTask(task.id, "submit_result", {
        expected_version: task.row_version,
        expected_board_revision: snapshot.revision,
        result_summary: summary,
        evidence_links: links,
      });
      await onChanged();
      onClose();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Submit result for review" onClose={onClose}>
      {error && <Alert>{error}</Alert>}
      <form className="stack" onSubmit={submit}>
        <label>Result summary
          <textarea rows={5} value={summary} onChange={(e) => setSummary(e.target.value)} required />
        </label>
        <label>Evidence links
          <textarea rows={4} value={evidence} onChange={(e) => setEvidence(e.target.value)}
            placeholder={"https://…\nhttps://…"} required />
          <span className="field-help">One http/https link per line. The server never fetches them.</span>
        </label>
        <div className="modal__actions">
          <button className="button button--ghost" type="button" onClick={onClose}>Cancel</button>
          <button className="button button--primary" disabled={busy}>
            {busy ? "Submitting…" : "Submit to Review"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function ReviewModal({
  task,
  snapshot,
  onClose,
  onChanged,
}: {
  task: Task;
  snapshot: BoardSnapshot;
  onClose: () => void;
  onChanged: () => Promise<void>;
}) {
  const current = task.submissions.find((item) => item.is_current);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function decide(decision: "ACCEPTED" | "REJECTED") {
    setBusy(true);
    setError("");
    try {
      await commandTask(task.id, "review_submission", {
        expected_version: task.row_version,
        expected_board_revision: snapshot.revision,
        decision,
        feedback,
      });
      await onChanged();
      onClose();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Review submitted result" onClose={onClose}>
      {error && <Alert>{error}</Alert>}
      {!current ? <Alert>This task has no current submission.</Alert> : (
        <>
          <dl className="detail-grid">
            <dt>Submitted</dt><dd>{formatDateTime(current.submitted_at)}</dd>
            <dt>Result</dt><dd>{current.result_summary}</dd>
            <dt>Evidence</dt><dd>{current.evidence_links.map((link) => (
              <div key={link}><a href={link} target="_blank" rel="noreferrer noopener">{link}</a></div>
            ))}</dd>
          </dl>
          <label>Review feedback
            <textarea rows={4} value={feedback} onChange={(e) => setFeedback(e.target.value)} />
          </label>
          <div className="modal__actions modal__actions--spread">
            <button className="button button--danger" type="button"
              onClick={() => void decide("REJECTED")} disabled={busy}>Reject</button>
            <button className="button button--success" type="button"
              onClick={() => void decide("ACCEPTED")} disabled={busy}>Accept → Done</button>
          </div>
        </>
      )}
    </Modal>
  );
}

export function TaskDetailModal({
  task,
  snapshot,
  currentUser,
  onClose,
  onChanged,
  onSubmit,
  onReview,
}: {
  task: Task;
  snapshot: BoardSnapshot;
  currentUser: SessionUser;
  onClose: () => void;
  onChanged: () => Promise<void>;
  onSubmit: () => void;
  onReview: () => void;
}) {
  const member = snapshot.members.find((item) => item.id === task.current_owner_id);
  const [error, setError] = useState("");
  const [busyItem, setBusyItem] = useState<string | null>(null);

  async function toggleChecklist(itemId: string, checked: boolean) {
    setBusyItem(itemId);
    setError("");
    try {
      await commandTask(task.id, "set_checklist_item", {
        expected_version: task.row_version,
        expected_board_revision: snapshot.revision,
        item_id: itemId,
        checked,
      });
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusyItem(null);
    }
  }

  return (
    <Modal title={task.title} onClose={onClose}>
      {error && <Alert>{error}</Alert>}
      <div className="task-detail__meta">
        <span className="stars">{stars(task.priority)}</span>
        <span className={isOverdue(task) ? "status-pill status-pill--danger" : "status-pill"}>
          {task.column_state.replaceAll("_", " ")}
        </span>
        {isOverdue(task) && <span className="status-pill status-pill--danger">Overdue</span>}
      </div>
      <dl className="detail-grid">
        <dt>Owner</dt><dd>{member?.username ?? "Unassigned"}</dd>
        <dt>Deadline</dt><dd>{formatDateTime(taskDue(task))}</dd>
        <dt>Version</dt><dd>Task {task.row_version} · Board {snapshot.revision}</dd>
        <dt>Description</dt><dd>{task.description || "—"}</dd>
        <dt>Acceptance criteria</dt>
        <dd>{task.current_commitment?.acceptance_criteria || task.draft_acceptance_criteria || "—"}</dd>
      </dl>
      {task.checklist_items.length > 0 && (
        <section>
          <h3>Checklist</h3>
          <div className="checklist">
            {task.checklist_items.map((item) => (
              <label key={item.id} className="checklist__item">
                <input type="checkbox" checked={item.checked}
                  disabled={busyItem === item.id || ["REVIEW", "DONE"].includes(task.column_state)}
                  onChange={(e) => void toggleChecklist(item.id, e.target.checked)} />
                <span>{item.text}</span>
                {item.required && <span className="required-chip">Required</span>}
              </label>
            ))}
          </div>
        </section>
      )}
      <TaskWorkspaceExtras
        key={`${task.id}:${task.row_version}`}
        task={task}
        snapshot={snapshot}
        currentUser={currentUser}
        onChanged={onChanged}
      />
      <div className="modal__actions">
        {["TODO", "IN_PROGRESS", "BLOCKED"].includes(task.column_state) && (
          <button className="button button--primary" type="button" onClick={onSubmit}>Submit result</button>
        )}
        {task.column_state === "REVIEW" && snapshot.membership.role === "MANAGER" && (
          <button className="button button--primary" type="button" onClick={onReview}>Review result</button>
        )}
      </div>
    </Modal>
  );
}
