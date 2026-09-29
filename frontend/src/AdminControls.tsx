import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  addBoardMembership,
  commandAdminUser,
  commandBoardMembership,
  createAdminUser,
  createBoard,
  getAdminUsers,
  getBoardMemberships,
  getBoards,
  getHealthDetail,
} from "./api";
import type {
  AdminUser,
  BoardMembershipAdmin,
  BoardSummary,
  HealthDetail,
  Role,
  SessionUser,
} from "./types";
import { Alert, errorMessage } from "./ui";

export function AdminControls({ user }: { user: SessionUser }) {
  const [boards, setBoards] = useState<BoardSummary[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [selectedBoardId, setSelectedBoardId] = useState("");
  const [memberships, setMemberships] = useState<BoardMembershipAdmin[]>([]);
  const [health, setHealth] = useState<HealthDetail | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const refreshBase = useCallback(async () => {
    const [boardRows, userRows] = await Promise.all([getBoards(), getAdminUsers()]);
    setBoards(boardRows);
    setUsers(userRows);
    setSelectedBoardId((current) => current || boardRows[0]?.id || "");
  }, []);

  const refreshMemberships = useCallback(async () => {
    if (!selectedBoardId) {
      setMemberships([]);
      return;
    }
    setMemberships(await getBoardMemberships(selectedBoardId));
  }, [selectedBoardId]);

  useEffect(() => {
    void refreshBase().catch((caught) => setError(errorMessage(caught)));
  }, [refreshBase]);

  useEffect(() => {
    void refreshMemberships().catch((caught) => setError(errorMessage(caught)));
  }, [refreshMemberships]);

  const refreshHealth = useCallback(async () => {
    setHealth(await getHealthDetail());
  }, []);

  useEffect(() => {
    void refreshHealth().catch((caught) => setError(errorMessage(caught)));
  }, [refreshHealth]);

  async function run(
    action: () => Promise<unknown>,
    message: string,
    refresh: "base" | "memberships" | "both" = "both",
  ) {
    setError("");
    setSuccess("");
    try {
      await action();
      setSuccess(message);
      if (refresh === "base" || refresh === "both") await refreshBase();
      if (refresh === "memberships" || refresh === "both") await refreshMemberships();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  return (
    <section>
      <div className="page-heading">
        <div>
          <h1>Administration</h1>
          <p>Account, board, and membership changes are server-audited and versioned.</p>
        </div>
      </div>
      {error && <Alert>{error}</Alert>}
      {success && <Alert kind="success">{success}</Alert>}
      <HealthPanel health={health} onRefresh={refreshHealth} />
      <div className="admin-grid">
        <BoardCreatePanel user={user} onCreated={refreshBase} onError={setError} />
        <UserCreatePanel onCreated={refreshBase} onError={setError} />
      </div>
      <UserAdminTable users={users} run={run} />
      <MembershipPanel
        boards={boards}
        users={users}
        boardId={selectedBoardId}
        setBoardId={setSelectedBoardId}
        memberships={memberships}
        run={run}
      />
    </section>
  );
}

function HealthPanel({
  health,
  onRefresh,
}: {
  health: HealthDetail | null;
  onRefresh: () => Promise<void>;
}) {
  return (
    <section className="panel admin-section">
      <div className="modal__header">
        <div>
          <h2>Operational health</h2>
          <p className="muted">Worker, queue, disk, and independent-backup indicators.</p>
        </div>
        <button className="button button--ghost" type="button" onClick={() => void onRefresh()}>
          Refresh
        </button>
      </div>
      {!health ? (
        <div className="skeleton">Loading health…</div>
      ) : (
        <>
          {health.warnings.length > 0 && (
            <Alert kind="info">Warnings: {health.warnings.join(", ")}</Alert>
          )}
          <div className="metric-grid">
            <div className="metric">
              <span>Worker heartbeat</span>
              <strong>{health.heartbeats.worker?.stale ? "Stale" : "OK"}</strong>
            </div>
            <div className="metric">
              <span>Scheduler heartbeat</span>
              <strong>{health.heartbeats.scheduler?.stale ? "Stale" : "OK"}</strong>
            </div>
            <div className="metric">
              <span>Oldest ready job</span>
              <strong>{Math.round(health.queue.oldest_ready_age_seconds)}s</strong>
            </div>
            <div className="metric">
              <span>Disk free</span>
              <strong>{health.disk.free_percent.toFixed(1)}%</strong>
            </div>
          </div>
          <p className="muted">
            Failed jobs: {health.queue.failed} · Unknown sends: {health.queue.unknown} · Backup:{" "}
            {health.backup.status}
            {health.backup.age_hours === null
              ? ""
              : " (" + health.backup.age_hours.toFixed(1) + "h old)"}
          </p>
        </>
      )}
    </section>
  );
}


function BoardCreatePanel({
  user,
  onCreated,
  onError,
}: {
  user: SessionUser;
  onCreated: () => Promise<void>;
  onError: (value: string) => void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await createBoard(name, [user.id]);
      setName("");
      await onCreated();
    } catch (caught) {
      onError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Create board</h2>
      <form className="stack" onSubmit={submit}>
        <label>
          Board name
          <input value={name} onChange={(event) => setName(event.target.value)}
            required maxLength={200} />
        </label>
        <button className="button button--primary" disabled={busy}>
          {busy ? "Creating…" : "Create board"}
        </button>
      </form>
    </section>
  );
}

function UserCreatePanel({
  onCreated,
  onError,
}: {
  onCreated: () => Promise<void>;
  onError: (value: string) => void;
}) {
  const [username, setUsername] = useState("");
  const [temporaryPassword, setTemporaryPassword] = useState("");
  const [reason, setReason] = useState("Initial account provisioning");
  const [isAdmin, setIsAdmin] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await createAdminUser({
        username,
        temporary_password: temporaryPassword,
        is_admin: isAdmin,
        reason,
      });
      setUsername("");
      setTemporaryPassword("");
      setIsAdmin(false);
      await onCreated();
    } catch (caught) {
      onError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Create account</h2>
      <form className="stack" onSubmit={submit}>
        <label>Username
          <input value={username} onChange={(event) => setUsername(event.target.value)}
            autoComplete="off" required maxLength={150} />
        </label>
        <label>Temporary password
          <input type="password" value={temporaryPassword}
            onChange={(event) => setTemporaryPassword(event.target.value)}
            autoComplete="new-password" minLength={12} required />
        </label>
        <label>Reason
          <input value={reason} onChange={(event) => setReason(event.target.value)}
            maxLength={2000} required />
        </label>
        <label className="inline-check">
          <input type="checkbox" checked={isAdmin}
            onChange={(event) => setIsAdmin(event.target.checked)} />
          Administrator
        </label>
        <button className="button button--primary" disabled={busy}>
          {busy ? "Creating…" : "Create account"}
        </button>
      </form>
    </section>
  );
}

function UserAdminTable({
  users,
  run,
}: {
  users: AdminUser[];
  run: (
    action: () => Promise<unknown>,
    message: string,
    refresh?: "base" | "memberships" | "both",
  ) => Promise<void>;
}) {
  const [resetUserId, setResetUserId] = useState<string | null>(null);
  const [temporaryPassword, setTemporaryPassword] = useState("");
  const [resetReason, setResetReason] = useState("");

  async function accountCommand(
    row: AdminUser,
    command: "disable" | "enable" | "set_admin",
    payload: Record<string, unknown>,
    label: string,
  ) {
    const reason = window.prompt(`Reason for ${label}:`)?.trim();
    if (!reason) return;
    await run(
      () => commandAdminUser(row.id, command, { ...payload, reason }),
      `${row.username}: ${label} completed.`,
    );
  }

  async function reset(event: FormEvent, row: AdminUser) {
    event.preventDefault();
    await run(
      () =>
        commandAdminUser(row.id, "reset_password", {
          temporary_password: temporaryPassword,
          reason: resetReason,
        }),
      `${row.username}: password reset and active sessions revoked.`,
      "base",
    );
    setTemporaryPassword("");
    setResetReason("");
    setResetUserId(null);
  }

  return (
    <section className="panel admin-section">
      <h2>Accounts</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>User</th><th>Status</th><th>Role</th><th>Slack</th><th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((row) => (
              <tr key={row.id}>
                <td>{row.username}</td>
                <td>{row.is_active ? "Active" : "Disabled"}</td>
                <td>{row.is_admin ? "Administrator" : "Member"}</td>
                <td>{row.slack_verified ? "Verified" : "Not verified"}</td>
                <td>
                  <div className="row-actions">
                    <button className="button button--ghost" type="button"
                      onClick={() => setResetUserId(row.id)}>Reset password</button>
                    {row.is_active ? (
                      <button className="button button--danger" type="button"
                        onClick={() => void accountCommand(row, "disable", {}, "disable account")}>
                        Disable
                      </button>
                    ) : (
                      <button className="button button--success" type="button"
                        onClick={() => void accountCommand(row, "enable", {}, "enable account")}>
                        Enable
                      </button>
                    )}
                    <button className="button button--ghost" type="button"
                      onClick={() =>
                        void accountCommand(
                          row,
                          "set_admin",
                          { is_admin: !row.is_admin },
                          row.is_admin ? "remove administrator role" : "grant administrator role",
                        )
                      }>
                      {row.is_admin ? "Demote" : "Make admin"}
                    </button>
                  </div>
                  {resetUserId === row.id && (
                    <form className="inline-form" onSubmit={(event) => void reset(event, row)}>
                      <input type="password" value={temporaryPassword}
                        onChange={(event) => setTemporaryPassword(event.target.value)}
                        placeholder="New temporary password" autoComplete="new-password"
                        minLength={12} required />
                      <input value={resetReason}
                        onChange={(event) => setResetReason(event.target.value)}
                        placeholder="Reset reason" maxLength={2000} required />
                      <button className="button button--primary">Reset</button>
                      <button className="button button--ghost" type="button"
                        onClick={() => setResetUserId(null)}>Cancel</button>
                    </form>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function MembershipPanel({
  boards,
  users,
  boardId,
  setBoardId,
  memberships,
  run,
}: {
  boards: BoardSummary[];
  users: AdminUser[];
  boardId: string;
  setBoardId: (value: string) => void;
  memberships: BoardMembershipAdmin[];
  run: (
    action: () => Promise<unknown>,
    message: string,
    refresh?: "base" | "memberships" | "both",
  ) => Promise<void>;
}) {
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState<Role>("MEMBER");
  const [reason, setReason] = useState("Board access granted");
  const [changeReason, setChangeReason] = useState("Board access maintenance");

  async function add(event: FormEvent) {
    event.preventDefault();
    if (!boardId) return;
    await run(
      () => addBoardMembership(boardId, userId, role, reason),
      "Board membership added.",
      "memberships",
    );
    setUserId("");
  }

  async function change(item: BoardMembershipAdmin, command: "set_role" | "remove") {
    if (!boardId || !changeReason.trim()) return;
    const payload: Record<string, unknown> = { reason: changeReason };
    if (command === "set_role") {
      payload.role = item.role === "MANAGER" ? "MEMBER" : "MANAGER";
    }
    await run(
      () => commandBoardMembership(boardId, item.user_id, command, payload),
      `${item.username}: board membership updated.`,
      "memberships",
    );
  }

  const activeUsers = users.filter((item) => item.is_active);
  return (
    <section className="panel admin-section">
      <div className="section-heading">
        <div>
          <h2>Board memberships</h2>
          <p className="muted">The server prevents removal or demotion of the last active board manager.</p>
        </div>
        <select value={boardId} onChange={(event) => setBoardId(event.target.value)}>
          <option value="">Select board</option>
          {boards.map((board) => (
            <option key={board.id} value={board.id}>{board.name}</option>
          ))}
        </select>
      </div>
      {boardId && (
        <>
          <form className="membership-add" onSubmit={add}>
            <select value={userId} onChange={(event) => setUserId(event.target.value)} required>
              <option value="">Select active user</option>
              {activeUsers.map((item) => (
                <option key={item.id} value={item.id}>{item.username}</option>
              ))}
            </select>
            <select value={role} onChange={(event) => setRole(event.target.value as Role)}>
              <option value="MEMBER">Member</option>
              <option value="MANAGER">Manager</option>
            </select>
            <input value={reason} onChange={(event) => setReason(event.target.value)}
              maxLength={2000} required />
            <button className="button button--primary">Add / reactivate</button>
          </form>
          <label>
            Reason for role/removal actions
            <input value={changeReason}
              onChange={(event) => setChangeReason(event.target.value)}
              maxLength={2000} required />
          </label>
          <ul className="membership-list">
            {memberships.map((item) => (
              <li key={item.user_id}>
                <div>
                  <strong>{item.username}</strong>
                  <span>{item.role} · {item.is_active ? "active" : "inactive"}</span>
                </div>
                <div className="row-actions">
                  {item.is_active && (
                    <>
                      <button className="button button--ghost" type="button"
                        onClick={() => void change(item, "set_role")}>
                        {item.role === "MANAGER" ? "Make member" : "Make manager"}
                      </button>
                      <button className="button button--danger" type="button"
                        onClick={() => void change(item, "remove")}>Remove</button>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
          <p><Link to={`/boards/${boardId}`}>Open selected board →</Link></p>
        </>
      )}
    </section>
  );
}
