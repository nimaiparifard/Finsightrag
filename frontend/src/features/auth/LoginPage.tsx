import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";

import { Button, Card, ErrorNote, Input } from "@/components/ui";

import { useAuth } from "./AuthProvider";

export function LoginPage() {
  const { authed, login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  if (authed) return <Navigate to="/" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await (mode === "login" ? login : register)(email, password);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full items-center justify-center p-4">
      <Card className="w-full max-w-sm space-y-4">
        <div>
          <h1 className="text-xl font-semibold text-brand">FinSight</h1>
          <p className="text-sm text-slate-500">Ask questions about SEC filings, with page citations.</p>
        </div>
        <form onSubmit={submit} className="space-y-3">
          <label className="block text-sm">
            Email
            <Input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="block text-sm">
            Password
            <Input type="password" required minLength={8} autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          <ErrorNote error={error} />
          <Button type="submit" disabled={busy} className="w-full">{mode === "login" ? "Sign in" : "Create account"}</Button>
        </form>
        <button className="text-sm text-brand underline" onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "Need an account? Register" : "Have an account? Sign in"}
        </button>
      </Card>
    </div>
  );
}
