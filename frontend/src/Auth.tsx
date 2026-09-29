import { type FormEvent, useState } from "react";

import { changePassword, login } from "./api";
import type { SessionUser } from "./types";
import { Alert, errorMessage } from "./ui";

export function LoginScreen({
  onAuthenticated,
}: {
  onAuthenticated: (user: SessionUser) => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onAuthenticated(await login(username, password));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-layout">
      <section className="login-card">
        <div className="brand-mark">eM</div>
        <h1>eMEGA Productivity</h1>
        <p className="muted">Private team workspace</p>
        {error && <Alert>{error}</Alert>}
        <form onSubmit={submit} className="stack">
          <label>
            Username
            <input autoComplete="username" value={username}
              onChange={(event) => setUsername(event.target.value)} required maxLength={150} />
          </label>
          <label>
            Password
            <input autoComplete="current-password" type="password" value={password}
              onChange={(event) => setPassword(event.target.value)} required />
          </label>
          <button className="button button--primary" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </section>
    </main>
  );
}

export function PasswordChangeScreen({
  user,
  onChanged,
}: {
  user: SessionUser;
  onChanged: (user: SessionUser) => void;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (newPassword !== confirm) {
      setError("New password confirmation does not match.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      onChanged(await changePassword(currentPassword, newPassword));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-layout">
      <section className="login-card login-card--wide">
        <h1>Set your permanent password</h1>
        <p>{user.username}, replace the temporary credential before accessing team work.</p>
        {error && <Alert>{error}</Alert>}
        <form onSubmit={submit} className="stack">
          <label>
            Current temporary password
            <input type="password" autoComplete="current-password" value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)} required />
          </label>
          <label>
            New password
            <input type="password" autoComplete="new-password" value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)} minLength={12} required />
          </label>
          <label>
            Confirm new password
            <input type="password" autoComplete="new-password" value={confirm}
              onChange={(event) => setConfirm(event.target.value)} minLength={12} required />
          </label>
          <button className="button button--primary" disabled={busy}>
            {busy ? "Updating…" : "Update password"}
          </button>
        </form>
      </section>
    </main>
  );
}
