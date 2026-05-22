"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

type User = {
  id: number;
  email: string;
  full_name?: string;
  role?: string;
  plan?: string;
};

type AuthContextValue = {
  user: User | null | undefined;  // undefined = checking, null = not authenticated
  signup: (email: string, password: string, fullName: string) => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  const data = await res.json().catch(() => ({ detail: "Network error" }));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data as T;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      const data = await call<{ user: User }>("/api/auth/me");
      setUser(data.user);
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const signup = useCallback(async (email: string, password: string, fullName: string) => {
    const data = await call<{ user: User }>("/api/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email, password, full_name: fullName }),
    });
    setUser(data.user);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const data = await call<{ user: User }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setUser(data.user);
  }, []);

  const logout = useCallback(async () => {
    await call("/api/auth/logout", { method: "POST" });
    setUser(null);
  }, []);

  // Memoized so consumers don't re-render every time AuthProvider re-renders.
  const value = useMemo<AuthContextValue>(() => ({ user, signup, login, logout }), [user, signup, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
