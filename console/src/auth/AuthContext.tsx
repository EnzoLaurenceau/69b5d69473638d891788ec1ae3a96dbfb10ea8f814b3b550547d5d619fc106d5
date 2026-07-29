// Auth : le token du tenant vit UNIQUEMENT en mémoire (state React).
// Interdiction stricte de localStorage/sessionStorage (règle Fable 5 §4) — un rechargement
// de page redemande le token, c'est le compromis assumé pour ne rien persister côté client.
import React, { createContext, useContext, useState } from "react";

interface AuthState {
  token: string | null;
  setToken: (t: string | null) => void;
}

const AuthCtx = createContext<AuthState>({ token: null, setToken: () => {} });

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  return <AuthCtx.Provider value={{ token, setToken }}>{children}</AuthCtx.Provider>;
}

export function useAuth(): AuthState {
  return useContext(AuthCtx);
}

/** Hook pratique : renvoie le token garanti non-null (à utiliser sous <RequireAuth>). */
export function useToken(): string {
  const { token } = useAuth();
  if (!token) throw new Error("useToken appelé hors session authentifiée");
  return token;
}
