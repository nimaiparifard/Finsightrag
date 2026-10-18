import { lazy, Suspense } from "react";
import { NavLink, Navigate, Outlet, Route, Routes } from "react-router-dom";

import { Button } from "@/components/ui";
import { useAuth } from "@/features/auth/AuthProvider";
import { LoginPage } from "@/features/auth/LoginPage";
import { ChatPage } from "@/features/chat/ChatPage";
import { ComparePage } from "@/features/compare/ComparePage";
import { LibraryPage } from "@/features/library/LibraryPage";

// Recharts is heavy and only this page needs it
const EvalPage = lazy(() => import("@/features/eval/EvalPage").then((m) => ({ default: m.EvalPage })));

function Shell() {
  const { authed, logout } = useAuth();
  if (!authed) return <Navigate to="/login" replace />;
  const link = ({ isActive }: { isActive: boolean }) =>
    `rounded-md px-3 py-1.5 text-sm font-medium ${isActive ? "bg-brand-soft text-brand" : "text-slate-600 hover:bg-slate-100"}`;
  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b border-slate-200 bg-white px-4 py-2">
        <span className="mr-4 text-lg font-semibold text-brand">FinSight</span>
        <nav className="flex gap-1" aria-label="Main">
          <NavLink to="/" end className={link}>Chat</NavLink>
          <NavLink to="/library" className={link}>Library</NavLink>
          <NavLink to="/compare" className={link}>Compare</NavLink>
          <NavLink to="/eval" className={link}>Evaluation</NavLink>
        </nav>
        <Button variant="ghost" className="ml-auto" onClick={logout}>Sign out</Button>
      </header>
      <main className="min-h-0 flex-1"><Suspense fallback={<p className="p-6 text-sm text-slate-500">Loading…</p>}><Outlet /></Suspense></main>
    </div>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<Shell />}>
        <Route index element={<ChatPage />} />
        <Route path="/chat/:id" element={<ChatPage />} />
        <Route path="/library" element={<LibraryPage />} />
        <Route path="/compare" element={<ComparePage />} />
        <Route path="/eval" element={<EvalPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
