import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, authStorage, formatApiError } from "../api/client";
import type { User } from "../types";

interface AuthContextValue {
  user: User | null;
  token: string | null;
  loading: boolean;
  error: string | null;
  login: (email: string, password: string) => Promise<void>;
  register: (fullName: string, email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  clearError: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);
const DEFAULT_SESSION_TTL_MS = 7 * 24 * 60 * 60 * 1000;

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(authStorage.token));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const clearSession = useCallback(() => {
    localStorage.removeItem(authStorage.token);
    localStorage.removeItem(authStorage.expiresAt);
    setToken(null);
    setUser(null);
  }, []);

  const persistSession = useCallback((nextToken: string, expiresAt?: string | null) => {
    const safeExpiresAt =
      expiresAt && Number.isFinite(new Date(expiresAt).getTime())
        ? expiresAt
        : new Date(Date.now() + DEFAULT_SESSION_TTL_MS).toISOString();
    localStorage.setItem(authStorage.token, nextToken);
    localStorage.setItem(authStorage.expiresAt, safeExpiresAt);
  }, []);

  const hydrate = useCallback(async () => {
    const storedToken = localStorage.getItem(authStorage.token);
    const expiresAt = localStorage.getItem(authStorage.expiresAt);
    if (!storedToken || (expiresAt && new Date(expiresAt).getTime() <= Date.now())) {
      clearSession();
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      const currentUser = await api.me();
      setUser(currentUser);
      setToken(storedToken);
    } catch (err) {
      clearSession();
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  }, [clearSession]);

  useEffect(() => {
    void hydrate();
  }, [hydrate]);

  useEffect(() => {
    const onUnauthorized = () => clearSession();
    window.addEventListener("skycast:unauthorized", onUnauthorized);
    return () => window.removeEventListener("skycast:unauthorized", onUnauthorized);
  }, [clearSession]);

  const login = useCallback(async (email: string, password: string) => {
    setError(null);
    const response = await api.login({ email, password });
    persistSession(response.access_token, response.expires_at);
    setToken(response.access_token);
    setUser(response.user);
  }, [persistSession]);

  const register = useCallback(
    async (fullName: string, email: string, password: string) => {
      setError(null);
      await api.register({ full_name: fullName, email, password });
      await login(email, password);
    },
    [login]
  );

  const logout = useCallback(async () => {
    setError(null);
    try {
      if (localStorage.getItem(authStorage.token)) {
        await api.logout();
      }
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      clearSession();
    }
  }, [clearSession]);

  const value = useMemo(
    () => ({
      user,
      token,
      loading,
      error,
      login,
      register,
      logout,
      clearError: () => setError(null)
    }),
    [user, token, loading, error, login, register, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}
