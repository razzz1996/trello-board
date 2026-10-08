import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react";

import type { BoardColumn, BoardSnapshot, Task } from "./types";
import { formatDateTime, taskDue } from "./ui";

export type BoardViewKey = "board" | "table" | "calendar" | "dashboard" | "timeline";

const VIEW_OPTIONS: Array<{ key: BoardViewKey; label: string }> = [
  { key: "board", label: "Board" },
  { key: "table", label: "Table" },
  { key: "calendar", label: "Calendar" },
  { key: "dashboard", label: "Dashboard" },
  { key: "timeline", label: "Timeline" },
];

export function BoardViewIcon({
  view,
  size = 18,
}: {
  view: BoardViewKey;
  size?: number;
}) {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };

  if (view === "board") {
    return (
      <svg {...common}>
        <rect x="3.25" y="4" width="4.5" height="16" rx="1.2" />
        <rect x="9.75" y="4" width="4.5" height="10.5" rx="1.2" />
        <rect x="16.25" y="4" width="4.5" height="13.5" rx="1.2" />
      </svg>
    );
  }
  if (view === "table") {
    return (
      <svg {...common}>
        <rect x="3" y="4.5" width="18" height="15" rx="1.5" />
        <path d="M3 9.5h18M8.8 4.5v15" />
      </svg>
    );
  }
  if (view === "calendar") {
    return (
      <svg {...common}>
        <rect x="3.5" y="5" width="17" height="15.5" rx="2" />
        <path d="M7.5 3.5v3M16.5 3.5v3M3.5 9h17" />
      </svg>
    );
  }
  if (view === "dashboard") {
    return (
      <svg {...common}>
        <path d="M4.2 16.8a8.2 8.2 0 1 1 15.6 0" />
        <path d="M12 12l4.3-4.3M7.6 15.3h.01M16.4 15.3h.01" />
        <circle cx="12" cy="12" r="1.2" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <path d="M5 5h14M5 10h9M5 15h14M5 20h9" />
      <circle cx="3" cy="5" r=".65" fill="currentColor" stroke="none" />
      <circle cx="3" cy="10" r=".65" fill="currentColor" stroke="none" />
      <circle cx="3" cy="15" r=".65" fill="currentColor" stroke="none" />
      <circle cx="3" cy="20" r=".65" fill="currentColor" stroke="none" />
    </svg>
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

function startOfDay(value: Date): Date {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate());
}

function addDays(value: Date, days: number): Date {
  const next = new Date(value);
  next.setDate(next.getDate() + days);
  return next;
}

function sameDate(a: Date, b: Date): boolean {
  return dateKey(a) === dateKey(b);
}

function monthLabel(value: Date): string {
  return new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric" }).format(value);
}

function shortDay(value: Date): string {
  return new Intl.DateTimeFormat(undefined, { weekday: "short" }).format(value);
}

function dueStatus(task: Task): "Complete" | "Due soon" | "Due later" | "Overdue" | "No due date" {
  if (task.column_state === "DONE") return "Complete";
  const due = taskDue(task);
  if (!due) return "No due date";
  const dueAt = new Date(due).valueOf();
  if (Number.isNaN(dueAt)) return "No due date";
  const delta = dueAt - Date.now();
  if (delta < 0) return "Overdue";
  if (delta <= 3 * 24 * 60 * 60 * 1000) return "Due soon";
  return "Due later";
}

function LabelPills({ task }: { task: Task }) {
  const labels = task.labels ?? [];
  if (!labels.length) return <span className="board-view-muted">·</span>;
  return (
    <div className="board-view-label-pills">
      {labels.map((label) => (
        <span
          key={label.id}
          data-label-color={label.color}
          title={label.description || label.name || label.color}
        >
          {label.name || label.color}
        </span>
      ))}
    </div>
  );
}

export function BoardViewSwitcher({
  value,
  open,
  onOpenChange,
  onChange,
}: {
  value: BoardViewKey;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChange: (view: BoardViewKey) => void;
}) {
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (target && !wrapRef.current?.contains(target)) onOpenChange(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open, onOpenChange]);

  return (
    <div className="trello-view-switcher" ref={wrapRef}>
      <button
        className="trello-view-switcher__trigger"
        type="button"
        aria-label="Change board view"
        aria-expanded={open}
        onClick={() => onOpenChange(!open)}
      >
        <BoardViewIcon view={value} size={18} />
      </button>
      {open && (
        <div className="trello-view-switcher__menu" role="menu" aria-label="Board views">
          <header>
            <strong>Views</strong>
            <button type="button" aria-label="Close views" onClick={() => onOpenChange(false)}>×</button>
          </header>
          <div className="trello-view-switcher__options">
            {VIEW_OPTIONS.map((option) => (
              <button
                key={option.key}
                type="button"
                role="menuitem"
                aria-current={value === option.key ? "page" : undefined}
                onClick={() => {
                  onChange(option.key);
                  onOpenChange(false);
                }}
              >
                <span><BoardViewIcon view={option.key} size={18} /></span>
                <strong>{option.label}</strong>
                {value === option.key && <b>✓</b>}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function TableView({
  columns,
  memberName,
  onOpen,
  onAdd,
  onClose,
}: {
  columns: BoardColumn[];
  memberName: (task: Task) => string;
  onOpen: (task: Task) => void;
  onAdd: () => void;
  onClose: () => void;
}) {
  const rows = useMemo(
    () =>
      columns.flatMap((column) =>
        column.tasks.map((task) => ({ task, list: column.name })),
      ),
    [columns],
  );

  return (
    <section className="trello-alt-view trello-table-view" aria-label="Table view">
      <button className="trello-alt-view__close" type="button" aria-label="Close table view" onClick={onClose}>×</button>
      <div className="trello-table-scroll">
        <table>
          <thead>
            <tr>
              <th>Card</th>
              <th>List</th>
              <th>Labels</th>
              <th>Members</th>
              <th>Due date</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ task, list }) => (
              <tr key={task.id} onDoubleClick={() => onOpen(task)}>
                <td>
                  <button type="button" onClick={() => onOpen(task)}>{task.title}</button>
                </td>
                <td>{list}</td>
                <td><LabelPills task={task} /></td>
                <td>{memberName(task)}</td>
                <td>
                  {taskDue(task) ? (
                    <span className={dueStatus(task) === "Overdue" ? "board-due-overdue" : ""}>
                      {formatDateTime(taskDue(task))}
                    </span>
                  ) : (
                    <span className="board-view-muted">·</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <div className="board-view-empty">No cards on this board yet.</div>}
      </div>
      <button className="trello-alt-view__add" type="button" onClick={onAdd}>＋ Add</button>
    </section>
  );
}

function CalendarView({
  tasks,
  onOpen,
  onAdd,
  onClose,
}: {
  tasks: Task[];
  onOpen: (task: Task) => void;
  onAdd: () => void;
  onClose: () => void;
}) {
  const [month, setMonth] = useState(() => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), 1);
  });
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const gridStart = addDays(first, -first.getDay());
  const days = Array.from({ length: 42 }, (_, index) => addDays(gridStart, index));
  const grouped = useMemo(() => {
    const result = new Map<string, Task[]>();
    for (const task of tasks) {
      const key = taskDateKey(task);
      if (!key) continue;
      const bucket = result.get(key) ?? [];
      bucket.push(task);
      result.set(key, bucket);
    }
    return result;
  }, [tasks]);
  const unscheduled = tasks.filter((task) => !taskDue(task)).length;

  return (
    <section className="trello-alt-view trello-calendar-view" aria-label="Calendar view">
      <button className="trello-alt-view__close" type="button" aria-label="Close calendar view" onClick={onClose}>×</button>
      <div className="trello-calendar-controls">
        <button type="button" className="trello-calendar-month">{monthLabel(month)}⌄</button>
        <button
          type="button"
          aria-label="Previous month"
          onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}
        >
          ‹
        </button>
        <button
          type="button"
          onClick={() => {
            const now = new Date();
            setMonth(new Date(now.getFullYear(), now.getMonth(), 1));
          }}
        >
          Today
        </button>
        <button
          type="button"
          aria-label="Next month"
          onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}
        >
          ›
        </button>
        <span className="trello-calendar-mode">Month⌄</span>
        <span className="trello-calendar-unscheduled">{unscheduled} not scheduled</span>
      </div>
      <div className="trello-calendar-grid">
        {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((label) => (
          <div className="trello-calendar-weekday" key={label}>{label}</div>
        ))}
        {days.map((day) => {
          const key = dateKey(day);
          const dayTasks = grouped.get(key) ?? [];
          const outside = day.getMonth() !== month.getMonth();
          return (
            <div
              key={key}
              className={`trello-calendar-day${outside ? " is-outside" : ""}${sameDate(day, new Date()) ? " is-today" : ""}`}
            >
              <strong>{day.getDate()}</strong>
              <div className="trello-calendar-day__tasks">
                {dayTasks.slice(0, 4).map((task) => (
                  <button key={task.id} type="button" onClick={() => onOpen(task)}>
                    {task.title}
                  </button>
                ))}
                {dayTasks.length > 4 && <span>＋{dayTasks.length - 4} more</span>}
              </div>
            </div>
          );
        })}
      </div>
      <button className="trello-alt-view__add" type="button" onClick={onAdd}>＋ Add</button>
    </section>
  );
}

function DashboardBars({
  rows,
  toneByLabel,
}: {
  rows: Array<{ label: string; value: number }>;
  toneByLabel?: (label: string) => string;
}) {
  const max = Math.max(1, ...rows.map((row) => row.value));
  return (
    <div className="trello-dashboard-bars">
      {rows.map((row) => (
        <div className="trello-dashboard-bar" key={row.label}>
          <span>{row.value}</span>
          <div className="trello-dashboard-bar__track">
            <i
              className={toneByLabel?.(row.label) ?? ""}
              style={{ height: `${Math.max(row.value ? 8 : 0, (row.value / max) * 100)}%` }}
            />
          </div>
          <small title={row.label}>{row.label}</small>
        </div>
      ))}
    </div>
  );
}

function DashboardView({
  snapshot,
  columns,
  tasks,
  memberName,
  onClose,
}: {
  snapshot: BoardSnapshot;
  columns: BoardColumn[];
  tasks: Task[];
  memberName: (task: Task) => string;
  onClose: () => void;
}) {
  const listRows = columns.map((column) => ({ label: column.name, value: column.tasks.length }));
  const dueLabels = ["Complete", "Due soon", "Due later", "Overdue", "No due date"];
  const dueRows = dueLabels.map((label) => ({
    label,
    value: tasks.filter((task) => dueStatus(task) === label).length,
  }));
  const members = Array.from(new Set(tasks.map(memberName)));
  const memberRows = members.map((name) => ({
    label: name,
    value: tasks.filter((task) => memberName(task) === name).length,
  }));
  const labelRows = (snapshot.labels ?? []).map((label) => ({
    label: label.name || label.description || label.color,
    value: tasks.filter((task) => (task.labels ?? []).some((item) => item.id === label.id)).length,
  }));
  const hasLabels = labelRows.some((row) => row.value > 0);

  return (
    <section className="trello-alt-view trello-dashboard-view" aria-label="Dashboard view">
      <button className="trello-alt-view__close" type="button" aria-label="Close dashboard view" onClick={onClose}>×</button>
      <div className="trello-dashboard-grid">
        <article>
          <h3>Cards per list</h3>
          <DashboardBars rows={listRows} />
        </article>
        <article>
          <h3>Cards per due date</h3>
          <DashboardBars
            rows={dueRows}
            toneByLabel={(label) => label === "Overdue" ? "is-danger" : label === "Complete" ? "is-complete" : ""}
          />
        </article>
        <article>
          <h3>Cards per member</h3>
          <DashboardBars rows={memberRows.length ? memberRows : [{ label: "Unassigned", value: 0 }]} />
        </article>
        <article>
          <h3>Cards per label</h3>
          {hasLabels ? (
            <DashboardBars rows={labelRows} />
          ) : (
            <div className="trello-dashboard-empty">
              <span>🏷️</span>
              <strong>No cards with labels yet.</strong>
              <small>Add labels to cards to track work by category.</small>
            </div>
          )}
        </article>
      </div>
    </section>
  );
}

type TimelineScale = "day" | "week" | "month" | "quarter" | "year";
type TimelineGrouping = "list" | "member" | "label" | "none";

type TimelinePeriod = {
  key: string;
  date: Date;
  kind: "day" | "month";
  top: string;
  bottom: string;
  isToday: boolean;
  isCurrentMonth: boolean;
};

type TimelineGroup = {
  key: string;
  label: string;
  secondary?: string;
  avatar?: string;
  color?: string;
  tasks: Task[];
};

function addMonths(value: Date, months: number): Date {
  const next = new Date(value.getFullYear(), value.getMonth(), 1);
  next.setMonth(next.getMonth() + months);
  return next;
}

function TimelineDropdown<T extends string>({
  value,
  options,
  ariaLabel,
  onChange,
}: {
  value: T;
  options: Array<{ value: T; label: string }>;
  ariaLabel: string;
  onChange: (value: T) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const current = options.find((option) => option.value === value) ?? options[0];

  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (target && !ref.current?.contains(target)) setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);

  return (
    <div className="trello-timeline-dropdown" ref={ref}>
      <button
        type="button"
        aria-label={ariaLabel}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span>{current.label}</span>
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="m4 6 4 4 4-4" />
        </svg>
      </button>
      {open && (
        <div className="trello-timeline-dropdown__menu" role="menu">
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              role="menuitemradio"
              aria-checked={option.value === value}
              onClick={() => {
                onChange(option.value);
                setOpen(false);
              }}
            >
              <span>{option.label}</span>
              {option.value === value && <b>✓</b>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function timelinePeriods(scale: TimelineScale, anchor: Date): TimelinePeriod[] {
  const today = startOfDay(new Date());
  if (scale === "quarter" || scale === "year") {
    const count = scale === "quarter" ? 5 : 14;
    const before = scale === "quarter" ? 2 : 8;
    const start = addMonths(anchor, -before);
    return Array.from({ length: count }, (_, index) => {
      const date = addMonths(start, index);
      return {
        key: `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`,
        date,
        kind: "month" as const,
        top: new Intl.DateTimeFormat(undefined, { month: "long" }).format(date).toUpperCase(),
        bottom: "",
        isToday:
          date.getFullYear() === today.getFullYear() &&
          date.getMonth() === today.getMonth(),
        isCurrentMonth:
          date.getFullYear() === anchor.getFullYear() &&
          date.getMonth() === anchor.getMonth(),
      };
    });
  }

  const count = scale === "day" ? 3 : scale === "week" ? 14 : 28;
  const before = scale === "day" ? 1 : scale === "week" ? 4 : 10;
  const start = addDays(startOfDay(anchor), -before);
  return Array.from({ length: count }, (_, index) => {
    const date = addDays(start, index);
    return {
      key: dateKey(date),
      date,
      kind: "day" as const,
      top: shortDay(date).toUpperCase(),
      bottom: String(date.getDate()),
      isToday: sameDate(date, today),
      isCurrentMonth:
        date.getFullYear() === anchor.getFullYear() &&
        date.getMonth() === anchor.getMonth(),
    };
  });
}

function timelineTaskMatches(task: Task, period: TimelinePeriod): boolean {
  const due = taskDue(task);
  if (!due) return false;
  const date = new Date(due);
  if (Number.isNaN(date.valueOf())) return false;
  if (period.kind === "month") {
    return (
      date.getFullYear() === period.date.getFullYear() &&
      date.getMonth() === period.date.getMonth()
    );
  }
  return sameDate(date, period.date);
}

function timelineGroups(
  grouping: TimelineGrouping,
  columns: BoardColumn[],
  snapshot: BoardSnapshot,
  memberName: (task: Task) => string,
): TimelineGroup[] {
  const tasks = columns.flatMap((column) => column.tasks);

  if (grouping === "none") {
    return [{ key: "all", label: "", tasks }];
  }

  if (grouping === "list") {
    return columns.map((column) => ({
      key: column.id,
      label: column.name,
      tasks: column.tasks,
    }));
  }

  if (grouping === "member") {
    const memberNames = snapshot.members.map((member) => member.username);
    const groups = memberNames.map((name) => ({
      key: `member:${name}`,
      label: name,
      avatar: name.slice(0, 2).toUpperCase(),
      tasks: tasks.filter((task) => memberName(task) === name),
    }));
    groups.push({
      key: "member:none",
      label: "No members",
      avatar: "○",
      tasks: tasks.filter((task) => {
        const owner = memberName(task);
        return owner === "Unassigned" || owner === "No members";
      }),
    });
    return groups;
  }

  const labels = snapshot.labels ?? [];
  const groups: TimelineGroup[] = labels.map((label) => ({
    key: `label:${label.id}`,
    label: label.name || label.description || "",
    color: label.color,
    tasks: tasks.filter((task) =>
      (task.labels ?? []).some((taskLabel) => taskLabel.id === label.id),
    ),
  }));
  groups.push({
    key: "label:none",
    label: "No labels",
    color: "none",
    tasks: tasks.filter((task) => !(task.labels ?? []).length),
  });
  return groups;
}

function TimelineView({
  snapshot,
  columns,
  memberName,
  onOpen,
  onAdd,
  onClose,
}: {
  snapshot: BoardSnapshot;
  columns: BoardColumn[];
  memberName: (task: Task) => string;
  onOpen: (task: Task) => void;
  onAdd: () => void;
  onClose: () => void;
}) {
  const [anchor, setAnchor] = useState(() => startOfDay(new Date()));
  const [scale, setScale] = useState<TimelineScale>("week");
  const [grouping, setGrouping] = useState<TimelineGrouping>("list");

  const periods = useMemo(() => timelinePeriods(scale, anchor), [scale, anchor]);
  const groups = useMemo(
    () => timelineGroups(grouping, columns, snapshot, memberName),
    [grouping, columns, snapshot, memberName],
  );

  const moveAnchor = (direction: -1 | 1) => {
    if (scale === "day") setAnchor((value) => addDays(value, direction));
    else if (scale === "week") setAnchor((value) => addDays(value, direction * 7));
    else if (scale === "month") setAnchor((value) => addMonths(value, direction));
    else if (scale === "quarter") setAnchor((value) => addMonths(value, direction * 3));
    else setAnchor((value) => addMonths(value, direction * 12));
  };

  const headerLabel =
    scale === "quarter" || scale === "year"
      ? String(anchor.getFullYear())
      : monthLabel(anchor);

  const gridStyle = {
    "--timeline-columns": String(periods.length),
    "--timeline-gutter": grouping === "none" ? "0px" : "190px",
    "--timeline-cell-min":
      scale === "day"
        ? "330px"
        : scale === "week"
          ? "96px"
          : scale === "month"
            ? "50px"
            : scale === "quarter"
              ? "260px"
              : "105px",
  } as CSSProperties;

  return (
    <section className="trello-alt-view trello-timeline-view" aria-label="Timeline view">
      <div className="trello-timeline-controls">
        <button type="button" className="trello-calendar-month" aria-label="Timeline period">
          {headerLabel}
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg>
        </button>
        <button type="button" aria-label="Previous period" onClick={() => moveAnchor(-1)}>‹</button>
        <button type="button" onClick={() => setAnchor(startOfDay(new Date()))}>Today</button>
        <button type="button" aria-label="Next period" onClick={() => moveAnchor(1)}>›</button>
        <TimelineDropdown
          value={scale}
          ariaLabel="Timeline scale"
          options={[
            { value: "day", label: "Day" },
            { value: "week", label: "Week" },
            { value: "month", label: "Month" },
            { value: "quarter", label: "Quarter" },
            { value: "year", label: "Year" },
          ]}
          onChange={setScale}
        />
        <TimelineDropdown
          value={grouping}
          ariaLabel="Timeline grouping"
          options={[
            { value: "list", label: "List" },
            { value: "member", label: "Member" },
            { value: "label", label: "Label" },
            { value: "none", label: "None" },
          ]}
          onChange={setGrouping}
        />
        <button className="trello-timeline-close" type="button" aria-label="Close timeline view" onClick={onClose}>×</button>
      </div>

      <div className="trello-timeline-scroll">
        <div
          className={`trello-timeline-grid trello-timeline-grid--${scale}${grouping === "none" ? " is-ungrouped" : ""}`}
          style={gridStyle}
        >
          {grouping !== "none" && <div className="trello-timeline-corner" />}
          {periods.map((period) => (
            <div
              key={period.key}
              className={`trello-timeline-day-head${period.isToday ? " is-today" : ""}${period.isCurrentMonth ? " is-current-period" : ""}`}
            >
              <small>{period.top}</small>
              {period.bottom && <strong>{period.bottom}</strong>}
            </div>
          ))}

          {groups.map((group) => {
            const unscheduled = group.tasks.filter((task) => !taskDue(task)).length;
            return [
              grouping !== "none" ? (
                <div className="trello-timeline-list-name" key={`name:${group.key}`}>
                  <div className="trello-timeline-group-title">
                    {grouping === "member" && (
                      <span className={`trello-timeline-group-avatar${group.label === "No members" ? " is-empty" : ""}`}>
                        {group.avatar}
                      </span>
                    )}
                    {grouping === "label" && (
                      <span
                        className="trello-timeline-group-label"
                        data-label-color={group.color === "none" ? undefined : group.color}
                      />
                    )}
                    <strong>{group.label}</strong>
                  </div>
                  {unscheduled > 0 && (
                    <small>
                      ({unscheduled}) Not scheduled
                      <button type="button" aria-label={`Add card to ${group.label || "timeline"}`} onClick={onAdd}>＋</button>
                    </small>
                  )}
                </div>
              ) : null,
              ...periods.map((period) => {
                const items = group.tasks.filter((task) => timelineTaskMatches(task, period));
                return (
                  <div
                    className={`trello-timeline-cell${period.isToday ? " is-today" : ""}`}
                    key={`${group.key}:${period.key}`}
                  >
                    {items.map((task) => (
                      <button key={task.id} type="button" onClick={() => onOpen(task)}>
                        {task.title}
                      </button>
                    ))}
                  </div>
                );
              }),
            ];
          })}
        </div>
      </div>
      <button className="trello-alt-view__add" type="button" onClick={onAdd}>＋ Add</button>
    </section>
  );
}

export function BoardAlternateView({
  view,
  snapshot,
  columns,
  memberName,
  onOpen,
  onAdd,
  onClose,
}: {
  view: Exclude<BoardViewKey, "board">;
  snapshot: BoardSnapshot;
  columns: BoardColumn[];
  memberName: (task: Task) => string;
  onOpen: (task: Task) => void;
  onAdd: () => void;
  onClose: () => void;
}) {
  const tasks = useMemo(() => columns.flatMap((column) => column.tasks), [columns]);

  if (view === "table") {
    return (
      <TableView
        columns={columns}
        memberName={memberName}
        onOpen={onOpen}
        onAdd={onAdd}
        onClose={onClose}
      />
    );
  }
  if (view === "calendar") {
    return <CalendarView tasks={tasks} onOpen={onOpen} onAdd={onAdd} onClose={onClose} />;
  }
  if (view === "dashboard") {
    return (
      <DashboardView
        snapshot={snapshot}
        columns={columns}
        tasks={tasks}
        memberName={memberName}
        onClose={onClose}
      />
    );
  }
  return (
    <TimelineView
      snapshot={snapshot}
      columns={columns}
      memberName={memberName}
      onOpen={onOpen}
      onAdd={onAdd}
      onClose={onClose}
    />
  );
}
