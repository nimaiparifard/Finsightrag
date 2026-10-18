import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, post } from "@/api/client";
import { Company, Filing, IngestionJob, Page } from "@/api/schemas";
import { Badge, Button, Card, ErrorNote, Input, ProgressBar } from "@/components/ui";

const tone = { indexed: "green", failed: "red", downloaded: "blue", pending: "slate" } as const;

export function LibraryPage() {
  const qc = useQueryClient();
  const thisYear = new Date().getFullYear();
  const [ticker, setTicker] = useState("");
  const [from, setFrom] = useState(thisYear - 2);
  const [to, setTo] = useState(thisYear);
  const [forms, setForms] = useState<string[]>(["10-K"]);
  const [jobId, setJobId] = useState<string | null>(null);

  const companies = useQuery({ queryKey: ["companies"], queryFn: () => api("/api/companies/?page_size=200", Page(Company)) });
  const filings = useQuery({ queryKey: ["filings"], queryFn: () => api("/api/filings/?page_size=200", Page(Filing)) });
  const job = useQuery({
    queryKey: ["job", jobId],
    enabled: !!jobId,
    queryFn: () => api(`/api/ingestion-jobs/${jobId}/`, IngestionJob),
    // poll while the job is alive, stop once it settles
    refetchInterval: (q) => (q.state.data && ["done", "failed"].includes(q.state.data.status) ? false : 1500),
  });
  const settled = job.data && ["done", "failed"].includes(job.data.status);
  if (settled) {
    void qc.invalidateQueries({ queryKey: ["companies"] });
    void qc.invalidateQueries({ queryKey: ["filings"] });
  }

  const ingest = useMutation({
    mutationFn: () => api("/api/filings/ingest/", IngestionJob, post({ ticker, years: [from, to], forms })),
    onSuccess: (j) => setJobId(j.id),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (ticker.trim()) ingest.mutate();
  }
  const toggle = (f: string) => setForms((cur) => (cur.includes(f) ? cur.filter((x) => x !== f) : [...cur, f]));

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <Card>
        <h2 className="mb-3 text-lg font-semibold">Add a company</h2>
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <label className="text-sm">Ticker<Input value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} placeholder="AAPL" className="w-28" maxLength={12} /></label>
          <label className="text-sm">From FY<Input type="number" value={from} onChange={(e) => setFrom(+e.target.value)} className="w-24" /></label>
          <label className="text-sm">To FY<Input type="number" value={to} onChange={(e) => setTo(+e.target.value)} className="w-24" /></label>
          {["10-K", "10-Q"].map((f) => (
            <label key={f} className="flex items-center gap-1 pb-2 text-sm"><input type="checkbox" checked={forms.includes(f)} onChange={() => toggle(f)} />{f}</label>
          ))}
          <Button type="submit" disabled={!ticker.trim() || forms.length === 0 || ingest.isPending}>Ingest</Button>
        </form>
        <ErrorNote error={ingest.error} />
        {job.data && (
          <div className="mt-4 space-y-1" aria-live="polite">
            <div className="flex justify-between text-sm"><span>{job.data.params.ticker}: {job.data.status}</span><span>{job.data.done}/{job.data.total} filings{job.data.failed ? `, ${job.data.failed} failed` : ""}</span></div>
            <ProgressBar value={job.data.progress} />
            {job.data.error && <ErrorNote error={job.data.error} />}
          </div>
        )}
      </Card>

      <Card>
        <h2 className="mb-3 text-lg font-semibold">Library</h2>
        <ErrorNote error={companies.error ?? filings.error} />
        {filings.data?.results.length === 0 && <p className="text-sm text-slate-500">No filings yet. Add a company above.</p>}
        <div className="divide-y divide-slate-100">
          {companies.data?.results.map((c) => (
            <div key={c.id} className="py-3">
              <p className="font-medium">{c.ticker} <span className="font-normal text-slate-500">{c.name}</span></p>
              <div className="mt-1 flex flex-wrap gap-2">
                {filings.data?.results.filter((f) => f.ticker === c.ticker).map((f) => (
                  <span key={f.id} title={f.error || `${f.chunk_count} chunks`}><Badge tone={tone[f.status]}>{f.form} FY{f.fiscal_year} · {f.status}</Badge></span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
