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
import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Link,
  Navigate,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";

import {
  ApiError,
  commandBoardColumn,
  commandTask,
  createBoardColumn,
  createTask,
  getBoardSnapshot,
} from "./api";
import { TaskDetailModal } from "./TaskActions";
import type {
  BoardColumn,
  BoardSnapshot,
  SessionUser,
  Task,
} from "./types";
import {
  Alert,
  errorMessage,
  formatDateTime,
  isOverdue,
  stars,
  taskDue,
} from "./ui";

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
      className={`task-card trello-card ${isDragging ? "task-card--dragging" : ""}`}
      {...attributes}
      {...listeners}
    >
      <button className="task-card__body" type="button" onClick={onOpen}>
        {task.priority > 0 && (
          <span className="stars" aria-label={`Priority ${task.priority} of 3`}>
            {stars(task.priority)}
          </span>
        )}
        <strong>{task.title}</strong>
        <div className="trello-card__meta">
          {due && (
            <span className={isOverdue(task) ? "deadline deadline--late" : "deadline"}>
              ◷ {formatDateTime(due)}
            </span>
          )}
          {task.recurrence_frequency !== "NONE" && (
            <span className="task-card__repeat">
              ↻ {task.recurrence_frequency.toLowerCase()}
            </span>
          )}
        </div>
        {task.current_owner_id && (
          <span className="task-card__owner">{memberName}</span>
        )}
      </button>
    </article>
  );
}

