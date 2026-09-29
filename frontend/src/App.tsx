import { useEffect, useState } from "react";

import { ApiError, bootstrapCsrf, getSessionUser, logout } from "./api";
import { LoginScreen, PasswordChangeScreen } from "./Auth";
import { Shell } from "./Layout";
import type { SessionUser } from "./types";
import { Alert, errorMessage } from "./ui";

export function App() {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [checked, setChecked] = useState(false);
  const [fatal, setFatal] = useState("");

  useEffect(() => {
    let active = true;
    void bootstrapCsrf()
      .then(async () => {
        try {
          const current = await getSessionUser();
          if (active) setUser(current);
        } catch (caught) {
          if (
            !(caught instanceof ApiError && [401, 403].includes(caught.status)) &&
            active
          ) {
            setFatal(errorMessage(caught));
          }        } finally {
          if (active) setChecked(true);
        }
      })
      .catch((caught) => {
        if (active) {
          setFatal(errorMessage(caught));
          setChecked(true);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  async function signOut() {
    try {
      await logout();
    } finally {
      setUser(null);
    }
  }

  if (!checked) {
    return (
      <main className="center-state">
        <div className="spinner" />
        <p>Checking secure session…</p>
      </main>
    );
  }  if (fatal && !user) {
    return (
      <main className="center-state">
        <Alert>{fatal}</Alert>
        <LoginScreen onAuthenticated={setUser} />
      </main>
    );
  }
  if (!user) return <LoginScreen onAuthenticated={setUser} />;
  if (user.force_password_change) {
    return <PasswordChangeScreen user={user} onChanged={setUser} />;
  }
  return <Shell user={user} onLogout={signOut} />;
}
