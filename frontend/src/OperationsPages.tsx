import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  commandSchedule,
  createReport,
  createSchedule,
  getBoardSnapshot,
  getBoards,
  getNotifications,
  getReport,
  getReports,
  getSchedules,
  getTasks,
  markNotificationRead,
  previewSchedule,
} from "./api";
import type {
  BoardMember,
  BoardSummary,
  NotificationRow,
  ReportSummary,
  ScheduleOccurrencePreview,
  ScheduleRow,
  Task,
} from "./types";
import { Alert, errorMessage, formatDateTime, stars, taskDue } from "./ui";

function todayIso(): string {
  const now = new Date();
  const offset = now.getTimezoneOffset();
  return new Date(now.valueOf() - offset * 60_000).toISOString().slice(0, 10);
}

function recurrencePeriodKey(
  frequency: "daily" | "weekly" | "monthly",
  dateValue: string,
): string {
  if (frequency === "daily") return dateValue;
  if (frequency === "monthly") return dateValue.slice(0, 7);

  const [year, month, day] = dateValue.split("-").map(Number);
  const value = new Date(Date.UTC(year, month - 1, day));
  const weekday = value.getUTCDay() || 7;
  value.setUTCDate(value.getUTCDate() + 4 - weekday);
  const isoYear = value.getUTCFullYear();
  const yearStart = new Date(Date.UTC(isoYear, 0, 1));
  const week = Math.ceil(
    ((value.valueOf() - yearStart.valueOf()) / 86_400_000 + 1) / 7,
  );
  return `${isoYear}-W${String(week).padStart(2, "0")}`;
}

