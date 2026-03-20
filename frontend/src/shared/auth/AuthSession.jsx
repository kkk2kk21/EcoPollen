import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { apiFetch, clearToken, getToken } from "../api/auth";

const AuthSessionContext = createContext(null);

export function AuthSessionProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const refreshSession = useCallback(async () => {
    const token = getToken();
    if (!token) {
      setUser(null);
      setLoading(false);
      return null;
    }

    setLoading(true);
    try {
      const me = await apiFetch("/api/v1/auth/me");
      setUser(me);
      return me;
    } catch {
      clearToken();
      setUser(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
  }, []);

  useEffect(() => {
    refreshSession();
  }, [refreshSession]);

  const value = useMemo(
    () => ({
      user,
      loading,
      isAuthenticated: Boolean(user),
      refreshSession,
      logout,
    }),
    [loading, logout, refreshSession, user]
  );

  return <AuthSessionContext.Provider value={value}>{children}</AuthSessionContext.Provider>;
}

export function useAuthSession() {
  const context = useContext(AuthSessionContext);
  if (!context) {
    throw new Error("useAuthSession must be used within AuthSessionProvider");
  }
  return context;
}
