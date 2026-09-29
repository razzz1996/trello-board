import { type FormEvent, useMemo, useState } from "react";

import { commandTask } from "./api";
import type { BoardSnapshot, SessionUser, Task } from "./types";
import { Alert, errorMessage, formatDateTime } from "./ui";

function localDateTimeInput(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "";
  const shifted = new Date(date.valueOf() - date.getTimezoneOffset() * 60_000);
  return shifted.toISOString().slice(0, 16);
}

type ChecklistDraft = { text: string; required: boolean };

export function TaskWorkspaceExtras({
  task,
  snapshot,
  currentUser,
  onChanged,
}: {
  task: Task;
  snapshot: BoardSnapshot;
  currentUser: SessionUser;
  onChanged: () => Promise<void>;
}) {
  return (
    <div className="task-extras">
      {task.committed_at === null ? (
        <DraftEditor task={task} snapshot={snapshot} onChanged={onChanged} />
      ) : (
        <>
          {snapshot.membership.role === "MANAGER" && task.column_state !== "DONE" && (
            <CommitmentRevisionForm task={task} snapshot={snapshot} onChanged={onChanged} />
          )}
          {task.column_state !== "DONE" && (
            <ProposalForm task={task} snapshot={snapshot} onChanged={onChanged} />
          )}
          {snapshot.membership.role === "MANAGER" && (
            <ProposalResolution task={task} snapshot={snapshot} onChanged={onChanged} />
          )}
        </>
      )}
      <CommentsPanel
        task={task}
        snapshot={snapshot}
        currentUser={currentUser}
        onChanged={onChanged}
      />
    </div>
  );
}