export function NotificationsPage() {
  const [rows, setRows] = useState<NotificationRow[]>([]);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setRows(await getNotifications(unreadOnly));
  }, [unreadOnly]);

  useEffect(() => {
    void refresh().catch((caught) => setError(errorMessage(caught)));
  }, [refresh]);

  async function markRead(row: NotificationRow) {
    try {
      await markNotificationRead(row.id);
      await refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  return (
    <section>
      <div className="page-heading">
        <div>
          <h1>Notifications</h1>
          <p>In-app delivery status mirrors the durable notification/outbox records.</p>
        </div>
        <label className="inline-check">
          <input type="checkbox" checked={unreadOnly}
            onChange={(event) => setUnreadOnly(event.target.checked)} />
          Unread only
        </label>
      </div>
      {error && <Alert>{error}</Alert>}
      <div className="notification-list">
        {rows.map((row) => (
          <article className={row.read_at ? "notification-card" : "notification-card notification-card--unread"}
            key={row.id}>
            <header>
              <strong>{row.kind.replaceAll("_", " ")}</strong>
              <span>{row.status}</span>
            </header>
            <p>{row.message}</p>
            <footer>
              <time>Scheduled {formatDateTime(row.scheduled_for)}</time>
              {!row.read_at && (
                <button className="button button--ghost" type="button"
                  onClick={() => void markRead(row)}>Mark read</button>
              )}
            </footer>
          </article>
        ))}
        {!rows.length && <div className="empty-state">No notifications in this view.</div>}
      </div>
    </section>
  );
}

export function ReportsPage() {
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [selected, setSelected] = useState<ReportSummary | null>(null);
  const [reportDate, setReportDate] = useState(todayIso());
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setReports(await getReports());
  }, []);

  useEffect(() => {
    void refresh().catch((caught) => setError(errorMessage(caught)));
  }, [refresh]);

  async function generate() {
    setBusy(true);
    setError("");
    try {
      const report = await createReport(reportDate);
      setSelected(report);
      await refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function open(report: ReportSummary) {
    try {
      setSelected(await getReport(report.id));
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  function download() {
    if (!selected) return;
    const blob = new Blob([JSON.stringify(selected, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `productivity-report-${selected.report_date}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section>
      <div className="page-heading">
        <div>
          <h1>Reports</h1>
          <p>Saved snapshots remain immutable; generating a later run creates a new snapshot.</p>
        </div>
        <div className="row-actions">
          <input type="date" value={reportDate}
            onChange={(event) => setReportDate(event.target.value)} />
          <button className="button button--primary" type="button"
            disabled={busy} onClick={() => void generate()}>
            {busy ? "Generating…" : "Generate snapshot"}
          </button>
        </div>
      </div>
      {error && <Alert>{error}</Alert>}
      <div className="report-layout">
        <section className="panel">
          <h2>Saved reports</h2>
          <ul className="plain-list report-list">
            {reports.map((report) => (
              <li key={report.id}>
                <button type="button" className="link-button"
                  onClick={() => void open(report)}>
                  {report.report_date}{report.delayed ? " · delayed" : ""}
                </button>
                <span>{formatDateTime(report.generated_at)}</span>
              </li>
            ))}
          </ul>
        </section>
        <section className="panel">
          {!selected ? (
            <div className="empty-state">Select or generate a report.</div>
          ) : (
            <ReportDetail report={selected} onDownload={download} />
          )}
        </section>
      </div>
    </section>
  );
}

function ReportDetail({
  report,
  onDownload,
}: {
  report: ReportSummary;
  onDownload: () => void;
}) {
  return (
    <div className="stack">
      <div className="section-heading">
        <div>
          <h2>{report.report_date}</h2>
          <p className="muted">Observed from {formatDateTime(report.observation_started_at)}</p>
        </div>
        <button className="button button--ghost" type="button" onClick={onDownload}>
          Download JSON
        </button>
      </div>
      <div className="report-metrics">
        {Object.entries(report.metrics).map(([key, value]) => (
          <div className="metric" key={key}>
            <span>{key.replaceAll("_", " ")}</span>
            <strong>{String(value)}</strong>
          </div>
        ))}
      </div>
      <h3>Snapshot rows</h3>
      <pre className="report-json">{JSON.stringify(report.rows ?? [], null, 2)}</pre>
    </div>
  );
}

export function CalendarPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [boards, setBoards] = useState<BoardSummary[]>([]);
  const [schedules, setSchedules] = useState<ScheduleRow[]>([]);
  const [boardId, setBoardId] = useState("");
  const [members, setMembers] = useState<BoardMember[]>([]);
  const [boardRole, setBoardRole] = useState<"MEMBER" | "MANAGER">("MEMBER");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const [taskRows, boardRows, scheduleRows] = await Promise.all([
      getTasks(),
      getBoards(),
      getSchedules(),
    ]);
    setTasks(
      taskRows
        .filter((task) => taskDue(task))
        .sort(
          (a, b) =>
            new Date(taskDue(a) ?? 0).valueOf() -
            new Date(taskDue(b) ?? 0).valueOf(),
        ),
    );
    setBoards(boardRows);
    setSchedules(scheduleRows);
    setBoardId((current) => current || boardRows[0]?.id || "");
  }, []);

  useEffect(() => {
    void refresh().catch((caught) => setError(errorMessage(caught)));
  }, [refresh]);

  useEffect(() => {
    if (!boardId) {
      setMembers([]);
      return;
    }
    void getBoardSnapshot(boardId)
      .then((snapshot) => {
        if (!snapshot) return;
        setMembers(snapshot.members);
        setBoardRole(snapshot.membership.role);
      })
      .catch((caught) => setError(errorMessage(caught)));
  }, [boardId]);

  return (
    <section>
      <div className="page-heading">
        <div>
          <h1>Calendar & Recurrence</h1>
          <p>Task deadlines and server-issued daily, weekly, or monthly recurrence schedules.</p>
        </div>
      </div>
      {error && <Alert>{error}</Alert>}
      <RecurrenceBuilder
        boards={boards}
        schedules={schedules}
        boardId={boardId}
        setBoardId={setBoardId}
        members={members}
        boardRole={boardRole}
        onChanged={refresh}
        onError={setError}
      />
      <section className="panel admin-section">
        <h2>Upcoming task deadlines</h2>
        <div className="timeline">
          {tasks.map((task) => (
            <a className="timeline__item" key={task.id} href={`/boards/${task.board_id}`}>
              <time>{formatDateTime(taskDue(task))}</time>
              <strong>{task.title}</strong>
              <span>{stars(task.priority)}</span>
            </a>
          ))}
          {!tasks.length && <div className="empty-state">No scheduled task deadlines.</div>}
        </div>
      </section>
    </section>
  );
}

function RecurrenceBuilder({
  boards,
  schedules,
  boardId,
  setBoardId,
  members,
  boardRole,
  onChanged,
  onError,
}: {
  boards: BoardSummary[];
  schedules: ScheduleRow[];
  boardId: string;
  setBoardId: (value: string) => void;
  members: BoardMember[];
  boardRole: "MEMBER" | "MANAGER";
  onChanged: () => Promise<void>;
  onError: (value: string) => void;
}) {
  const [scheduleId, setScheduleId] = useState<string | null>(null);
  const [name, setName] = useState("Recurring task");
  const [frequency, setFrequency] = useState<"daily" | "weekly" | "monthly">("daily");
  const [anchorDate, setAnchorDate] = useState(todayIso());
  const [effectiveDate, setEffectiveDate] = useState(todayIso());
  const [releaseTime, setReleaseTime] = useState("08:00");
  const [dueTime, setDueTime] = useState("17:00");
  const [interval, setIntervalValue] = useState(1);
  const [releaseWeekday, setReleaseWeekday] = useState(1);
  const [dueWeekday, setDueWeekday] = useState(5);
  const [monthlyRelease, setMonthlyRelease] = useState<"first_working_day" | "last_working_day">("first_working_day");
  const [monthlyDue, setMonthlyDue] = useState<"first_working_day" | "last_working_day">("last_working_day");
  const [taskTitle, setTaskTitle] = useState("Recurring task");
  const [priority, setPriority] = useState(2);
  const [ownerId, setOwnerId] = useState("");
  const [criteria, setCriteria] = useState("Complete the defined recurring work and provide evidence.");
  const [reason, setReason] = useState("Initial recurrence publication");
  const [preview, setPreview] = useState<ScheduleOccurrencePreview[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!ownerId && members.length) setOwnerId(members[0].id);
  }, [members, ownerId]);

  function rule(): Record<string, unknown> {
    const base: Record<string, unknown> = {
      frequency,
      timezone: "Asia/Manila",
      anchor_date: anchorDate,
      interval,
      release_time: releaseTime,
      due_time: dueTime,
      shift_policy: "next_workday",
      workdays_iso: [1, 2, 3, 4, 5],
      holidays: [],
    };
    if (frequency === "daily") {
      base.weekdays_iso = [1, 2, 3, 4, 5];
    } else if (frequency === "weekly") {
      base.release_weekday = releaseWeekday;
      base.due_weekday = dueWeekday;
    } else {
      base.release_rule = { kind: monthlyRelease };
      base.due_rule = { kind: monthlyDue };
    }
    return base;
  }

  function template(): Record<string, unknown> {
    return {
      title: taskTitle,
      priority,
      owner_id: ownerId,
      acceptance_criteria: criteria,
      required_checklist: [],
    };
  }

  async function doPreview() {
    if (!boardId) return;
    setBusy(true);
    try {
      setPreview(
        await previewSchedule({
          board_id: boardId,
          rule: rule(),
          after: todayIso(),
        }),
      );
    } catch (caught) {
      onError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function createDraft() {
    if (!boardId) return;
    setBusy(true);
    try {
      const created = await createSchedule({
        board_id: boardId,
        name,
        timezone: "Asia/Manila",
      });
      setScheduleId(created.id);
      await onChanged();
    } catch (caught) {
      onError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function publish() {
    if (!scheduleId || !ownerId) return;
    setBusy(true);
    try {
      const selected = schedules.find((item) => item.id === scheduleId);
      await commandSchedule(
        scheduleId,
        selected?.current_revision ? "revise" : "publish",
        {
          rule: rule(),
          template_fields: template(),
          effective_base_period: recurrencePeriodKey(
            frequency,
            effectiveDate,
          ),
          reason,
        },
      );
      await onChanged();
      setPreview([]);
    } catch (caught) {
      onError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  function loadSchedule(schedule: ScheduleRow) {
    setBoardId(schedule.board_id);
    setScheduleId(schedule.id);
    setName(schedule.name);
    const revision = schedule.current_revision;
    if (!revision) return;
    const scheduleRule = revision.rule;
    const scheduleTemplate = revision.template_fields;
    const nextFrequency = String(scheduleRule.frequency ?? "daily");
    if (nextFrequency === "daily" || nextFrequency === "weekly" || nextFrequency === "monthly") {
      setFrequency(nextFrequency);
    }
    setAnchorDate(String(scheduleRule.anchor_date ?? todayIso()));
    setEffectiveDate(todayIso());
    setReleaseTime(String(scheduleRule.release_time ?? "08:00"));
    setDueTime(String(scheduleRule.due_time ?? "17:00"));
    setIntervalValue(Number(scheduleRule.interval ?? 1));
    setReleaseWeekday(Number(scheduleRule.release_weekday ?? 1));
    setDueWeekday(Number(scheduleRule.due_weekday ?? 5));
    const releaseRule = scheduleRule.release_rule as Record<string, unknown> | undefined;
    const dueRule = scheduleRule.due_rule as Record<string, unknown> | undefined;
    if (releaseRule?.kind === "last_working_day") setMonthlyRelease("last_working_day");
    else setMonthlyRelease("first_working_day");
    if (dueRule?.kind === "first_working_day") setMonthlyDue("first_working_day");
    else setMonthlyDue("last_working_day");
    setTaskTitle(String(scheduleTemplate.title ?? schedule.name));
    setPriority(Number(scheduleTemplate.priority ?? 2));
    setOwnerId(String(scheduleTemplate.owner_id ?? ""));
    setCriteria(String(scheduleTemplate.acceptance_criteria ?? ""));
    setReason("Recurrence revision");
  }

  async function pauseOrResume(schedule: ScheduleRow) {
    const reasonText = window.prompt(
      schedule.paused ? "Reason for resuming schedule:" : "Reason for pausing schedule:",
    )?.trim();
    if (!reasonText) return;
    try {
      if (schedule.paused) {
        const tomorrow = new Date();
        tomorrow.setDate(tomorrow.getDate() + 1);
        const defaultEnd = new Date(
          tomorrow.valueOf() - tomorrow.getTimezoneOffset() * 60_000,
        )
          .toISOString()
          .slice(0, 10);
        const end = window.prompt("Resume base date (exclusive pause end):", defaultEnd)?.trim();
        if (!end) return;
        await commandSchedule(schedule.id, "resume", {
          end_base_date: end,
          reason: reasonText,
        });
      } else {
        const start = window.prompt("Pause base date:", todayIso())?.trim();
        if (!start) return;
        await commandSchedule(schedule.id, "pause", {
          start_base_date: start,
          reason: reasonText,
        });
      }
      await onChanged();
    } catch (caught) {
      onError(errorMessage(caught));
    }
  }

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <h2>Recurrence builder</h2>
          <p className="muted">
            Preview five occurrences before publication. Generated tasks are never deleted to simulate resets.
          </p>
        </div>
        <span className="status-pill">{boardRole.toLowerCase()}</span>
      </div>
      <div className="form-grid recurrence-grid">
        <label>Board
          <select value={boardId} onChange={(event) => {
            setBoardId(event.target.value);
            setScheduleId(null);
          }}>
            <option value="">Select board</option>
            {boards.map((board) => <option key={board.id} value={board.id}>{board.name}</option>)}
          </select>
        </label>
        <label>Schedule name
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label>Frequency
          <select value={frequency}
            onChange={(event) => setFrequency(event.target.value as "daily" | "weekly" | "monthly")}>
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
          </select>
        </label>
        <label>Anchor date
          <input type="date" value={anchorDate}
            onChange={(event) => setAnchorDate(event.target.value)} />
        </label>
        <label>Effective from base date
          <input type="date" value={effectiveDate}
            onChange={(event) => setEffectiveDate(event.target.value)} />
          <span className="field-help">
            Converted to the canonical {frequency} recurrence period at publish time.
          </span>
        </label>
        <label>Interval
          <input type="number" min={1} max={365} value={interval}
            onChange={(event) => setIntervalValue(Math.max(1, Number(event.target.value)))} />
        </label>
        <label>Release time
          <input type="time" value={releaseTime}
            onChange={(event) => setReleaseTime(event.target.value)} />
        </label>
        <label>Due time
          <input type="time" value={dueTime}
            onChange={(event) => setDueTime(event.target.value)} />
        </label>
        {frequency === "weekly" && (
          <>
            <label>Release weekday
              <select value={releaseWeekday}
                onChange={(event) => setReleaseWeekday(Number(event.target.value))}>
                {[1,2,3,4,5,6,7].map((day) => <option key={day} value={day}>{day}</option>)}
              </select>
            </label>
            <label>Due weekday
              <select value={dueWeekday}
                onChange={(event) => setDueWeekday(Number(event.target.value))}>
                {[1,2,3,4,5,6,7].map((day) => <option key={day} value={day}>{day}</option>)}
              </select>
            </label>
          </>
        )}
        {frequency === "monthly" && (
          <>
            <label>Release rule
              <select value={monthlyRelease}
                onChange={(event) => setMonthlyRelease(event.target.value as typeof monthlyRelease)}>
                <option value="first_working_day">First working day</option>
                <option value="last_working_day">Last working day</option>
              </select>
            </label>
            <label>Due rule
              <select value={monthlyDue}
                onChange={(event) => setMonthlyDue(event.target.value as typeof monthlyDue)}>
                <option value="first_working_day">First working day</option>
                <option value="last_working_day">Last working day</option>
              </select>
            </label>
          </>
        )}
      </div>
      <h3>Task template</h3>
      <div className="form-grid">
        <label>Task title
          <input value={taskTitle} onChange={(event) => setTaskTitle(event.target.value)} />
        </label>
        <label>Owner
          <select value={ownerId} onChange={(event) => setOwnerId(event.target.value)}>
            <option value="">Select owner</option>
            {members.map((member) => (
              <option key={member.id} value={member.id}>{member.username}</option>
            ))}
          </select>
        </label>
        <label>Priority
          <select value={priority} onChange={(event) => setPriority(Number(event.target.value))}>
            <option value={1}>★</option><option value={2}>★★</option><option value={3}>★★★</option>
          </select>
        </label>
      </div>
      <label>Acceptance criteria
        <textarea rows={3} value={criteria}
          onChange={(event) => setCriteria(event.target.value)} />
      </label>
      <label>Publication / revision reason
        <input value={reason} onChange={(event) => setReason(event.target.value)} />
      </label>
      <div className="row-actions">
        <button className="button button--ghost" type="button"
          disabled={busy || !boardId} onClick={() => void doPreview()}>Preview 5</button>
        {!scheduleId && (
          <button className="button button--primary" type="button"
            disabled={busy || !boardId} onClick={() => void createDraft()}>Create draft schedule</button>
        )}
        {scheduleId && boardRole === "MANAGER" && (
          <button className="button button--primary" type="button"
            disabled={busy || !ownerId} onClick={() => void publish()}>
            Publish {schedules.find((item) => item.id === scheduleId)?.current_revision ? "revision" : "schedule"}
          </button>
        )}
        {scheduleId && (
          <button className="button button--ghost" type="button"
            onClick={() => setScheduleId(null)}>New schedule</button>
        )}
      </div>
      {preview.length > 0 && (
        <div className="preview-list">
          {preview.map((item) => (
            <div key={item.period_key}>
              <strong>{item.period_key}</strong>
              <span>{formatDateTime(item.release_at)} → {formatDateTime(item.due_at)}</span>
              {item.explanations.length > 0 && <small>{item.explanations.join("; ")}</small>}
            </div>
          ))}
        </div>
      )}
      <h3>Existing schedules</h3>
      <div className="schedule-list">
        {schedules.map((schedule) => (
          <article key={schedule.id}>
            <div>
              <strong>{schedule.name}</strong>
              <span>
                {schedule.current_revision ? `revision ${schedule.current_revision.revision}` : "draft"}
                {" · "}{schedule.paused ? "paused" : schedule.active ? "active" : "inactive"}
              </span>
            </div>
            <div className="row-actions">
              <button className="button button--ghost" type="button"
                onClick={() => loadSchedule(schedule)}>Load</button>
              {schedule.current_revision && (
                <button className="button button--ghost" type="button"
                  onClick={() => void pauseOrResume(schedule)}>
                  {schedule.paused ? "Resume" : "Pause"}
                </button>
              )}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
