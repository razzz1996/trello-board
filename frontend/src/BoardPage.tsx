import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCorners,
  type DragEndEvent,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";

import {
  ApiError,
  addBoardMembershipByUsername,
  commandBoardMembership,
  commandTask,
  getBoardMemberships,
  getBoardSnapshot,
} from "./api";
import { QuickAddCard, TaskDetailModal } from "./TaskActions";
import type {
  BoardColumn,
  BoardMembershipAdmin,
  BoardSnapshot,
  Role,
  SessionUser,
  Task,
  TaskState,
} from "./types";
import { Alert, errorMessage, formatDateTime, isOverdue, Modal, stars, taskDue } from "./ui";

function SortableTaskCard({
  task,
  memberName,
  onOpen,
}: {
  task: Task;
  memberName: string;
  onOpen: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: task.id,
    data: { type: "task", taskId: task.id },
  });
  const due = taskDue(task);

  return (
    <article
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={`task-card ${isDragging ? "task-card--dragging" : ""}`}
      {...attributes}
      {...listeners}
    >
      <button className="task-card__body" type="button" onClick={onOpen}>
        <span className="stars" aria-label={`Priority ${task.priority} of 3`}>{stars(task.priority)}</span>
        <strong>{task.title}</strong>
        {due && (
          <span className={isOverdue(task) ? "deadline deadline--late" : "deadline"}>
            {formatDateTime(due)}
          </span>
        )}
        {task.current_owner_id && <span className="task-card__owner">{memberName}</span>}
      </button>
    </article>
  );
}

function ColumnView({
  column,
  memberName,
  onOpen,
}: {
  column: BoardColumn;
  memberName: (task: Task) => string;
  onOpen: (task: Task) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `column:${column.state}` });
  return (
    <div ref={setNodeRef} className={isOver ? "column-drop column-drop--over" : "column-drop"}>
      <section className="kanban-column" data-state={column.state}>
        <header>
          <h2>{column.name}</h2>
          <span>{column.tasks.length}</span>
        </header>
        <SortableContext items={column.tasks.map((task) => task.id)} strategy={verticalListSortingStrategy}>
          <div className="kanban-column__body">
            {column.tasks.map((task) => (
              <SortableTaskCard
                key={task.id}
                task={task}
                memberName={memberName(task)}
                onOpen={() => onOpen(task)}
              />
            ))}
            {column.tasks.length === 0 && (
              <div className="column-empty">
                {column.state === "BACKLOG" ? "New cards land here" : "Drop cards here"}
              </div>
            )}
          </div>
        </SortableContext>
      </section>
    </div>
  );
}