function DraftEditor({
  task,
  snapshot,
  onChanged,
}: {
  task: Task;
  snapshot: BoardSnapshot;
  onChanged: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(task.title);
  const [description, setDescription] = useState(task.description);
  const [priority, setPriority] = useState(task.priority);
  const [ownerId, setOwnerId] = useState(task.current_owner_id ?? "");
  const [due, setDue] = useState(localDateTimeInput(task.draft_due_at));
  const [criteria, setCriteria] = useState(task.draft_acceptance_criteria);
  const [items, setItems] = useState<ChecklistDraft[]>(
    task.checklist_items.map((item) => ({
      text: item.text,
      required: item.required,
    })),
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function saveFields(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await commandTask(task.id, "edit_task", {
        expected_version: task.row_version,
        expected_board_revision: snapshot.revision,
        title,
        description,
        priority,
        owner_id: ownerId || null,
        draft_due_at: due ? new Date(due).toISOString() : null,
        draft_acceptance_criteria: criteria,
      });
      await onChanged();
      setOpen(false);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function saveChecklist() {
    setBusy(true);
    setError("");
    try {
      await commandTask(task.id, "replace_draft_checklist", {
        expected_version: task.row_version,
        expected_board_revision: snapshot.revision,
        items,
      });
      await onChanged();
      setOpen(false);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="task-section">
      <div className="section-heading">
        <h3>Draft setup</h3>
        <button className="button button--ghost" type="button" onClick={() => setOpen(!open)}>
          {open ? "Hide" : "Edit draft"}
        </button>
      </div>
      {open && (
        <div className="stack">
          {error && <Alert>{error}</Alert>}
          <form className="stack" onSubmit={saveFields}>
            <label>Title
              <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} required />
            </label>
            <label>Description
              <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={4} />
            </label>
            <div className="form-grid">
              <label>Priority
                <select value={priority} onChange={(e) => setPriority(Number(e.target.value) as 1 | 2 | 3)}>
                  <option value={1}>★</option><option value={2}>★★</option><option value={3}>★★★</option>
                </select>
              </label>
              <label>Draft owner
                <select value={ownerId} onChange={(e) => setOwnerId(e.target.value)}>
                  <option value="">Unassigned</option>
                  {snapshot.members.map((member) => (
                    <option key={member.id} value={member.id}>{member.username}</option>
                  ))}
                </select>
              </label>
              <label>Draft deadline
                <input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} />
              </label>
            </div>
            <label>Draft acceptance criteria
              <textarea value={criteria} onChange={(e) => setCriteria(e.target.value)} rows={4} />
            </label>
            <button className="button button--primary" disabled={busy}>Save draft fields</button>
          </form>
          <ChecklistStructureEditor items={items} setItems={setItems} />
          <button className="button button--primary" type="button"
            disabled={busy} onClick={() => void saveChecklist()}>
            Save checklist structure
          </button>
        </div>
      )}
    </section>
  );
}

function ChecklistStructureEditor({
  items,
  setItems,
  requiredOnly = false,
}: {
  items: ChecklistDraft[];
  setItems: (value: ChecklistDraft[]) => void;
  requiredOnly?: boolean;
}) {
  return (
    <div className="stack">
      <div className="section-heading">
        <h4>Checklist structure</h4>
        <button className="button button--ghost" type="button"
          onClick={() =>
            setItems([...items, { text: "", required: requiredOnly }])
          }>+ Item</button>
      </div>
      {items.map((item, index) => (
        <div className="checklist-edit-row" key={index}>
          <input value={item.text} placeholder="Checklist item"
            onChange={(e) => {
              const next = [...items];
              next[index] = { ...item, text: e.target.value };
              setItems(next);
            }} />
          {requiredOnly ? (
            <span className="required-chip">Required</span>
          ) : (
            <label className="inline-check">
              <input type="checkbox" checked={item.required}
                onChange={(e) => {
                  const next = [...items];
                  next[index] = { ...item, required: e.target.checked };
                  setItems(next);
                }} />
              Required
            </label>
          )}
          <button className="button button--ghost" type="button"
            onClick={() => setItems(items.filter((_, position) => position !== index))}>Remove</button>
        </div>
      ))}
    </div>
  );
}

function CommitmentRevisionForm({
  task,
  snapshot,
  onChanged,
}: {
  task: Task;
  snapshot: BoardSnapshot;
  onChanged: () => Promise<void>;
}) {
  const commitment = task.current_commitment;
  const [open, setOpen] = useState(false);
  const [ownerId, setOwnerId] = useState(task.current_owner_id ?? "");
  const [priority, setPriority] = useState(task.priority);
  const [due, setDue] = useState(localDateTimeInput(commitment?.due_at ?? null));
  const [criteria, setCriteria] = useState(commitment?.acceptance_criteria ?? "");
  const [required, setRequired] = useState<ChecklistDraft[]>(
    task.checklist_items
      .filter((item) => item.required)
      .map((item) => ({ text: item.text, required: true })),
  );
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (!commitment) return null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await commandTask(task.id, "revise_commitment", {
        expected_version: task.row_version,
        expected_board_revision: snapshot.revision,
        owner_id: ownerId,
        priority,
        due_at: new Date(due).toISOString(),
        acceptance_criteria: criteria,
        required_checklist: required.map((item) => ({ text: item.text })),
        reason,
      });
      await onChanged();
      setOpen(false);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="task-section">
      <div className="section-heading">
        <h3>Commitment</h3>
        <button className="button button--ghost" type="button" onClick={() => setOpen(!open)}>
          {open ? "Hide revision" : "Revise commitment"}
        </button>
      </div>
      {open && (
        <form className="stack" onSubmit={submit}>
          {error && <Alert>{error}</Alert>}
          <div className="form-grid">
            <label>Owner
              <select value={ownerId} onChange={(e) => setOwnerId(e.target.value)} required>
                {snapshot.members.map((member) => (
                  <option key={member.id} value={member.id}>{member.username}</option>
                ))}
              </select>
            </label>
            <label>Priority
              <select value={priority} onChange={(e) => setPriority(Number(e.target.value) as 1 | 2 | 3)}>
                <option value={1}>★</option><option value={2}>★★</option><option value={3}>★★★</option>
              </select>
            </label>
            <label>Deadline
              <input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} required />
            </label>
          </div>
          <label>Acceptance criteria
            <textarea rows={4} value={criteria} onChange={(e) => setCriteria(e.target.value)} required />
          </label>
          <ChecklistStructureEditor
            items={required}
            setItems={setRequired}
            requiredOnly
          />
          <label>Revision reason
            <textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)}
              maxLength={2000} required />
          </label>
          <button className="button button--primary" disabled={busy}>
            {busy ? "Revising…" : "Create commitment revision"}
          </button>
        </form>
      )}
    </section>
  );
}

