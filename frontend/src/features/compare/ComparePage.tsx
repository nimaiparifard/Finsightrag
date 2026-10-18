import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { z } from "zod";

import { api, post } from "@/api/client";
import { Company, Citation, Page } from "@/api/schemas";
import { Button, Card, ErrorNote, Input } from "@/components/ui";
import { AnswerText } from "@/features/chat/AnswerView";
import type { ViewerTarget } from "@/features/viewer/DocumentViewer";
import { LazyViewer } from "@/features/viewer/LazyViewer";

const CompareResult = z.object({ answer: z.string(), citations: z.array(Citation), refused: z.boolean(), latency_s: z.number() });
const METRICS = ["operating margin", "revenue growth", "net income", "capital expenditures", "gross margin", "free cash flow"];

/** Side-by-side comparison. Uses the agentic endpoint: one lookup per company, then a cited synthesis. */
export function ComparePage() {
  const companies = useQuery({ queryKey: ["companies"], queryFn: () => api("/api/companies/?page_size=200", Page(Company)) });
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [metric, setMetric] = useState(METRICS[0]);
  const [year, setYear] = useState("");
  const [target, setTarget] = useState<ViewerTarget | null>(null);

  const run = useMutation({
    mutationFn: () => {
      const name = (t: string) => companies.data?.results.find((c) => c.ticker === t)?.name ?? t;
      const q = `Compare ${name(a)} and ${name(b)} on ${metric}${year ? ` in FY${year}` : ""}.`;
      return api("/api/chat/compare/", CompareResult, post({ question: q, company: [name(a), name(b)] }));
    },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (a && b && a !== b) run.mutate(); };
  const list = companies.data?.results ?? [];

  return (
    <div className="grid h-full grid-cols-1 lg:grid-cols-2">
      <div className="space-y-4 overflow-auto p-6">
        <Card>
          <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
            {[["Company A", a, setA], ["Company B", b, setB]].map(([label, val, set]) => (
              <label key={label as string} className="text-sm">{label as string}
                <select className="block rounded-md border border-slate-300 px-2 py-1.5 text-sm" value={val as string} onChange={(e) => (set as (v: string) => void)(e.target.value)}>
                  <option value="">Select…</option>
                  {list.map((c) => <option key={c.id} value={c.ticker}>{c.ticker}</option>)}
                </select>
              </label>
            ))}
            <label className="text-sm">Metric
              <select className="block rounded-md border border-slate-300 px-2 py-1.5 text-sm" value={metric} onChange={(e) => setMetric(e.target.value)}>
                {METRICS.map((m) => <option key={m}>{m}</option>)}
              </select>
            </label>
            <label className="text-sm">FY<Input value={year} onChange={(e) => setYear(e.target.value.replace(/\D/g, "").slice(0, 4))} className="w-20" /></label>
            <Button type="submit" disabled={!a || !b || a === b || run.isPending}>{run.isPending ? "Comparing…" : "Compare"}</Button>
          </form>
          {a && a === b && <p className="mt-2 text-sm text-amber-700">Pick two different companies.</p>}
        </Card>
        <ErrorNote error={run.error} />
        {run.data && (
          <Card>
            <AnswerText text={run.data.answer} onCite={(d, p) => setTarget({ docId: d, page: p })} />
            <p className="mt-2 text-xs text-slate-500">{run.data.latency_s.toFixed(1)}s · {run.data.citations.length} sources</p>
          </Card>
        )}
      </div>
      <div className="hidden min-h-0 border-l border-slate-200 lg:block">
        <LazyViewer target={target} onPage={(p) => target && setTarget({ ...target, page: p })} />
      </div>
    </div>
  );
}
