import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { desk, getToken, setToken } from "./api";
import type { Me } from "./types";

type AuthValue = {
  ready: boolean;
  token: string | null;
  me: Me | null;
  signIn: (token: string) => Promise<void>;
  signOut: () => void;
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTok] = useState<string | null>(getToken());
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setMe(null);
      setReady(true);
      return;
    }
    const next = await desk.me();
    setMe(next);
    setReady(true);
  }, []);

  useEffect(() => {
    refresh().catch(() => setReady(true));
  }, [refresh]);

  const value = useMemo<AuthValue>(
    () => ({
      ready,
      token,
      me,
      signIn: async (next) => {
        setToken(next);
        setTok(next);
        const profile = await desk.me();
        setMe(profile);
        setReady(true);
      },
      signOut: () => {
        setToken(null);
        setTok(null);
        setMe(null);
      },
      refresh,
    }),
    [ready, token, me, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("Auth is missing.");
  return value;
}
