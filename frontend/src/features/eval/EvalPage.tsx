import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "@/api/client";
import { EvalRun, Page } from "@/api/schemas";
import { Card, ErrorNote } from "@/components/ui";

const SERIES = [
  ["recall@5", "#0f4c81"],
  ["mrr", "#2a9d8f"],
  ["numeric_em", "#e9a23b"],
] as const;

/** Latest run per config → ablation bar chart + table. */
export function EvalPage() {
  const runs = useQuery({ queryKey: ["eval-runs"], queryFn: () => api("/api/evaluation/runs/?page_size=200", Page(EvalRun)) });
  const [dataset, setDataset] = useState("financebench");

  const latest = useMemo(() => {
    const seen = new Map<string, EvalRun>();
    for (const r of runs.data?.results ?? []) if (r.dataset === dataset && !seen.has(r.config_name)) seen.set(r.config_name, r); // API is newest-first
    return [...seen.values()];
  }, [runs.data, dataset]);

  const chart = latest.map((r) => ({ config: r.config_name, ...Object.fromEntries(SERIES.map(([k]) => [k, r.metrics[k] ?? 0])) }));
  const fmt = (v: number | null | undefined) => (v == null ? "–" : v.toFixed(3));

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Evaluation</h2>
        <select aria-label="Dataset" className="rounded-md border border-slate-300 px-2 py-1 text-sm" value={dataset} onChange={(e) => setDataset(e.target.value)}>
          {["financebench", "golden"].map((d) => <option key={d}>{d}</option>)}
        </select>
      </div>
      <ErrorNote error={runs.error} />
      {latest.length === 0 ? (
        <Card><p className="text-sm text-slate-500">No runs yet. Run <code>finsight eval --config …</code> then <code>manage.py import_eval_runs</code>.</p></Card>
      ) : (
        <>
          <Card>
            <div className="h-72" role="img" aria-label="Ablation chart of retrieval and answer metrics per configuration">
              <ResponsiveContainer>
                <BarChart data={chart}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="config" tick={{ fontSize: 12 }} />
                  <YAxis domain={[0, 1]} />
                  <Tooltip />
                  <Legend />
                  {SERIES.map(([k, color]) => <Bar key={k} dataKey={k} fill={color} />)}
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
          <Card className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-slate-500"><th className="py-1">Config</th><th>n</th><th>Recall@5</th><th>MRR</th><th>nDCG@8</th><th>Numeric EM</th><th>p95 s</th></tr></thead>
              <tbody>
                {latest.map((r) => (
                  <tr key={r.id} className="border-t border-slate-100">
                    <td className="py-1 font-medium">{r.config_name}</td><td>{r.n_questions}</td>
                    <td>{fmt(r.metrics["recall@5"])}</td><td>{fmt(r.metrics.mrr)}</td><td>{fmt(r.metrics["ndcg@8"])}</td><td>{fmt(r.metrics.numeric_em)}</td><td>{fmt(r.metrics.latency_p95_s)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </div>
  );
}
