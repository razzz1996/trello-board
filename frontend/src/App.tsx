import { useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes } from "react-router-dom";

import { AdminControls } from "./AdminControls";
import { AUTH_INVALID_EVENT, ApiError, bootstrapCsrf, getSessionUser, logout } from "./api";
import { LoginScreen, PasswordChangeScreen } from "./Auth";
import { BoardPage } from "./BoardPage";
import { CalendarPage, NotificationsPage, ReportsPage } from "./OperationsPages";
import { BoardsPage, ManagerPage, MyTasksPage } from "./Pages";
import type { SessionUser } from "./types";
import { Alert, errorMessage } from "./ui";

function Shell({
  user,
  online,
  onLogout,
}: {
  user: SessionUser;
  online: boolean;
  onLogout: () => Promise<void>;
}) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="topbar__brand" to="/">
          <span className="brand-mark brand-mark--small">eM</span>
          <span>Productivity</span>
        </Link>
        <nav className="topbar__nav" aria-label="Primary">
          <NavLink to="/">Boards</NavLink>
          <NavLink to="/my-tasks">My Tasks</NavLink>
          <NavLink to="/manager">Manager</NavLink>
          <NavLink to="/notifications">Notifications</NavLink>
          <NavLink to="/calendar">Calendar</NavLink>
          <NavLink to="/reports">Reports</NavLink>
          {user.is_admin && <NavLink to="/admin">Admin</NavLink>}
        </nav>
        <div className="topbar__user">
          <span>{user.username}</span>
          <button className="button button--ghost" type="button" onClick={() => void onLogout()}>
            Sign out
          </button>
        </div>
      </header>
      <main className="page">
        {!online && (
          <Alert kind="info">
            You are offline. Changes are not queued locally; unsent form text stays on this screen
            until you reconnect or navigate away.
          </Alert>
        )}
        <Routes>
          <Route path="/" element={<BoardsPage user={user} />} />
          <Route path="/boards/:boardId" element={<BoardPage user={user} />} />
          <Route path="/my-tasks" element={<MyTasksPage user={user} />} />
          <Route path="/manager" element={<ManagerPage />} />
          <Route path="/notifications" element={<NotificationsPage />} />
          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/admin"
            element={user.is_admin ? <AdminControls user={user} /> : <Navigate to="/" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export function App() {
  const [csrfReady, setCsrfReady] = useState(false);
  const [sessionChecked, setSessionChecked] = useState(false);
  const [online, setOnline] = useState(() => navigator.onLine);
  const [user, setUser] = useState<SessionUser | null>(null);
  const [sessionError, setSessionError] = useState("");

  useEffect(() => {
    const connected = () => setOnline(true);
    const disconnected = () => setOnline(false);
    window.addEventListener("online", connected);
    window.addEventListener("offline", disconnected);
    return () => {
      window.removeEventListener("online", connected);
      window.removeEventListener("offline", disconnected);
    };
  }, []);

  useEffect(() => {
    const authenticationInvalid = (event: Event) => {
      const detail = (event as CustomEvent<{ message?: string }>).detail;
      setUser((current) => {
        if (current) {
          setSessionError(detail?.message ?? "Your session ended. Please sign in again.");
        }
        return null;
      });
    };
    window.addEventListener(AUTH_INVALID_EVENT, authenticationInvalid);
    return () => window.removeEventListener(AUTH_INVALID_EVENT, authenticationInvalid);
  }, []);

  useEffect(() => {
    let active = true;
    void bootstrapCsrf()
      .then(async () => {
        if (!active) return;
        setCsrfReady(true);
        try {
          const current = await getSessionUser();
          if (active) setUser(current);
        } catch (caught) {
          if (!(caught instanceof ApiError && [401, 403].includes(caught.status))) {
            if (active) setSessionError(errorMessage(caught));
          }
        } finally {
          if (active) setSessionChecked(true);
        }
      })
      .catch((caught) => {
        if (!active) return;
        setSessionError(errorMessage(caught));
        setSessionChecked(true);
      });
    return () => {
      active = false;
    };
  }, []);

  function authenticated(nextUser: SessionUser) {
    setSessionError("");
    setUser(nextUser);
  }

  async function signOut() {
    try {
      await logout();
    } finally {
      setSessionError("");
      setUser(null);
    }
  }

  if (!sessionChecked) {
    return (
      <main className="center-state">
        <div className="spinner" aria-hidden="true" />
        <p>{csrfReady ? "Checking session…" : "Initializing secure session…"}</p>
      </main>
    );
  }

  if (!csrfReady) {
    return (
      <main className="center-state">
        <Alert>{sessionError || "Unable to initialize the secure session."}</Alert>
      </main>
    );
  }

  if (!user) {
    return (
      <>
        {sessionError && <div className="global-alert"><Alert>{sessionError}</Alert></div>}
        <LoginScreen onAuthenticated={authenticated} />
      </>
    );
  }

  if (user.force_password_change) {
    return <PasswordChangeScreen user={user} onChanged={setUser} />;
  }

  return <Shell user={user} online={online} onLogout={signOut} />;
}