function InlineAddCard({
  snapshot,
  column,
  onChanged,
  defaultOpen = false,
}: {
  snapshot: BoardSnapshot;
  column: BoardColumn;
  onChanged: () => Promise<void>;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const cleaned = title.trim();
    if (!cleaned) return;
    setBusy(true);
    setError("");
    try {
      await createTask({
        board_id: snapshot.board.id,
        column_id: column.id,
        title: cleaned,
        priority: 1,
        owner_id: null,
        draft_due_at: null,
        draft_acceptance_criteria: "",
      });
      setTitle("");
      if (!defaultOpen) setOpen(false);
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        className="trello-add-card"
        type="button"
        onClick={() => setOpen(true)}
      >
        <span>＋</span> Add a card
      </button>
    );
  }

  return (
    <form className="trello-add-form" onSubmit={submit}>
      {error && <span className="trello-inline-error">{error}</span>}
      <textarea
        autoFocus={!defaultOpen}
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        placeholder={column.state === "BACKLOG" ? "Add a card" : "Enter a title for this card…"}
        aria-label={`Add a card to ${column.name}`}
        maxLength={200}
        rows={defaultOpen ? 1 : 3}
      />
      {(!defaultOpen || title.trim()) && (
        <div className="trello-add-form__actions">
          <button className="button trello-primary-button" disabled={busy || !title.trim()}>
            {busy ? "Adding…" : "Add card"}
          </button>
          {!defaultOpen && (
            <button
              className="trello-icon-button"
              type="button"
              aria-label="Cancel adding card"
              onClick={() => {
                setOpen(false);
                setTitle("");
                setError("");
              }}
            >
              ×
            </button>
          )}
        </div>
      )}
    </form>
  );
}
function ColumnMenu({
  snapshot,
  column,
  onChanged,
}: {
  snapshot: BoardSnapshot;
  column: BoardColumn;
  onChanged: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(column.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function rename(event: FormEvent) {
    event.preventDefault();
    const cleaned = name.trim();
    if (!cleaned) return;
    setBusy(true);
    setError("");
    try {
      await commandBoardColumn(snapshot.board.id, column.id, "rename", {
        expected_board_revision: snapshot.revision,
        name: cleaned,
        reason: "Renamed from board",
      });
      setOpen(false);
      setRenaming(false);
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Delete the empty list "${column.name}"?`)) return;
    setBusy(true);
    setError("");
    try {
      await commandBoardColumn(snapshot.board.id, column.id, "delete", {
        expected_board_revision: snapshot.revision,
        reason: "Deleted from board",
      });
      setOpen(false);
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="trello-list-menu-wrap">
      <button
        className="trello-list-menu-button"
        type="button"
        aria-label={`List actions for ${column.name}`}
        onClick={() => setOpen((value) => !value)}
      >
        •••
      </button>
      {open && (
        <div className="trello-list-menu">
          {renaming ? (
            <form onSubmit={rename}>
              <label>
                List name
                <input
                  autoFocus
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  maxLength={100}
                />
              </label>
              <div className="row-actions">
                <button className="button trello-primary-button" disabled={busy}>
                  Save
                </button>
                <button
                  className="button button--ghost"
                  type="button"
                  onClick={() => setRenaming(false)}
                >
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <>
              <button type="button" onClick={() => setRenaming(true)}>
                Rename list
              </button>
              {column.is_custom && (
                <button
                  className="trello-list-menu__danger"
                  type="button"
                  disabled={busy}
                  onClick={() => void remove()}
                >
                  Delete list
                </button>
              )}
            </>
          )}
          {error && <span className="trello-inline-error">{error}</span>}
        </div>
      )}
    </div>
  );
}

function ColumnView({
  snapshot,
  column,
  memberName,
  onOpen,
  onChanged,
  colorIndex,
}: {
  snapshot: BoardSnapshot;
  column: BoardColumn;
  memberName: (task: Task) => string;
  onOpen: (task: Task) => void;
  onChanged: () => Promise<void>;
  colorIndex: number;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `column:${column.id}` });
  const tone =
    column.state === "TODO"
      ? "todo"
      : column.state === "IN_PROGRESS"
        ? "progress"
        : column.state === "BLOCKED"
          ? "later"
          : column.state === "DONE"
            ? "done"
            : `custom-${colorIndex % 4}`;

  return (
    <div
      ref={setNodeRef}
      className={`column-drop trello-list-wrap ${isOver ? "column-drop--over" : ""}`}
    >
      <section
        className="kanban-column trello-list"
        data-state={column.state}
        data-column-id={column.id}
        data-tone={tone}
      >
        <header className="trello-list__header">
          <h2>{column.name}</h2>
          <div className="trello-list__header-actions">
            <span>{column.tasks.length}</span>
            <ColumnMenu snapshot={snapshot} column={column} onChanged={onChanged} />
          </div>
        </header>
        <SortableContext
          items={column.tasks.map((task) => task.id)}
          strategy={verticalListSortingStrategy}
        >
          <div className="kanban-column__body trello-list__body">
            {column.tasks.map((task) => (
              <SortableTaskCard
                key={task.id}
                task={task}
                memberName={memberName(task)}
                onOpen={() => onOpen(task)}
              />
            ))}
            {column.tasks.length === 0 && (
              <div className="trello-list__empty">Drop cards here</div>
            )}
          </div>
        </SortableContext>
        <InlineAddCard snapshot={snapshot} column={column} onChanged={onChanged} />
      </section>
    </div>
  );
}

function InboxRail({
  snapshot,
  column,
  memberName,
  onOpen,
  onChanged,
}: {
  snapshot: BoardSnapshot;
  column: BoardColumn;
  memberName: (task: Task) => string;
  onOpen: (task: Task) => void;
  onChanged: () => Promise<void>;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `column:${column.id}` });
  return (
    <aside
      ref={setNodeRef}
      className={`trello-inbox ${isOver ? "trello-inbox--over" : ""}`}
      data-state={column.state}
    >
      <header>
        <div><span aria-hidden="true">▣</span><h2>Inbox</h2></div>
        <span className="trello-inbox__count">{column.tasks.length}</span>
      </header>
      <InlineAddCard snapshot={snapshot} column={column} onChanged={onChanged} defaultOpen />
      <SortableContext
        items={column.tasks.map((task) => task.id)}
        strategy={verticalListSortingStrategy}
      >
        <div className="trello-inbox__cards">
          {column.tasks.map((task) => (
            <SortableTaskCard
              key={task.id}
              task={task}
              memberName={memberName(task)}
              onOpen={() => onOpen(task)}
            />
          ))}
          {column.tasks.length === 0 && (
            <div className="trello-inbox__empty">
              <strong>Capture it now.</strong>
              <span>Drag it onto the board when you are ready.</span>
            </div>
          )}
        </div>
      </SortableContext>
      <div className="trello-inbox__tip">◉ Consolidate your to-dos</div>
    </aside>
  );
}
function AddListControl({
  snapshot,
  onChanged,
}: {
  snapshot: BoardSnapshot;
  onChanged: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    const cleaned = name.trim();
    if (!cleaned) return;
    setBusy(true);
    setError("");
    try {
      await createBoardColumn(snapshot.board.id, cleaned);
      setName("");
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
      <button className="trello-add-list" type="button" onClick={() => setOpen(true)}>
        ＋ Add another list
      </button>
    );
  }

  return (
    <form className="trello-add-list trello-add-list--form" onSubmit={submit}>
      <input
        autoFocus
        value={name}
        onChange={(event) => setName(event.target.value)}
        placeholder="Enter list title…"
        maxLength={100}
        aria-label="New list title"
      />
      {error && <span className="trello-inline-error">{error}</span>}
      <div className="row-actions">
        <button className="button trello-primary-button" disabled={busy || !name.trim()}>
          {busy ? "Adding…" : "Add list"}
        </button>
        <button
          className="trello-icon-button"
          type="button"
          aria-label="Cancel adding list"
          onClick={() => {
            setOpen(false);
            setName("");
            setError("");
          }}
        >
          ×
        </button>
      </div>
    </form>
  );
}

function BoardDock() {
  return (
    <nav className="trello-dock" aria-label="Board shortcuts">
      <button
        type="button"
        onClick={() =>
          document.querySelector<HTMLTextAreaElement>(".trello-inbox textarea")?.focus()
        }
      >
        ▣ <span>Inbox</span>
      </button>
      <Link to="/calendar">▦ <span>Planner</span></Link>
      <span className="trello-dock__active">▥ <span>Board</span></span>
      <Link to="/">▤ <span>Switch boards</span></Link>
    </nav>
  );
}

export function BoardPage({ user }: { user: SessionUser }) {
  const { boardId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [snapshot, setSnapshot] = useState<BoardSnapshot | null>(null);
  const snapshotRevision = useRef<number | undefined>(undefined);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  useEffect(() => {
    document.body.classList.add("trello-board-active");
    return () => document.body.classList.remove("trello-board-active");
  }, []);

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
  const allTasks = useMemo(() => columns.flatMap((column) => column.tasks), [columns]);
  const taskById = useCallback(
    (id: string | null) => allTasks.find((task) => task.id === id) ?? null,
    [allTasks],
  );

  const query = (searchParams.get("q") ?? "").trim().toLowerCase();
  const memberName = useCallback(
    (task: Task) =>
      snapshot?.members.find((member) => member.id === task.current_owner_id)?.username ??
      "Unassigned",
    [snapshot],
  );
  const displayColumns = useMemo(() => {
    if (!query) return columns;
    return columns.map((column) => ({
      ...column,
      tasks: column.tasks.filter((task) => {
        const owner = memberName(task).toLowerCase();
        return (
          task.title.toLowerCase().includes(query) ||
          task.description.toLowerCase().includes(query) ||
          owner.includes(query)
        );
      }),
    }));
  }, [columns, memberName, query]);

  async function moveTask(task: Task, targetColumnId: string, targetPosition: number | null) {
    if (!snapshot) return;
    try {
      await commandTask(task.id, "move_task", {
        expected_version: task.row_version,
        expected_board_revision: snapshot.revision,
        target_column_id: targetColumnId,
        target_position: targetPosition,
        reason: "Moved on board",
      });
      setNotice("");
      snapshotRevision.current = undefined;
      await refresh();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        setNotice("This board changed while you were moving the card. I reloaded the latest version.");
        snapshotRevision.current = undefined;
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
    const overTask = taskById(overId);
    let targetColumnId: string | null = null;
    let targetPosition: number | null = null;

    if (overTask) {
      targetColumnId = overTask.column_id;
      targetPosition = overTask.position;
    } else if (overId.startsWith("column:")) {
      targetColumnId = overId.slice("column:".length);
      targetPosition =
        columns.find((column) => column.id === targetColumnId)?.tasks.length ?? null;
    }

    if (!targetColumnId) return;
    if (active.column_id !== targetColumnId || targetPosition !== active.position) {
      await moveTask(active, targetColumnId, targetPosition);
    }
  }

  if (!boardId) return <Navigate to="/" replace />;
  if (!snapshot) {
    return (
      <section>
        {error ? <Alert>{error}</Alert> : <div className="skeleton">Loading board…</div>}
      </section>
    );
  }

  const inbox = displayColumns.find((column) => column.state === "BACKLOG");
  const boardColumns = displayColumns.filter((column) => column.state !== "BACKLOG");
  const selected = taskById(selectedTaskId);

  async function changed() {
    snapshotRevision.current = undefined;
    await refresh();
  }

  return (
    <section className="trello-board-page">
      {error && <div className="trello-board-alert"><Alert>{error}</Alert></div>}
      {notice && <div className="trello-board-alert"><Alert kind="info">{notice}</Alert></div>}

      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragEnd={(event) => void onDragEnd(event)}
      >
        <div className="trello-workspace">
          {inbox && (
            <InboxRail
              snapshot={snapshot}
              column={inbox}
              memberName={memberName}
              onOpen={(task) => setSelectedTaskId(task.id)}
              onChanged={changed}
            />
          )}

          <main className="trello-canvas">
            <header className="trello-board-toolbar">
              <div className="trello-board-toolbar__title">
                <Link to="/" className="trello-board-toolbar__back" aria-label="Back to boards">
                  ‹
                </Link>
                <h1>{snapshot.board.name}</h1>
                <button type="button" aria-label="Board view">▥</button>
                <button type="button" aria-label="Board menu">⌄</button>
              </div>
              <div className="trello-board-toolbar__actions">
                <span className="trello-avatar">{user.username.slice(0, 2).toUpperCase()}</span>
                <span className="trello-shared">👥 Shared with everyone</span>
                <button type="button" aria-label="More board actions">•••</button>
              </div>
            </header>

            {query && (
              <div className="trello-search-status">
                Showing cards matching <strong>{searchParams.get("q")}</strong>
              </div>
            )}

            <div className="kanban-board trello-board-lists">
              {boardColumns.map((column, index) => (
                <ColumnView
                  key={column.id}
                  snapshot={snapshot}
                  column={column}
                  memberName={memberName}
                  onOpen={(task) => setSelectedTaskId(task.id)}
                  onChanged={changed}
                  colorIndex={index}
                />
              ))}
              <AddListControl snapshot={snapshot} onChanged={changed} />
            </div>
          </main>
        </div>
      </DndContext>

      <BoardDock />

      {selected && (
        <TaskDetailModal
          task={selected}
          snapshot={snapshot}
          currentUser={user}
          onClose={() => setSelectedTaskId(null)}
          onChanged={changed}
          onDeleted={async () => {
            setSelectedTaskId(null);
            await changed();
          }}
        />
      )}
    </section>
  );
}
