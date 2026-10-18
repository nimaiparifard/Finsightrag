import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { z } from "zod";

import { api, post } from "@/api/client";
import { Company, ConversationDetail, Conversation, Page, type Message as Msg } from "@/api/schemas";
import { Button, ErrorNote, Input } from "@/components/ui";
import { streamSSE } from "@/lib/sse";
import type { ViewerTarget } from "@/features/viewer/DocumentViewer";
import { LazyViewer } from "@/features/viewer/LazyViewer";

import { AnswerText, DebugDrawer } from "./AnswerView";

export function ChatPage() {
  const { id } = useParams();
  const qc = useQueryClient();
  const [convId, setConvId] = useState<string | null>(id ?? null);
  const [question, setQuestion] = useState("");
  const [company, setCompany] = useState("");
  const [year, setYear] = useState("");
  const [live, setLive] = useState<{ q: string; text: string } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [target, setTarget] = useState<ViewerTarget | null>(null);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const companies = useQuery({ queryKey: ["companies"], queryFn: () => api("/api/companies/?page_size=200", Page(Company)) });
  const conv = useQuery({
    queryKey: ["conversation", convId],
    enabled: !!convId,
    queryFn: () => api(`/api/chat/conversations/${convId}/`, ConversationDetail),
  });
  useEffect(() => bottom.current?.scrollIntoView?.({ behavior: "smooth" }), [conv.data?.messages.length, live?.text]);
  useEffect(() => () => abort.current?.abort(), []);

  const send = useMutation({
    mutationFn: async (q: string) => {
      let cid = convId;
      if (!cid) {
        cid = (await api("/api/chat/conversations/", Conversation, post({}))).id;
        setConvId(cid);
      }
      setLive({ q, text: "" });
      abort.current = new AbortController();
      const filters = { ...(company && { company: [company] }), ...(year && { year: [year] }) };
      let failure: string | null = null;
      await streamSSE(`/api/chat/conversations/${cid}/messages/`, { question: q, stream: true, ...filters }, (e) => {
        if (e.event === "token") setLive((l) => (l ? { ...l, text: l.text + e.data } : l));
        if (e.event === "error") failure = JSON.parse(e.data).message ?? "Request failed";
      }, abort.current.signal);
      if (failure) throw new Error(failure);
      await qc.invalidateQueries({ queryKey: ["conversation", cid] });
    },
    onError: setError,
    onSettled: () => setLive(null),
  });

  const feedback = useMutation({
    mutationFn: ({ id: mid, up }: { id: string; up: boolean }) => api(`/api/chat/messages/${mid}/feedback/`, z.object({}).passthrough(), post({ thumbs_up: up })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["conversation", convId] }),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (q.length < 3 || send.isPending) return;
    setQuestion("");
    setError(null);
    send.mutate(q);
  }

  const open = (docId: string, page: number, hl?: string) => setTarget({ docId, page, highlight: hl });
  const msgs: Msg[] = conv.data?.messages ?? [];

  return (
    <div className="grid h-full grid-cols-1 lg:grid-cols-2">
      <section className="flex min-h-0 flex-col border-r border-slate-200">
        <div className="flex gap-2 border-b border-slate-200 bg-white p-2">
          <select aria-label="Company filter" className="rounded-md border border-slate-300 px-2 py-1 text-sm" value={company} onChange={(e) => setCompany(e.target.value)}>
            <option value="">All companies</option>
            {companies.data?.results.map((c) => <option key={c.id} value={c.name}>{c.ticker}</option>)}
          </select>
          <Input aria-label="Fiscal year filter" placeholder="Year" className="w-24" inputMode="numeric" value={year} onChange={(e) => setYear(e.target.value.replace(/\D/g, "").slice(0, 4))} />
        </div>
        <div className="flex-1 space-y-4 overflow-auto p-4">
          {msgs.length === 0 && !live && <p className="text-sm text-slate-500">Ask about a filing, e.g. “What was Apple’s operating margin in FY2023?”</p>}
          {msgs.map((m) => (
            <div key={m.id} className={m.role === "user" ? "ml-auto max-w-[85%] rounded-lg bg-brand p-3 text-sm text-white" : "max-w-[95%] rounded-lg border border-slate-200 bg-white p-3"}>
              {m.role === "user" ? m.content : (
                <>
                  <AnswerText text={m.content} onCite={(d, p) => open(d, p, m.chunks.find((c) => c.doc_id === d && c.page === p)?.preview)} />
                  <DebugDrawer m={m} onCite={open} />
                  <div className="mt-1 flex gap-1 text-sm">
                    <button aria-label="Helpful" className={m.thumbs_up === true ? "opacity-100" : "opacity-40 hover:opacity-100"} onClick={() => feedback.mutate({ id: m.id, up: true })}>👍</button>
                    <button aria-label="Not helpful" className={m.thumbs_up === false ? "opacity-100" : "opacity-40 hover:opacity-100"} onClick={() => feedback.mutate({ id: m.id, up: false })}>👎</button>
                  </div>
                </>
              )}
            </div>
          ))}
          {live && (
            <>
              <div className="ml-auto max-w-[85%] rounded-lg bg-brand p-3 text-sm text-white">{live.q}</div>
              <div className="max-w-[95%] rounded-lg border border-slate-200 bg-white p-3 text-sm" aria-live="polite">
                {live.text || <span className="text-slate-400">Searching filings…</span>}
              </div>
            </>
          )}
          <ErrorNote error={error} />
          <div ref={bottom} />
        </div>
        <form onSubmit={submit} className="flex gap-2 border-t border-slate-200 bg-white p-3">
          <Input aria-label="Question" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about a filing…" maxLength={2000} />
          {send.isPending ? <Button type="button" variant="ghost" onClick={() => abort.current?.abort()}>Stop</Button> : <Button type="submit" disabled={question.trim().length < 3}>Ask</Button>}
        </form>
      </section>
      <section className="hidden min-h-0 lg:block">
        <LazyViewer target={target} onPage={(p) => target && setTarget({ ...target, page: p, highlight: undefined })} />
      </section>
    </div>
  );
}
