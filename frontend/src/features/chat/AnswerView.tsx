import { useState } from "react";

import type { Message } from "@/api/schemas";
import { Badge } from "@/components/ui";
import { splitCitations } from "@/lib/citations";

export function AnswerText({ text, onCite }: { text: string; onCite: (docId: string, page: number) => void }) {
  return (
    <p className="whitespace-pre-wrap text-sm leading-relaxed">
      {splitCitations(text).map((s, i) =>
        s.kind === "text" ? (
          <span key={i}>{s.text}</span>
        ) : (
          <button key={i} onClick={() => onCite(s.docId, s.page)} title={`${s.docId}, page ${s.page + 1}`}
            className="mx-0.5 inline-block rounded bg-brand-soft px-1.5 py-0.5 align-baseline text-xs font-medium text-brand hover:bg-brand hover:text-white">
            {s.docId.replace(/_10[KQ]$/, "")} p.{s.page + 1}
          </button>
        ),
      )}
    </p>
  );
}

/** Per-answer debug drawer: what was retrieved, scores, latency, cost, prompt version, guardrail verdict. */
export function DebugDrawer({ m, onCite }: { m: Message; onCite: (docId: string, page: number) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2">
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        {m.cached && <Badge tone="blue">cache hit</Badge>}
        {m.refused && <Badge tone="amber">not found</Badge>}
        {m.guardrails && <Badge tone={m.guardrails.ok ? "green" : "red"}>{m.guardrails.ok ? "verified" : "unverified numbers/citations"}</Badge>}
        {m.latency_s != null && <span>{m.latency_s.toFixed(1)}s</span>}
        <button className="underline" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? "Hide" : "Debug"}</button>
      </div>
      {open && (
        <div className="mt-2 space-y-1 rounded border border-slate-200 bg-slate-50 p-2 text-xs">
          <p>prompt <code>{m.prompt_version || "n/a"}</code> · cost ${Number(m.cost_usd).toFixed(5)}</p>
          <table className="w-full">
            <thead><tr className="text-left text-slate-500"><th>#</th><th>source</th><th>type</th><th className="text-right">score</th></tr></thead>
            <tbody>
              {m.chunks.map((c, i) => (
                <tr key={i} className="cursor-pointer hover:bg-white" onClick={() => onCite(c.doc_id, c.page)}>
                  <td>{i + 1}</td><td>{c.doc_id} p.{c.page + 1}</td><td>{c.type}</td><td className="text-right">{c.score.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