function ShareBoardModal({
  snapshot,
  onClose,
  onChanged,
}: {
  snapshot: BoardSnapshot;
  onClose: () => void;
  onChanged: () => Promise<void>;
}) {
  const [members, setMembers] = useState<BoardMembershipAdmin[]>([]);
  const [username, setUsername] = useState("");
  const [role, setRole] = useState<Role>("MEMBER");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refreshMembers = useCallback(async () => {
    setMembers(await getBoardMemberships(snapshot.board.id));
  }, [snapshot.board.id]);

  useEffect(() => {
    void refreshMembers().catch((caught) => setError(errorMessage(caught)));
  }, [refreshMembers]);

  async function addMember(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await addBoardMembershipByUsername(snapshot.board.id, username.trim(), role);
      setUsername("");
      setRole("MEMBER");
      await refreshMembers();
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function updateMember(
    member: BoardMembershipAdmin,
    command: "set_role" | "remove",
    payload: Record<string, unknown>,
  ) {
    setBusy(true);
    setError("");
    try {
      await commandBoardMembership(snapshot.board.id, member.user_id, command, {
        ...payload,
        reason: "Updated from board Share panel",
      });
      await refreshMembers();
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Share board" onClose={onClose}>
      {error && <Alert>{error}</Alert>}
      <p className="muted">Invite an existing eMEGA Productivity user by username.</p>
      <form className="share-form" onSubmit={addMember}>
        <label>
          Username
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="e.g. RC"
            required
          />
        </label>
        <label>
          Access
          <select value={role} onChange={(event) => setRole(event.target.value as Role)}>
            <option value="MEMBER">Member</option>
            <option value="MANAGER">Board manager</option>
          </select>
        </label>
        <button className="button button--primary" disabled={busy || !username.trim()}>
          Add to board
        </button>
      </form>
      <div className="share-members">
        {members.filter((member) => member.is_active).map((member) => (
          <div className="share-member" key={member.user_id}>
            <div>
              <strong>{member.username}</strong>
              <span>{member.role === "MANAGER" ? "Board manager" : "Member"}</span>
            </div>
            <div className="row-actions">
              <button
                className="button button--ghost"
                type="button"
                disabled={busy}
                onClick={() =>
                  void updateMember(member, "set_role", {
                    role: member.role === "MANAGER" ? "MEMBER" : "MANAGER",
                  })
                }
              >
                {member.role === "MANAGER" ? "Make member" : "Make manager"}
              </button>
              <button
                className="button button--ghost"
                type="button"
                disabled={busy}
                onClick={() => void updateMember(member, "remove", {})}
              >
                Remove
              </button>
            </div>
          </div>
        ))}
      </div>
    </Modal>
  );
}
export function BoardPage({ user }: { user: SessionUser }) {
  const { boardId } = useParams();
  const navigate = useNavigate();
  const [snapshot, setSnapshot] = useState<BoardSnapshot | null>(null);
  const snapshotRevision = useRef<number | undefined>(undefined);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [shareOpen, setShareOpen] = useState(false);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const refresh = useCallback(async () => {
    if (!boardId) return;
    try {
      const fresh = await getBoardSnapshot(boardId, snapshotRevision.current);
      if (fresh !== null) {
        snapshotRevision.current = fresh.revision;
        setSnapshot(fresh);
      }
      setError("");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 404) {
        navigate("/", { replace: true });
        return;
      }
      setError(errorMessage(caught));
    }
  }, [boardId, navigate]);

  useEffect(() => {
    snapshotRevision.current = undefined;
    setSnapshot(null);
  }, [boardId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 10_000);
    const refetchVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", refetchVisible);
    window.addEventListener("focus", refetchVisible);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", refetchVisible);
      window.removeEventListener("focus", refetchVisible);
    };
  }, [refresh]);

  const columns = useMemo(
    () => snapshot?.columns.filter((column) => column.state !== "REVIEW") ?? [],
    [snapshot],
  );
  const tasks = useMemo(() => columns.flatMap((column) => column.tasks), [columns]);
  const taskById = useCallback(
    (id: string | null) => tasks.find((task) => task.id === id) ?? null,
    [tasks],
  );

  async function moveTask(task: Task, targetState: TaskState, targetPosition: number | null) {
    if (!snapshot) return;
    try {
      await commandTask(task.id, "move_task", {
        expected_version: task.row_version,
        expected_board_revision: snapshot.revision,
        target_state: targetState,
        target_position: targetPosition,
        reason: "Moved on board",
      });
      setNotice("");
      await refresh();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        setNotice("This board changed while you were moving the card. I reloaded the latest version.");
        await refresh();
        return;
      }
      setError(errorMessage(caught));
    }
  }

  async function onDragEnd(event: DragEndEvent) {
    if (!snapshot || !event.over) return;
    const active = taskById(String(event.active.id));
    if (!active) return;

    const overId = String(event.over.id);
    let targetState: TaskState | null = null;
    let targetPosition: number | null = null;
    const overTask = taskById(overId);

    if (overTask) {
      targetState = overTask.column_state;
      targetPosition = overTask.position;
    } else if (overId.startsWith("column:")) {
      targetState = overId.slice("column:".length) as TaskState;
      targetPosition = columns.find((column) => column.state === targetState)?.tasks.length ?? null;
    }
    if (!targetState) return;

    if (active.column_state !== targetState || targetPosition !== active.position) {
      await moveTask(active, targetState, targetPosition);
    }
  }

  if (!boardId) return <Navigate to="/" replace />;
  if (!snapshot) {
    return <section>{error ? <Alert>{error}</Alert> : <div className="skeleton">Loading board…</div>}</section>;
  }

  const memberName = (task: Task) =>
    snapshot.members.find((member) => member.id === task.current_owner_id)?.username ?? "Unassigned";
  const selected = taskById(selectedTaskId);
  const canShare = snapshot.membership.role === "MANAGER" || user.is_admin;

  return (
    <section className="board-page">
      <div className="board-page__header">
        <div>
          <Link className="back-link" to="/">← Boards</Link>
          <h1>{snapshot.board.name}</h1>
          <p className="muted">Capture first. Organize by dragging cards when you are ready.</p>
        </div>
        {canShare && (
          <button className="button button--ghost" type="button" onClick={() => setShareOpen(true)}>
            Share
          </button>
        )}
      </div>

      <QuickAddCard snapshot={snapshot} onChanged={refresh} />
      {error && <Alert>{error}</Alert>}
      {notice && <Alert kind="info">{notice}</Alert>}

      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragEnd={(event) => void onDragEnd(event)}
      >
        <div className="kanban-board">
          {columns.map((column) => (
            <ColumnView
              key={column.id}
              column={column}
              memberName={memberName}
              onOpen={(task) => setSelectedTaskId(task.id)}
            />
          ))}
        </div>
      </DndContext>

      {selected && (
        <TaskDetailModal
          task={selected}
          snapshot={snapshot}
          currentUser={user}
          onClose={() => setSelectedTaskId(null)}
          onChanged={refresh}
        />
      )}
      {shareOpen && (
        <ShareBoardModal
          snapshot={snapshot}
          onClose={() => setShareOpen(false)}
          onChanged={refresh}
        />
      )}
    </section>
  );
}
