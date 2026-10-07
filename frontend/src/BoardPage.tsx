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
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import {
  Link,
  Navigate,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";

import {
  ApiError,
  addBoardMembershipByUsername,
  commandBoardColumn,
  commandBoardMembership,
  commandTask,
  createBoardColumn,
  createTask,
  getBoardSnapshot,
  renameBoard,
} from "./api";
import { TaskDetailModal } from "./TaskActions";
import type {
  BoardColumn,
  BoardSnapshot,
  Role,
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
const PASTEL_COLOR_OPTIONS = [
  { key: "rose-1", label: "Rose light" }, { key: "rose-2", label: "Rose medium" }, { key: "rose-3", label: "Rose deep" },
  { key: "peach-1", label: "Peach light" }, { key: "peach-2", label: "Peach medium" }, { key: "peach-3", label: "Peach deep" },
  { key: "amber-1", label: "Butter light" }, { key: "amber-2", label: "Butter medium" }, { key: "amber-3", label: "Butter deep" },
  { key: "mint-1", label: "Mint light" }, { key: "mint-2", label: "Mint medium" }, { key: "mint-3", label: "Mint deep" },
  { key: "aqua-1", label: "Aqua light" }, { key: "aqua-2", label: "Aqua medium" }, { key: "aqua-3", label: "Aqua deep" },
  { key: "sky-1", label: "Sky light" }, { key: "sky-2", label: "Sky medium" }, { key: "sky-3", label: "Sky deep" },
  { key: "lavender-1", label: "Lavender light" }, { key: "lavender-2", label: "Lavender medium" }, { key: "lavender-3", label: "Lavender deep" },
  { key: "lilac-1", label: "Lilac light" }, { key: "lilac-2", label: "Lilac medium" }, { key: "lilac-3", label: "Lilac deep" },
  { key: "blush-1", label: "Blush light" }, { key: "blush-2", label: "Blush medium" }, { key: "blush-3", label: "Blush deep" },
  { key: "slate-1", label: "Cloud light" }, { key: "slate-2", label: "Cloud medium" }, { key: "slate-3", label: "Cloud deep" },
] as const;

const DARK_COLOR_OPTIONS = [
  { key: "navy1", label: "Navy rich" }, { key: "navy2", label: "Navy deep" }, { key: "navy3", label: "Midnight navy" },
  { key: "ocean1", label: "Ocean rich" }, { key: "ocean2", label: "Ocean deep" }, { key: "ocean3", label: "Deep sea" },
  { key: "teald1", label: "Teal rich" }, { key: "teald2", label: "Teal deep" }, { key: "teald3", label: "Dark teal" },
  { key: "forest1", label: "Forest rich" }, { key: "forest2", label: "Forest deep" }, { key: "forest3", label: "Pine" },
  { key: "olive1", label: "Olive rich" }, { key: "olive2", label: "Olive deep" }, { key: "olive3", label: "Moss" },
  { key: "rust1", label: "Rust rich" }, { key: "rust2", label: "Rust deep" }, { key: "rust3", label: "Burnt sienna" },
  { key: "wine1", label: "Wine rich" }, { key: "wine2", label: "Wine deep" }, { key: "wine3", label: "Burgundy" },
  { key: "plumd1", label: "Plum rich" }, { key: "plumd2", label: "Plum deep" }, { key: "plumd3", label: "Aubergine" },
  { key: "indigo1", label: "Indigo rich" }, { key: "indigo2", label: "Indigo deep" }, { key: "indigo3", label: "Night violet" },
  { key: "char1", label: "Charcoal soft" }, { key: "char2", label: "Charcoal deep" }, { key: "char3", label: "Graphite" },
] as const;

const LIST_TEXT_COLOR_OPTIONS = [
  { key: "", label: "Auto", sample: "Aa" },
  { key: "ink", label: "Ink", sample: "Aa" },
  { key: "charcoal", label: "Charcoal", sample: "Aa" },
  { key: "navy", label: "Navy", sample: "Aa" },
  { key: "plum", label: "Plum", sample: "Aa" },
  { key: "forest", label: "Forest", sample: "Aa" },
  { key: "white", label: "White", sample: "Aa" },
] as const;

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
  const [colorOpen, setColorOpen] = useState(true);
  const [textColorOpen, setTextColorOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [menuPosition, setMenuPosition] = useState<{ left: number; top: number; maxHeight: number } | null>(null);

  useEffect(() => {
    const handleOtherMenu = (event: Event) => {
      const detail = (event as CustomEvent<{ columnId: string }>).detail;
      if (detail?.columnId && detail.columnId !== column.id) {
        setOpen(false);
      }
    };
    window.addEventListener("trello:list-menu-open", handleOtherMenu as EventListener);
    return () => window.removeEventListener("trello:list-menu-open", handleOtherMenu as EventListener);
  }, [column.id]);

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (buttonRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [open]);

  useLayoutEffect(() => {
    if (!open) {
      setMenuPosition(null);
      return;
    }

    const reposition = () => {
      const button = buttonRef.current;
      const menu = menuRef.current;
      if (!button || !menu) return;

      const margin = 8;
      const gap = 6;
      const buttonRect = button.getBoundingClientRect();
      const menuRect = menu.getBoundingClientRect();
      const width = Math.min(menuRect.width || 286, window.innerWidth - margin * 2);
      const height = menuRect.height;

      let left = buttonRect.right - width;
      left = Math.max(margin, Math.min(left, window.innerWidth - width - margin));

      const spaceBelow = window.innerHeight - buttonRect.bottom - margin;
      const spaceAbove = buttonRect.top - margin;
      const maxHeight = Math.max(220, Math.min(680, Math.max(spaceBelow, spaceAbove)));
      let top = buttonRect.bottom + gap;

      if (height > spaceBelow && spaceAbove > spaceBelow) {
        top = Math.max(margin, buttonRect.top - Math.min(height, maxHeight) - gap);
      }
      top = Math.max(margin, Math.min(top, window.innerHeight - Math.min(height, maxHeight) - margin));

      setMenuPosition({ left, top, maxHeight });
    };

    reposition();
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    return () => {
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
    };
  }, [open, colorOpen, textColorOpen]);

  async function runCommand(
    command: "set_color" | "clear_color" | "set_text_color" | "clear_text_color" | "archive" | "archive_all_cards",
    payload: Record<string, unknown> = {},
  ) {
    setBusy(true);
    setError("");
    try {
      await commandBoardColumn(snapshot.board.id, column.id, command, {
        expected_board_revision: snapshot.revision,
        reason: "Updated from list actions",
        ...payload,
      });
      if (command === "archive" || command === "archive_all_cards") {
        setOpen(false);
      }
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function archiveList() {
    if (!column.is_custom) return;
    if (
      !window.confirm(
        `Archive the list "${column.name}"? The list and its cards will be hidden from the active board but preserved.`,
      )
    ) {
      return;
    }
    await runCommand("archive");
  }

  async function archiveAllCards() {
    if (
      !window.confirm(
        `Archive all ${column.tasks.length} card${column.tasks.length === 1 ? "" : "s"} in "${column.name}"? The list will remain visible.`,
      )
    ) {
      return;
    }
    await runCommand("archive_all_cards");
  }

  return (
    <div className="trello-list-menu-wrap">
      <button
        ref={buttonRef}
        className="trello-list-menu-button"
        type="button"
        aria-label={`List actions for ${column.name}`}
        onClick={() => {
          const next = !open;
          if (next) {
            window.dispatchEvent(
              new CustomEvent("trello:list-menu-open", { detail: { columnId: column.id } }),
            );
          }
          setOpen(next);
        }}
      >
        •••
      </button>
      {open &&
        createPortal(
          <div
            ref={menuRef}
            className="trello-list-menu trello-list-menu--actions trello-list-menu--floating"
            style={{
              left: menuPosition?.left ?? 0,
              top: menuPosition?.top ?? 0,
              maxHeight: menuPosition?.maxHeight ?? 680,
              visibility: menuPosition ? "visible" : "hidden",
            }}
          >
          <div className="trello-list-menu__title">
            <strong>List actions</strong>
            <button
              type="button"
              aria-label="Close list actions"
              onClick={() => setOpen(false)}
            >
              ×
            </button>
          </div>

          <button
            className="trello-list-menu__section-toggle"
            type="button"
            onClick={() => setColorOpen((value) => !value)}
          >
            <span>Change list color</span>
            <span aria-hidden="true">{colorOpen ? "⌃" : "⌄"}</span>
          </button>

          {colorOpen && (
            <div className="trello-list-colors" aria-label="List colors">
              <span className="trello-color-group-label">Pastel</span>
              <div className="trello-list-colors__grid trello-list-colors__grid--pastel">
                {PASTEL_COLOR_OPTIONS.map((option) => (
                  <button
                    key={option.key}
                    type="button"
                    className="trello-color-swatch"
                    data-color={option.key}
                    aria-label={option.label}
                    title={option.label}
                    aria-pressed={column.color === option.key}
                    disabled={busy}
                    onClick={() => void runCommand("set_color", { color: option.key })}
                  >
                    {column.color === option.key && <span>✓</span>}
                  </button>
                ))}
              </div>

              <span className="trello-color-group-label">Dark & rich</span>
              <div className="trello-list-colors__grid trello-list-colors__grid--dark">
                {DARK_COLOR_OPTIONS.map((option) => (
                  <button
                    key={option.key}
                    type="button"
                    className="trello-color-swatch trello-color-swatch--dark"
                    data-color={option.key}
                    aria-label={option.label}
                    title={option.label}
                    aria-pressed={column.color === option.key}
                    disabled={busy}
                    onClick={() => void runCommand("set_color", { color: option.key })}
                  >
                    {column.color === option.key && <span>✓</span>}
                  </button>
                ))}
              </div>

              <button
                className="trello-remove-color"
                type="button"
                disabled={busy || !column.color}
                onClick={() => void runCommand("clear_color")}
              >
                × Remove color
              </button>
            </div>
          )}

          <button
            className="trello-list-menu__section-toggle"
            type="button"
            onClick={() => setTextColorOpen((value) => !value)}
          >
            <span>Change text color</span>
            <span aria-hidden="true">{textColorOpen ? "⌃" : "⌄"}</span>
          </button>

          {textColorOpen && (
            <div className="trello-text-colors" aria-label="List text colors">
              {LIST_TEXT_COLOR_OPTIONS.map((option) => (
                <button
                  key={option.key || "auto"}
                  type="button"
                  className="trello-text-color-swatch"
                  data-text-color={option.key || "auto"}
                  aria-label={`${option.label} text`}
                  aria-pressed={column.text_color === option.key}
                  disabled={busy}
                  onClick={() =>
                    void runCommand(
                      option.key ? "set_text_color" : "clear_text_color",
                      option.key ? { text_color: option.key } : {},
                    )
                  }
                >
                  <span className="trello-text-color-swatch__sample">{option.sample}</span>
                  <span>{option.label}</span>
                  {column.text_color === option.key && <strong>✓</strong>}
                </button>
              ))}
            </div>
          )}

          <div className="trello-list-menu__divider" />

          <button
            className="trello-list-menu__archive"
            type="button"
            disabled={busy || !column.is_custom}
            title={
              column.is_custom
                ? "Archive this list"
                : "The five workflow lists are required and cannot be archived."
            }
            onClick={() => void archiveList()}
          >
            Archive this list
          </button>
          {!column.is_custom && (
            <span className="trello-list-menu__hint">
              Required workflow list — it cannot be archived.
            </span>
          )}

          <button
            className="trello-list-menu__archive"
            type="button"
            disabled={busy || column.tasks.length === 0}
            onClick={() => void archiveAllCards()}
          >
            Archive all cards in this list
          </button>

          {error && <span className="trello-inline-error">{error}</span>}
          </div>,
          document.body,
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
        data-color={column.color || undefined}
        data-text-color={column.text_color || undefined}
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
      data-color={column.color || undefined}
      data-text-color={column.text_color || undefined}
    >
      <header>
        <div><span aria-hidden="true">▣</span><h2>Inbox</h2></div>
        <div className="trello-inbox__header-actions">
          <span className="trello-inbox__count">{column.tasks.length}</span>
          <ColumnMenu snapshot={snapshot} column={column} onChanged={onChanged} />
        </div>
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

function BoardMembersPanel({
  snapshot,
  currentUser,
  open,
  startInAddMode,
  onClose,
  onChanged,
}: {
  snapshot: BoardSnapshot;
  currentUser: SessionUser;
  open: boolean;
  startInAddMode: boolean;
  onClose: () => void;
  onChanged: () => Promise<void>;
}) {
  const canManage = currentUser.is_admin || snapshot.membership.role === "MANAGER";
  const [username, setUsername] = useState("");
  const [role, setRole] = useState<Role>("MEMBER");
  const [busyUserId, setBusyUserId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const usernameRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open) {
      setUsername("");
      setRole("MEMBER");
      setAdding(false);
      setBusyUserId(null);
      setError("");
      return;
    }
    if (startInAddMode && canManage) {
      window.setTimeout(() => usernameRef.current?.focus(), 0);
    }
  }, [canManage, open, startInAddMode]);

  if (!open) return null;

  async function addMember(event: FormEvent) {
    event.preventDefault();
    const cleaned = username.trim();
    if (!canManage || !cleaned || adding) return;

    setAdding(true);
    setError("");
    try {
      await addBoardMembershipByUsername(snapshot.board.id, cleaned, role);
      setUsername("");
      setRole("MEMBER");
      await onChanged();
      window.setTimeout(() => usernameRef.current?.focus(), 0);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setAdding(false);
    }
  }

  async function changeRole(userId: string, currentRole: Role) {
    if (!canManage || busyUserId) return;
    setBusyUserId(userId);
    setError("");
    try {
      await commandBoardMembership(snapshot.board.id, userId, "set_role", {
        role: currentRole === "MANAGER" ? "MEMBER" : "MANAGER",
        reason: "Role changed from board members panel",
      });
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusyUserId(null);
    }
  }

  async function removeMember(userId: string, usernameToRemove: string) {
    if (!canManage || busyUserId || userId === currentUser.id) return;
    if (!window.confirm(`Remove ${usernameToRemove} from this board? They will immediately lose access.`)) {
      return;
    }

    setBusyUserId(userId);
    setError("");
    try {
      await commandBoardMembership(snapshot.board.id, userId, "remove", {
        reason: "Removed from board members panel",
      });
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusyUserId(null);
    }
  }

  return createPortal(
    <div
      className="trello-members-overlay"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section className="trello-members-panel" role="dialog" aria-modal="true" aria-label="Board members">
        <header className="trello-members-panel__header">
          <div>
            <strong>Board members</strong>
            <span>🔒 Private board · {snapshot.members.length} active member{snapshot.members.length === 1 ? "" : "s"}</span>
          </div>
          <button type="button" aria-label="Close board members" onClick={onClose}>×</button>
        </header>

        {canManage && (
          <form className="trello-members-add" onSubmit={addMember}>
            <label>
              Add user
              <input
                ref={usernameRef}
                aria-label="Username to add"
                value={username}
                maxLength={150}
                placeholder="Enter exact username"
                disabled={adding}
                onChange={(event) => setUsername(event.target.value)}
              />
            </label>
            <label>
              Access
              <select
                aria-label="Board role"
                value={role}
                disabled={adding}
                onChange={(event) => setRole(event.target.value as Role)}
              >
                <option value="MEMBER">Member</option>
                <option value="MANAGER">Manager</option>
              </select>
            </label>
            <button
              className="trello-members-add__button"
              type="submit"
              disabled={adding || !username.trim()}
            >
              {adding ? "Adding…" : "Add to board"}
            </button>
          </form>
        )}

        {error && <div className="trello-members-error">{error}</div>}

        <div className="trello-members-list">
          {snapshot.members.map((member) => {
            const isCurrentUser = member.id === currentUser.id;
            const isBusy = busyUserId === member.id;
            return (
              <div className="trello-member-row" key={member.id}>
                <span className="trello-member-avatar">
                  {member.username.slice(0, 2).toUpperCase()}
                </span>
                <div className="trello-member-row__identity">
                  <strong>{member.username}{isCurrentUser ? " (you)" : ""}</strong>
                  <span>{member.role === "MANAGER" ? "Board manager" : "Member"}</span>
                </div>
                {canManage && (
                  <div className="trello-member-row__actions">
                    <button
                      type="button"
                      disabled={isBusy}
                      onClick={() => void changeRole(member.id, member.role)}
                    >
                      {member.role === "MANAGER" ? "Make member" : "Make manager"}
                    </button>
                    {!isCurrentUser && (
                      <button
                        className="trello-member-remove"
                        type="button"
                        disabled={isBusy}
                        onClick={() => void removeMember(member.id, member.username)}
                      >
                        Remove
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {!canManage && (
          <p className="trello-members-note">
            Only a board manager or administrator can add or remove board members.
          </p>
        )}
      </section>
    </div>,
    document.body,
  );
}

function BoardTitleEditor({
  snapshot,
  canEdit,
  onChanged,
}: {
  snapshot: BoardSnapshot;
  canEdit: boolean;
  onChanged: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(snapshot.board.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!editing) setName(snapshot.board.name);
  }, [editing, snapshot.board.name]);

  function cancel() {
    setName(snapshot.board.name);
    setError("");
    setEditing(false);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const cleaned = name.trim();
    if (!cleaned || cleaned === snapshot.board.name || busy) {
      if (cleaned === snapshot.board.name) setEditing(false);
      return;
    }

    setBusy(true);
    setError("");
    try {
      await renameBoard(snapshot.board.id, cleaned, snapshot.revision);
      setEditing(false);
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
      if (caught instanceof ApiError && caught.status === 409) {
        await onChanged();
      }
    } finally {
      setBusy(false);
    }
  }

  if (!canEdit || !editing) {
    return (
      <div className="trello-board-title-display">
        <h1
          className={canEdit ? "trello-board-title-display__editable" : undefined}
          onDoubleClick={() => canEdit && setEditing(true)}
          title={canEdit ? "Double-click to rename board" : undefined}
        >
          {snapshot.board.name}
        </h1>
        {canEdit && (
          <button
            type="button"
            className="trello-board-title-edit"
            aria-label="Edit board name"
            title="Edit board name"
            onClick={() => setEditing(true)}
          >
            ✎
          </button>
        )}
      </div>
    );
  }

  return (
    <form className="trello-board-title-form" onSubmit={submit}>
      <input
        autoFocus
        aria-label="Board name"
        value={name}
        maxLength={200}
        disabled={busy}
        onChange={(event) => setName(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            cancel();
          }
        }}
        onFocus={(event) => event.currentTarget.select()}
      />
      <button
        className="trello-board-title-save"
        type="submit"
        aria-label="Save board name"
        disabled={busy || !name.trim()}
      >
        {busy ? "…" : "✓"}
      </button>
      <button
        className="trello-board-title-cancel"
        type="button"
        aria-label="Cancel board name edit"
        disabled={busy}
        onClick={cancel}
      >
        ×
      </button>
      {error && <span className="trello-board-title-error">{error}</span>}
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
  const [membersOpen, setMembersOpen] = useState(false);
  const [memberPanelAddMode, setMemberPanelAddMode] = useState(false);

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
    setMembersOpen(false);
    setMemberPanelAddMode(false);
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
                <BoardTitleEditor
                  snapshot={snapshot}
                  canEdit={user.is_admin}
                  onChanged={changed}
                />
                <button type="button" aria-label="Board view">▥</button>
                <button type="button" aria-label="Board menu">⌄</button>
              </div>
              <div className="trello-board-toolbar__actions">
                <span className="trello-avatar">{user.username.slice(0, 2).toUpperCase()}</span>
                <button
                  className="trello-shared trello-board-members-button"
                  type="button"
                  aria-label="View board members"
                  onClick={() => {
                    setMemberPanelAddMode(false);
                    setMembersOpen(true);
                  }}
                >
                  🔒 {snapshot.members.length} member{snapshot.members.length === 1 ? "" : "s"}
                </button>
                {(user.is_admin || snapshot.membership.role === "MANAGER") && (
                  <button
                    className="trello-board-add-user"
                    type="button"
                    aria-label="Add user to board"
                    onClick={() => {
                      setMemberPanelAddMode(true);
                      setMembersOpen(true);
                    }}
                  >
                    ＋ Add user
                  </button>
                )}
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

      <BoardMembersPanel
        snapshot={snapshot}
        currentUser={user}
        open={membersOpen}
        startInAddMode={memberPanelAddMode}
        onClose={() => {
          setMembersOpen(false);
          setMemberPanelAddMode(false);
        }}
        onChanged={changed}
      />

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
