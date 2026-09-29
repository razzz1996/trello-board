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
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";

import { ApiError, commandTask, getBoardSnapshot } from "./api";
import { CommitModal, CreateTaskButton, ReviewModal, SubmitModal, TaskDetailModal } from "./TaskActions";
import type { BoardColumn, BoardSnapshot, SessionUser, Task, TaskState } from "./types";
import { Alert, errorMessage, formatDateTime, isOverdue, stars, taskDue } from "./ui";

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

  return (
    <article
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={`task-card ${isDragging ? "task-card--dragging" : ""}`}
    >
      <button className="task-card__handle" type="button" aria-label={`Move ${task.title}`}
        {...attributes} {...listeners}>⋮⋮</button>
      <button className="task-card__body" type="button" onClick={onOpen}>
        <span className="stars" aria-label={`Priority ${task.priority} of 3`}>{stars(task.priority)}</span>
        <strong>{task.title}</strong>
        <span className={isOverdue(task) ? "deadline deadline--late" : "deadline"}>
          {formatDateTime(taskDue(task))}
        </span>
        <span className="task-card__owner">{memberName}</span>
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
        <header><h2>{column.name}</h2><span>{column.tasks.length}</span></header>
        <SortableContext items={column.tasks.map((task) => task.id)} strategy={verticalListSortingStrategy}>
          <div className="kanban-column__body">
            {column.tasks.map((task) => (
              <SortableTaskCard key={task.id} task={task} memberName={memberName(task)}
                onOpen={() => onOpen(task)} />
            ))}
            {column.tasks.length === 0 && <div className="column-empty">Drop tasks here</div>}
          </div>
        </SortableContext>
      </section>
    </div>
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
  const [commitTaskId, setCommitTaskId] = useState<string | null>(null);
  const [submitTaskId, setSubmitTaskId] = useState<string | null>(null);
  const [reviewTaskId, setReviewTaskId] = useState<string | null>(null);

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

  const tasks = useMemo(
    () => snapshot?.columns.flatMap((column) => column.tasks) ?? [],
    [snapshot],
  );
  const taskById = useCallback(
    (id: string | null) => tasks.find((task) => task.id === id) ?? null,
    [tasks],
  );

  async function moveTask(task: Task, targetState: TaskState, targetPosition: number | null) {
    if (!snapshot) return;
    let reason = "";
    if (targetState === "BLOCKED") {
      reason = window.prompt("Why is this task blocked?")?.trim() ?? "";
      if (!reason) {
        setNotice("Move cancelled: Blocked requires a reason.");
        return;
      }
    }
    try {
      await commandTask(task.id, "move_task", {
        expected_version: task.row_version,
        expected_board_revision: snapshot.revision,
        target_state: targetState,
        target_position: targetPosition,
        reason,
      });
      setNotice("");
      await refresh();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        setNotice("The board changed while you were moving the card. The latest board was reloaded.");
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
      targetPosition = snapshot.columns.find((column) => column.state === targetState)?.tasks.length ?? null;
    }
    if (!targetState) return;

    if (active.column_state === "BACKLOG" && targetState === "TODO") {
      if (snapshot.membership.role !== "MANAGER") {
        setNotice("Only a board manager can commit a draft into To Do.");
        return;
      }
      setCommitTaskId(active.id);
      return;
    }
    if (targetState === "REVIEW") {
      setSubmitTaskId(active.id);
      return;
    }
    if (targetState === "DONE") {
      setNotice("Done requires an independent manager acceptance. Open the Review card instead.");
      return;
    }
    if (active.committed_at && targetState === "BACKLOG") {
      setNotice("Committed tasks cannot return to Backlog.");
      return;
    }
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
  const commitTarget = taskById(commitTaskId);
  const submitTarget = taskById(submitTaskId);
  const reviewTarget = taskById(reviewTaskId);

  return (
    <section className="board-page">
      <div className="page-heading page-heading--board">
        <div>
          <Link className="back-link" to="/">← Boards</Link>
          <h1>{snapshot.board.name}</h1>
          <p>{snapshot.membership.role === "MANAGER" ? "Manager" : "Member"} · revision {snapshot.revision}</p>
        </div>
        <CreateTaskButton snapshot={snapshot} user={user} onChanged={refresh} />
      </div>
      {error && <Alert>{error}</Alert>}
      {notice && <Alert kind="info">{notice}</Alert>}

      <DndContext sensors={sensors} collisionDetection={closestCorners}
        onDragEnd={(event) => void onDragEnd(event)}>
        <div className="kanban-board">
          {snapshot.columns.map((column) => (
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
          onSubmit={() => {
            setSelectedTaskId(null);
            setSubmitTaskId(selected.id);
          }}
          onReview={() => {
            setSelectedTaskId(null);
            setReviewTaskId(selected.id);
          }}
        />
      )}
      {commitTarget && (
        <CommitModal task={commitTarget} snapshot={snapshot}
          onClose={() => setCommitTaskId(null)} onChanged={refresh} />
      )}
      {submitTarget && (
        <SubmitModal task={submitTarget} snapshot={snapshot}
          onClose={() => setSubmitTaskId(null)} onChanged={refresh} />
      )}
      {reviewTarget && (
        <ReviewModal task={reviewTarget} snapshot={snapshot}
          onClose={() => setReviewTaskId(null)} onChanged={refresh} />
      )}
    </section>
  );
}
