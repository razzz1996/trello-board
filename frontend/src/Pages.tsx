import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { createBoard, getBoards, getTasks } from "./api";
import type { BoardSummary, SessionUser, Task } from "./types";
import { Alert, errorMessage, formatDateTime, isOverdue, Metric, stars, taskDue } from "./ui";

function TaskTable({ tasks }: { tasks: Task[] }) {
  if (!tasks.length) return null;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr><th>Task</th><th>Stars</th><th>Status</th><th>Deadline</th><th>Owner ID</th></tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={task.id}>
              <td><Link to={`/boards/${task.board_id}`}>{task.title}</Link></td>
              <td className="stars">{stars(task.priority)}</td>
              <td>{task.column_state.replaceAll("_", " ")}</td>
              <td className={isOverdue(task) ? "deadline deadline--late" : "deadline"}>
                {formatDateTime(taskDue(task))}
              </td>
              <td>{task.current_owner_id ?? "Unassigned"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function BoardsPage() {
  const [boards, setBoards] = useState<BoardSummary[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    void getBoards()
      .then((data) => {
        if (active) setBoards(data);
      })
      .catch((caught) => {
        if (active) setError(errorMessage(caught));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  return (
    <section>
      <div className="page-heading"><div><h1>Boards</h1>
        <p>Shared team workspaces you are authorized to access.</p></div></div>
      {loading && <div className="skeleton">Loading boards…</div>}
      {error && <Alert>{error}</Alert>}
      {!loading && !boards.length && <div className="empty-state">No boards yet.</div>}
      <div className="board-grid">
        {boards.map((board) => (
          <Link key={board.id} className="board-tile" to={`/boards/${board.id}`}>
            <div className="board-tile__title">{board.name}</div>
            <div className="board-tile__meta">Revision {board.revision}{board.archived ? " · Archived" : ""}</div>
          </Link>
        ))}
      </div>
    </section>
  );
}

export function MyTasksPage({ user }: { user: SessionUser }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void getTasks(`owner=${encodeURIComponent(user.id)}`)
      .then((data) => { if (active) setTasks(data); })
      .catch((caught) => { if (active) setError(errorMessage(caught)); });
    return () => { active = false; };
  }, [user.id]);

  return (
    <section>
      <div className="page-heading"><div><h1>My Tasks</h1>
        <p>Current work assigned to you across authorized boards.</p></div></div>
      {error && <Alert>{error}</Alert>}
      {!error && !tasks.length && <div className="empty-state">No current assigned tasks.</div>}
      <TaskTable tasks={tasks} />
    </section>
  );
}

export function ManagerPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void getTasks()
      .then((data) => { if (active) setTasks(data); })
      .catch((caught) => { if (active) setError(errorMessage(caught)); });
    return () => { active = false; };
  }, []);

  const attention = useMemo(
    () => tasks.filter((task) => isOverdue(task) || ["REVIEW", "BLOCKED"].includes(task.column_state)),
    [tasks],
  );
  return (
    <section>
      <div className="page-heading"><div><h1>Manager Overview</h1>
        <p>Current workload view. Formal performance uses immutable report snapshots.</p></div></div>
      {error && <Alert>{error}</Alert>}
      <div className="metric-grid">
        <Metric label="Overdue" value={tasks.filter(isOverdue).length} tone="danger" />
        <Metric label="Waiting review" value={tasks.filter((t) => t.column_state === "REVIEW").length} />
        <Metric label="Blocked" value={tasks.filter((t) => t.column_state === "BLOCKED").length} />
        <Metric label="★★★ active" value={tasks.filter((t) => t.priority === 3 && t.column_state !== "DONE").length} />
      </div>
      <h2>Attention required</h2>
      {!attention.length && <div className="empty-state">No overdue, blocked, or review-waiting work.</div>}
      <TaskTable tasks={attention} />
    </section>
  );
}

export function CalendarPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void getTasks()
      .then((data) => {
        if (!active) return;
        setTasks(
          data.filter((task) => taskDue(task)).sort(
            (a, b) => new Date(taskDue(a) ?? 0).valueOf() - new Date(taskDue(b) ?? 0).valueOf(),
          ),
        );
      })
      .catch((caught) => { if (active) setError(errorMessage(caught)); });
    return () => { active = false; };
  }, []);

  return (
    <section>
      <div className="page-heading"><div><h1>Calendar</h1>
        <p>Issued task deadlines. Published recurrence previews will be added by the schedule module.</p></div></div>
      {error && <Alert>{error}</Alert>}
      <div className="timeline">
        {tasks.map((task) => (
          <Link className="timeline__item" key={task.id} to={`/boards/${task.board_id}`}>
            <time>{formatDateTime(taskDue(task))}</time>
            <strong>{task.title}</strong>
            <span>{stars(task.priority)}</span>
          </Link>
        ))}
        {!tasks.length && <div className="empty-state">No scheduled task deadlines.</div>}
      </div>
    </section>
  );
}

export function ReportsPage() {
  return (
    <section>
      <div className="page-heading"><div><h1>Reports</h1>
        <p>Immutable daily manager reports and deadline adherence.</p></div></div>
      <Alert kind="info">
        Report calculations are not approximated in the browser. The server snapshot endpoint is implemented
        separately so original/revised deadlines, cancellations, reviews, and observation time remain auditable.
      </Alert>
    </section>
  );
}

export function AdminPage({ user }: { user: SessionUser }) {
  const [name, setName] = useState("");
  const [boards, setBoards] = useState<BoardSummary[]>([]);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setBoards(await getBoards());
  }, []);
  useEffect(() => {
    void refresh().catch((caught) => setError(errorMessage(caught)));
  }, [refresh]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const board = await createBoard(name, [user.id]);
      setName("");
      setSuccess(`Created ${board.name}. You are its initial manager.`);
      await refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <div className="page-heading"><div><h1>Administration</h1>
        <p>Board creation is enabled. Account and membership changes remain audited server actions.</p></div></div>
      {error && <Alert>{error}</Alert>}
      {success && <Alert kind="success">{success}</Alert>}
      <div className="two-column">
        <section className="panel">
          <h2>Create board</h2>
          <form className="stack" onSubmit={submit}>
            <label>Board name
              <input value={name} onChange={(event) => setName(event.target.value)} required maxLength={200} />
            </label>
            <button className="button button--primary" disabled={busy}>
              {busy ? "Creating…" : "Create board"}
            </button>
          </form>
        </section>
        <section className="panel">
          <h2>Existing boards</h2>
          <ul className="plain-list">
            {boards.map((board) => (
              <li key={board.id}><Link to={`/boards/${board.id}`}>{board.name}</Link>
                <span>rev {board.revision}</span></li>
            ))}
          </ul>
        </section>
      </div>
    </section>
  );
}
