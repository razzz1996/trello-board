import { Link, NavLink, Navigate, Route, Routes } from "react-router-dom";

import { BoardPage } from "./BoardPage";
import {
  AdminPage,
  BoardsPage,
  CalendarPage,
  ManagerPage,
  MyTasksPage,
  ReportsPage,
} from "./Pages";
import type { SessionUser } from "./types";

export function Shell({
  user,
  onLogout,
}: {
  user: SessionUser;
  onLogout: () => Promise<void>;
}) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="topbar__brand" to="/">
          <span className="brand-mark brand-mark--small">eM</span>
          <span>Productivity</span>
        </Link>        <nav className="topbar__nav" aria-label="Primary">
          <NavLink to="/">Boards</NavLink>
          <NavLink to="/my-tasks">My Tasks</NavLink>
          <NavLink to="/manager">Manager</NavLink>
          <NavLink to="/calendar">Calendar</NavLink>
          <NavLink to="/reports">Reports</NavLink>
          {user.is_admin && <NavLink to="/admin">Admin</NavLink>}
        </nav>
        <div className="topbar__user">
          <span>{user.username}</span>
          <button
            className="button button--ghost"
            type="button"
            onClick={() => void onLogout()}
          >
            Sign out
          </button>
        </div>
      </header>
      <main className="page">
        <Routes>
          <Route path="/" element={<BoardsPage user={user} />} />
          <Route path="/boards/:boardId" element={<BoardPage user={user} />} />
          <Route path="/my-tasks" element={<MyTasksPage user={user} />} />
          <Route path="/manager" element={<ManagerPage />} />          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route
            path="/admin"
            element={
              user.is_admin ? <AdminPage user={user} /> : <Navigate to="/" replace />
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