function ProposalForm({
  task,
  snapshot,
  onChanged,
}: {
  task: Task;
  snapshot: BoardSnapshot;
  onChanged: () => Promise<void>;
}) {
  const current = task.current_commitment;
  const [open, setOpen] = useState(false);
  const [ownerId, setOwnerId] = useState(task.current_owner_id ?? "");
  const [priority, setPriority] = useState(task.priority);
  const [due, setDue] = useState(localDateTimeInput(current?.due_at ?? null));
  const [criteria, setCriteria] = useState(current?.acceptance_criteria ?? "");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (!current) return null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    const commitment = task.current_commitment;
    if (!commitment) return;
    const proposed: Record<string, unknown> = {};
    if (ownerId !== task.current_owner_id) proposed.owner_id = ownerId;
    if (priority !== task.priority) proposed.priority = priority;
    const proposedDue = new Date(due).toISOString();
    if (proposedDue !== new Date(commitment.due_at).toISOString()) {
      proposed.due_at = proposedDue;
    }
    if (criteria.trim() !== commitment.acceptance_criteria) {
      proposed.acceptance_criteria = criteria.trim();
    }
    if (!Object.keys(proposed).length) {
      setError("Change at least one commitment field before proposing.");
      return;
    }

    setBusy(true);
    setError("");
    try {
      await commandTask(task.id, "propose_change", {
        expected_version: task.row_version,
        expected_board_revision: snapshot.revision,
        proposed_changes: proposed,
        reason,
      });
      await onChanged();
      setOpen(false);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="task-section">
      <div className="section-heading">
        <h3>Change request</h3>
        <button className="button button--ghost" type="button" onClick={() => setOpen(!open)}>
          {open ? "Hide proposal" : "Propose commitment change"}
        </button>
      </div>
      {open && (
        <form className="stack" onSubmit={submit}>
          {error && <Alert>{error}</Alert>}
          <div className="form-grid">
            <label>Proposed owner
              <select value={ownerId} onChange={(e) => setOwnerId(e.target.value)}>
                {snapshot.members.map((member) => (
                  <option key={member.id} value={member.id}>{member.username}</option>
                ))}
              </select>
            </label>
            <label>Proposed priority
              <select value={priority} onChange={(e) => setPriority(Number(e.target.value) as 1 | 2 | 3)}>
                <option value={1}>★</option><option value={2}>★★</option><option value={3}>★★★</option>
              </select>
            </label>
            <label>Proposed deadline
              <input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} required />
            </label>
          </div>
          <label>Proposed acceptance criteria
            <textarea rows={4} value={criteria} onChange={(e) => setCriteria(e.target.value)} required />
          </label>
          <label>Why this change is needed
            <textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)}
              maxLength={2000} required />
          </label>
          <button className="button button--primary" disabled={busy}>
            {busy ? "Submitting…" : "Submit change proposal"}
          </button>
        </form>
      )}
    </section>
  );
}

