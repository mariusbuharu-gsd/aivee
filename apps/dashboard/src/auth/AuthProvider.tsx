import { useMemo, useState, type ReactNode } from 'react';
import { AuthContext, type AuthState } from './context';
import { loadSession, saveSession, type Session } from './session';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(loadSession);
  const value = useMemo<AuthState>(
    () => ({
      session,
      signIn: (s, remember) => {
        saveSession(s, remember);
        setSession(s);
      },
      signOut: () => {
        saveSession(null);
        setSession(null);
      },
    }),
    [session],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
