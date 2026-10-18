import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { ApiError, tokens } from "@/api/client";
import { Tokens } from "@/api/schemas";

type Auth = {
  authed: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const Ctx = createContext<Auth | null>(null);

async function postJson(path: string, body: unknown) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new ApiError(r.status, extractMessage(data));
  return data;
}

function extractMessage(data: unknown): string {
  const m = (data as { error?: { message?: unknown }; detail?: string } | null);
  const msg = m?.error?.message ?? m?.detail ?? "Request failed";
  return typeof msg === "string" ? msg : Object.values(msg as Record<string, string[]>).flat().join(" ");
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authed, setAuthed] = useState(() => tokens.get() !== null);

  useEffect(() => {
    const off = () => setAuthed(false);
    window.addEventListener("finsight:logout", off);
    return () => window.removeEventListener("finsight:logout", off);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    tokens.set(Tokens.parse(await postJson("/api/auth/token/", { email, password })));
    setAuthed(true);
  }, []);
  const register = useCallback(async (email: string, password: string) => {
    await postJson("/api/auth/register/", { email, password });
    await login(email, password);
  }, [login]);
  const logout = useCallback(() => {
    tokens.set(null);
    setAuthed(false);
  }, []);

  const value = useMemo(() => ({ authed, login, register, logout }), [authed, login, register, logout]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): Auth {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
