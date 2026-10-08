import {
  type CSSProperties,
  type RefObject,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { getBoards, getTasks } from "./api";
import type { BoardSummary, SessionUser, Task } from "./types";
import { errorMessage, taskDue } from "./ui";

function startOfDay(value: Date): Date {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate());
}

function addDays(value: Date, days: number): Date {
  const next = new Date(value);
  next.setDate(next.getDate() + days);
  return next;
}

function addMonths(value: Date, months: number): Date {
  const next = new Date(value.getFullYear(), value.getMonth(), 1);
  next.setMonth(next.getMonth() + months);
  return next;
}

function sameDate(left: Date, right: Date): boolean {
  return (
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate()
  );
}

function dateKey(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function taskDateKey(task: Task): string | null {
  const due = taskDue(task);
  if (!due) return null;
  const parsed = new Date(due);
  return Number.isNaN(parsed.valueOf()) ? null : dateKey(parsed);
}

function monthShort(value: Date): string {
  return new Intl.DateTimeFormat(undefined, { month: "short" }).format(value);
}

function monthYear(value: Date): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "long",
    year: "numeric",
  }).format(value);
}

function fullDate(value: Date): string {
  return new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(value);
}

function weekdayShort(value: Date): string {
  return new Intl.DateTimeFormat(undefined, { weekday: "short" }).format(value);
}

function monthDay(value: Date): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "long",
    day: "numeric",
  }).format(value);
}

function dueTime(task: Task): string {
  const due = taskDue(task);
  if (!due) return "";
  const parsed = new Date(due);
  if (Number.isNaN(parsed.valueOf())) return "";
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(parsed);
}

type FloatingPosition = {
  left: number;
  top: number;
  width: number;
  maxHeight: number;
};

function resolveFloatingPosition(
  trigger: HTMLElement,
  floating: HTMLElement,
  preferredWidth: number,
  preferredMaxHeight: number,
): FloatingPosition {
  const margin = 8;
  const gap = 6;
  const triggerRect = trigger.getBoundingClientRect();
  const floatingRect = floating.getBoundingClientRect();
  const width = Math.min(preferredWidth, Math.max(180, window.innerWidth - margin * 2));
  const measuredHeight = floatingRect.height || 1;
  const spaceBelow = window.innerHeight - triggerRect.bottom - margin - gap;
  const spaceAbove = triggerRect.top - margin - gap;
  const availableHeight = Math.max(spaceBelow, spaceAbove);
  const maxHeight = Math.max(120, Math.min(preferredMaxHeight, availableHeight));

  let left = triggerRect.left;
  left = Math.max(margin, Math.min(left, window.innerWidth - width - margin));

  let top = triggerRect.bottom + gap;
  if (measuredHeight > spaceBelow && spaceAbove > spaceBelow) {
    top = triggerRect.top - Math.min(measuredHeight, maxHeight) - gap;
  }
  top = Math.max(
    margin,
    Math.min(top, window.innerHeight - Math.min(measuredHeight, maxHeight) - margin),
  );

  return { left, top, width, maxHeight };
}

function relativeDayLabel(value: Date): string | null {
  const today = startOfDay(new Date());
  const difference = Math.round(
    (startOfDay(value).valueOf() - today.valueOf()) / (24 * 60 * 60 * 1000),
  );
  if (difference === -1) return "Yesterday";
  if (difference === 0) return "Today";
  if (difference === 1) return "Tomorrow";
  return null;
}

function CalendarIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="4" y="5.5" width="16" height="14" rx="2" />
      <path d="M8 3.5v4M16 3.5v4M4 9h16" />
    </svg>
  );
}

function MoreIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="5" cy="12" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="19" cy="12" r="1.4" fill="currentColor" stroke="none" />
    </svg>
  );
}

function ClockIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8.2" />
      <path d="M12 7.8v4.7l3.2 2" />
    </svg>
  );
}

function Toggle({
  checked,
  label,
  description,
  onChange,
}: {
  checked: boolean;
  label: string;
  description: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="trello-planner-toggle-row">
      <span>
        <strong>{label}</strong>
        <small>{description}</small>
      </span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <i aria-hidden="true" />
    </label>
  );
}