function ProposalResolution({
  task,
  snapshot,
  onChanged,
}: {
  task: Task;
  snapshot: BoardSnapshot;
  onChanged: () => Promise<void>;
}) {
  const pending = useMemo(
    () => task.change_proposals.filter((proposal) => proposal.status === "PENDING"),
    [task.change_proposals],
  );
  const [reason, setReason] = useState("Manager decision on requested commitment change");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");

  if (!pending.length) return null;

  async function decide(proposalId: string, decision: "ACCEPTED" | "DECLINED") {
    if (!reason.trim()) {
      setError("A resolution reason is required.");
      return;
    }
    setBusyId(proposalId);
    setError("");
    try {
      await commandTask(task.id, "resolve_change_proposal", {
        expected_version: task.row_version,
        expected_board_revision: snapshot.revision,
        proposal_id: proposalId,
        decision,
        reason,
      });
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="task-section">
      <h3>Pending change proposals</h3>
      {error && <Alert>{error}</Alert>}
      <label>Resolution reason
        <input value={reason} onChange={(e) => setReason(e.target.value)}
          maxLength={2000} />
      </label>
      <div className="proposal-list">
        {pending.map((proposal) => (
          <article className="proposal-card" key={proposal.id}>
            <div>
              <strong>Requested {formatDateTime(proposal.created_at)}</strong>
              <p>{proposal.reason}</p>
              <pre>{JSON.stringify(proposal.proposed_changes, null, 2)}</pre>
            </div>
            <div className="row-actions">
              <button className="button button--danger" type="button"
                disabled={busyId === proposal.id}
                onClick={() => void decide(proposal.id, "DECLINED")}>
                Decline
              </button>
              <button className="button button--success" type="button"
                disabled={busyId === proposal.id}
                onClick={() => void decide(proposal.id, "ACCEPTED")}>
                Accept and revise
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function CommentsPanel({
  task,
  snapshot,
  currentUser,
  onChanged,
}: {
  task: Task;
  snapshot: BoardSnapshot;
  currentUser: SessionUser;
  onChanged: () => Promise<void>;
}) {
  const [body, setBody] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [correction, setCorrection] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function add(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await commandTask(task.id, "add_comment", {
        expected_version: task.row_version,
        expected_board_revision: snapshot.revision,
        body,
      });
      setBody("");
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function correct(commentId: string) {
    setBusy(true);
    setError("");
    try {
      await commandTask(task.id, "correct_comment", {
        expected_version: task.row_version,
        expected_board_revision: snapshot.revision,
        comment_id: commentId,
        body: correction,
      });
      setEditingId(null);
      setCorrection("");
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="task-section">
      <h3>Comments</h3>
      {error && <Alert>{error}</Alert>}
      <form className="comment-form" onSubmit={add}>
        <textarea value={body} onChange={(e) => setBody(e.target.value)}
          placeholder="Add a comment…" rows={3} maxLength={10000} required />
        <button className="button button--primary" disabled={busy}>Add comment</button>
      </form>
      <div className="comment-list">
        {task.comments.map((comment) => {
          const canCorrect =
            comment.author_id === currentUser.id ||
            snapshot.membership.role === "MANAGER";
          return (
            <article className="comment-card" key={comment.id}>
              <header>
                <strong>{comment.author_username}</strong>
                <span>{formatDateTime(comment.created_at)}
                  {comment.corrected_at ? " · corrected" : ""}
                </span>
              </header>
              <p>{comment.body}</p>
              {canCorrect && (
                <button className="button button--ghost" type="button"
                  onClick={() => {
                    setEditingId(comment.id);
                    setCorrection(comment.body);
                  }}>
                  Correct
                </button>
              )}
              {editingId === comment.id && (
                <div className="stack compact-stack">
                  <textarea value={correction}
                    onChange={(e) => setCorrection(e.target.value)}
                    rows={3} maxLength={10000} />
                  <div className="row-actions">
                    <button className="button button--primary" type="button"
                      disabled={busy}
                      onClick={() => void correct(comment.id)}>Save correction</button>
                    <button className="button button--ghost" type="button"
                      onClick={() => setEditingId(null)}>Cancel</button>
                  </div>
                </div>
              )}
              {comment.history.length > 0 && (
                <details>
                  <summary>Correction history ({comment.history.length})</summary>
                  <ul className="history-list">
                    {comment.history.map((entry) => (
                      <li key={entry.id}>
                        <time>{formatDateTime(entry.edited_at)}</time>
                        <div><strong>Previous:</strong> {entry.previous_body}</div>
                        <div><strong>Replacement:</strong> {entry.replacement_body}</div>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </article>
          );
        })}
        {!task.comments.length && <p className="muted">No comments yet.</p>}
      </div>
    </section>
  );
}
