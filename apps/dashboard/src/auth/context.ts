import { createContext, useContext } from 'react';
import type { Session } from './session';

export interface AuthState {
  session: Session | null;
  signIn: (session: Session, remember: boolean) => void;
  signOut: () => void;
}

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error('useAuth must be used inside <AuthProvider>');
  return auth;
}