function PlannerDatePicker({
  anchor,
  onSelect,
  onClose,
  floatingRef,
  floatingStyle,
}: {
  anchor: Date;
  onSelect: (date: Date) => void;
  onClose: () => void;
  floatingRef: RefObject<HTMLDivElement | null>;
  floatingStyle: CSSProperties;
}) {
  const [visibleMonth, setVisibleMonth] = useState(
    () => new Date(anchor.getFullYear(), anchor.getMonth(), 1),
  );

  useEffect(() => {
    setVisibleMonth(new Date(anchor.getFullYear(), anchor.getMonth(), 1));
  }, [anchor]);

  const monthDays = useMemo(() => {
    const first = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth(), 1);
    const gridStart = addDays(first, -first.getDay());
    return Array.from({ length: 42 }, (_, index) => addDays(gridStart, index));
  }, [visibleMonth]);

  const today = startOfDay(new Date());

  return (
    <div
      ref={floatingRef}
      className="trello-planner-date-picker trello-planner-date-picker--floating"
      role="dialog"
      aria-label="Select date"
      style={floatingStyle}
    >
      <header>
        <strong>Select date</strong>
        <button type="button" aria-label="Close date picker" onClick={onClose}>×</button>
      </header>
      <div className="trello-planner-date-picker__month">
        <button
          type="button"
          aria-label="Previous month"
          onClick={() => setVisibleMonth((value) => addMonths(value, -1))}
        >
          ‹
        </button>
        <strong>{monthYear(visibleMonth)}</strong>
        <button
          type="button"
          aria-label="Next month"
          onClick={() => setVisibleMonth((value) => addMonths(value, 1))}
        >
          ›
        </button>
      </div>
      <div className="trello-planner-date-picker__weekdays" aria-hidden="true">
        {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((day) => (
          <span key={day}>{day}</span>
        ))}
      </div>
      <div className="trello-planner-date-picker__grid">
        {monthDays.map((day) => {
          const outside = day.getMonth() !== visibleMonth.getMonth();
          const selected = sameDate(day, anchor);
          const isToday = sameDate(day, today);
          return (
            <button
              key={dateKey(day)}
              type="button"
              aria-label={"Choose " + fullDate(day)}
              aria-selected={selected}
              className={[
                outside ? "is-outside" : "",
                selected ? "is-selected" : "",
                isToday ? "is-today" : "",
              ].filter(Boolean).join(" ")}
              onClick={() => {
                onSelect(startOfDay(day));
                onClose();
              }}
            >
              {day.getDate()}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function PlannerPanel({
  open,
  user,
  currentBoardId,
  refreshToken,
  onOpenTask,
}: {
  open: boolean;
  user: SessionUser;
  currentBoardId: string;
  refreshToken: number;
  onOpenTask: (task: Task) => void;
}) {
  const [anchor, setAnchor] = useState(() => startOfDay(new Date()));
  const [tasks, setTasks] = useState<Task[]>([]);
  const [boards, setBoards] = useState<BoardSummary[]>([]);
  const [error, setError] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [filterOpen, setFilterOpen] = useState(false);
  const [datePickerOpen, setDatePickerOpen] = useState(false);
  const [assignedToMe, setAssignedToMe] = useState(true);
  const [currentBoardCards, setCurrentBoardCards] = useState(true);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);
  const datePickerRef = useRef<HTMLDivElement | null>(null);
  const dateButtonRef = useRef<HTMLButtonElement | null>(null);
  const [menuPosition, setMenuPosition] = useState<FloatingPosition | null>(null);
  const [datePickerPosition, setDatePickerPosition] = useState<FloatingPosition | null>(null);

  const refresh = useCallback(async () => {
    if (!open) return;
    try {
      const [nextTasks, nextBoards] = await Promise.all([getTasks(), getBoards()]);
      setTasks(nextTasks);
      setBoards(nextBoards);
      setError("");
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    void refresh();
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 10_000);
    return () => window.clearInterval(interval);
  }, [open, refresh, refreshToken]);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (
        target &&
        !menuRef.current?.contains(target) &&
        !menuButtonRef.current?.contains(target)
      ) {
        setMenuOpen(false);
        setFilterOpen(false);
      }
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [menuOpen]);

  useEffect(() => {
    if (!datePickerOpen) return;
    const close = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (
        target &&
        !datePickerRef.current?.contains(target) &&
        !dateButtonRef.current?.contains(target)
      ) {
        setDatePickerOpen(false);
      }
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [datePickerOpen]);

  useLayoutEffect(() => {
    if (!menuOpen) {
      setMenuPosition(null);
      return;
    }

    const reposition = () => {
      const trigger = menuButtonRef.current;
      const floating = menuRef.current;
      if (!trigger || !floating) return;
      setMenuPosition(resolveFloatingPosition(trigger, floating, 310, 520));
    };

    reposition();
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    return () => {
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
    };
  }, [menuOpen, filterOpen]);

  useLayoutEffect(() => {
    if (!datePickerOpen) {
      setDatePickerPosition(null);
      return;
    }

    const reposition = () => {
      const trigger = dateButtonRef.current;
      const floating = datePickerRef.current;
      if (!trigger || !floating) return;
      setDatePickerPosition(resolveFloatingPosition(trigger, floating, 320, 560));
    };

    reposition();
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    return () => {
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
    };
  }, [datePickerOpen]);

  const boardNames = useMemo(
    () => new Map(boards.map((board) => [board.id, board.name])),
    [boards],
  );

  const eligibleTasks = useMemo(
    () =>
      tasks.filter((task) => {
        if (task.is_archived || task.is_cancelled || !taskDue(task)) return false;
        const matchesAssigned = assignedToMe && task.current_owner_id === user.id;
        const matchesCurrentBoard = currentBoardCards && task.board_id === currentBoardId;
        return matchesAssigned || matchesCurrentBoard;
      }),
    [assignedToMe, currentBoardCards, currentBoardId, tasks, user.id],
  );

  const days = useMemo(
    () => Array.from({ length: 7 }, (_, index) => addDays(anchor, index)),
    [anchor],
  );

  if (!open) return null;

  return (
    <aside className="trello-planner-panel" aria-label="Planner">
      <div className="trello-planner-toolbar">
        <div className="trello-planner-date-wrap">
          <button
            ref={dateButtonRef}
            className="trello-planner-month"
            type="button"
            aria-label="Planner month"
            aria-expanded={datePickerOpen}
            onClick={() => {
              setDatePickerOpen((value) => !value);
              setMenuOpen(false);
              setFilterOpen(false);
            }}
          >
            <CalendarIcon />
            <span>{monthShort(anchor)}</span>
            <svg className="trello-planner-chevron" viewBox="0 0 16 16" aria-hidden="true">
              <path d="m4 6 4 4 4-4" />
            </svg>
          </button>
          {datePickerOpen &&
            createPortal(
              <PlannerDatePicker
                anchor={anchor}
                onSelect={setAnchor}
                onClose={() => setDatePickerOpen(false)}
                floatingRef={datePickerRef}
                floatingStyle={{
                  left: datePickerPosition?.left ?? 0,
                  top: datePickerPosition?.top ?? 0,
                  width: datePickerPosition?.width ?? 320,
                  maxHeight: datePickerPosition?.maxHeight ?? 560,
                  visibility: datePickerPosition ? "visible" : "hidden",
                }}
              />,
              document.body,
            )}
        </div>
        <button
          className="trello-planner-nav"
          type="button"
          aria-label="Previous day"
          onClick={() => setAnchor((value) => addDays(value, -1))}
        >
          ‹
        </button>
        <button
          className="trello-planner-today"
          type="button"
          onClick={() => setAnchor(startOfDay(new Date()))}
        >
          Today
        </button>
        <button
          className="trello-planner-nav"
          type="button"
          aria-label="Next day"
          onClick={() => setAnchor((value) => addDays(value, 1))}
        >
          ›
        </button>

        <div className="trello-planner-menu-wrap">
          <button
            ref={menuButtonRef}
            className="trello-planner-more"
            type="button"
            aria-label="Planner options"
            aria-expanded={menuOpen}
            onClick={() => {
              setMenuOpen((value) => !value);
              setFilterOpen(false);
              setDatePickerOpen(false);
            }}
          >
            <MoreIcon />
          </button>

          {menuOpen &&
            createPortal(
              <div
                ref={menuRef}
                className={`trello-planner-menu trello-planner-menu--floating ${
                  filterOpen ? "trello-planner-filter" : ""
                }`}
                role={filterOpen ? "dialog" : "menu"}
                aria-label={filterOpen ? "Filter due cards shown" : "Planner menu"}
                style={{
                  left: menuPosition?.left ?? 0,
                  top: menuPosition?.top ?? 0,
                  width: menuPosition?.width ?? 310,
                  maxHeight: menuPosition?.maxHeight ?? 520,
                  visibility: menuPosition ? "visible" : "hidden",
                }}
              >
                {filterOpen ? (
                  <>
                    <header>
                      <button
                        type="button"
                        aria-label="Back to planner menu"
                        onClick={() => setFilterOpen(false)}
                      >
                        ‹
                      </button>
                      <strong>Filter due cards shown</strong>
                      <button
                        type="button"
                        aria-label="Close due card filter"
                        onClick={() => {
                          setMenuOpen(false);
                          setFilterOpen(false);
                        }}
                      >
                        ×
                      </button>
                    </header>
                    <div className="trello-planner-filter__body">
                      <Toggle
                        checked={assignedToMe}
                        label="Cards assigned to me"
                        description="Show cards due from all cards assigned to you"
                        onChange={setAssignedToMe}
                      />
                      <Toggle
                        checked={currentBoardCards}
                        label="Cards on this board"
                        description="Show due cards from the board currently open"
                        onChange={setCurrentBoardCards}
                      />
                    </div>
                  </>
                ) : (
                  <>
                    <header>
                      <strong>Menu</strong>
                      <button
                        type="button"
                        aria-label="Close planner menu"
                        onClick={() => setMenuOpen(false)}
                      >
                        ×
                      </button>
                    </header>
                    <button
                      className="trello-planner-menu__item"
                      type="button"
                      role="menuitem"
                      onClick={() => setFilterOpen(true)}
                    >
                      <ClockIcon />
                      <span>Filter due cards shown</span>
                    </button>
                  </>
                )}
              </div>,
              document.body,
            )}
        </div>
      </div>

      {error && <div className="trello-planner-error">{error}</div>}

      <div className="trello-planner-agenda">
        {days.map((day) => {
          const key = dateKey(day);
          const dayTasks = eligibleTasks
            .filter((task) => taskDateKey(task) === key)
            .sort((left, right) => {
              const leftDue = new Date(taskDue(left) ?? 0).valueOf();
              const rightDue = new Date(taskDue(right) ?? 0).valueOf();
              return leftDue - rightDue;
            });
          const relative = relativeDayLabel(day);
          return (
            <section className="trello-planner-day" key={key}>
              <h3>
                {relative && <strong>{relative}</strong>}
                <span>{weekdayShort(day)} {monthDay(day)}</span>
              </h3>
              {dayTasks.length === 0 ? (
                <p>Nothing planned{relative ? relative === "Today" ? " today" : "" : ""}</p>
              ) : (
                <div className="trello-planner-day__tasks">
                  {dayTasks.map((task) => (
                    <button
                      type="button"
                      key={task.id}
                      className="trello-planner-task"
                      onClick={() => onOpenTask(task)}
                    >
                      <span className="trello-planner-task__time">{dueTime(task)}</span>
                      <span className="trello-planner-task__copy">
                        <strong>{task.title}</strong>
                        <small>
                          {boardNames.get(task.board_id) ?? "Board"} · {task.column_name}
                        </small>
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </section>
          );
        })}
      </div>
    </aside>
  );
}
