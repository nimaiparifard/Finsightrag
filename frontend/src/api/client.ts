import { z } from "zod";

import { Tokens } from "./schemas";

const KEY = "finsight.tokens";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const tokens = {
  get(): { access: string; refresh: string } | null {
    try {
      const raw = localStorage.getItem(KEY);
      return raw ? Tokens.parse(JSON.parse(raw)) : null;
    } catch {
      return null;
    }
  },
  set(t: { access: string; refresh: string } | null) {
    try {
      if (t) localStorage.setItem(KEY, JSON.stringify(t));
      else localStorage.removeItem(KEY);
    } catch {
      /* storage unavailable (private mode): session just won't persist */
    }
  },
};

let refreshing: Promise<boolean> | null = null;

async function refresh(): Promise<boolean> {
  const t = tokens.get();
  if (!t) return false;
  // de-duplicate: concurrent 401s share one refresh call (refresh tokens rotate, so a second call would fail)
  refreshing ??= fetch("/api/auth/token/refresh/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh: t.refresh }),
  })
    .then(async (r) => {
      if (!r.ok) return false;
      const data = Tokens.partial({ refresh: true }).parse(await r.json());
      tokens.set({ access: data.access, refresh: data.refresh ?? t.refresh });
      return true;
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export async function authedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const go = () => {
    const headers = new Headers(init.headers);
    const t = tokens.get();
    if (t) headers.set("Authorization", `Bearer ${t.access}`);
    if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    return fetch(path, { ...init, headers });
  };
  let res = await go();
  if (res.status === 401 && (await refresh())) res = await go();
  if (res.status === 401) {
    tokens.set(null);
    window.dispatchEvent(new Event("finsight:logout"));
  }
  return res;
}

export async function api<S extends z.ZodTypeAny>(path: string, schema: S, init: RequestInit = {}): Promise<z.infer<S>> {
  const res = await authedFetch(path, init);
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const err = (body as { error?: { message?: unknown } } | null)?.error?.message;
    throw new ApiError(res.status, typeof err === "string" ? err : JSON.stringify(err ?? res.statusText));
  }
  return schema.parse(body); // fail loudly if the backend contract drifts
}

export const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });
