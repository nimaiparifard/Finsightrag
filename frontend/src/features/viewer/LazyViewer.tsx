import { lazy, Suspense } from "react";

import type { ViewerTarget } from "./DocumentViewer";

// pdf.js is ~600 kB: keep it out of the initial bundle, load it when a citation is first opened
const Viewer = lazy(() => import("./DocumentViewer").then((m) => ({ default: m.DocumentViewer })));

export function LazyViewer(props: { target: ViewerTarget | null; onPage: (p: number) => void }) {
  if (!props.target) return <p className="p-6 text-sm text-slate-500">Click a citation to open the source page.</p>;
  return (
    <Suspense fallback={<p className="p-6 text-sm text-slate-500">Loading viewer…</p>}>
      <Viewer {...props} />
    </Suspense>
  );
}
