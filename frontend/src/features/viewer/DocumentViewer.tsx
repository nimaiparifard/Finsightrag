import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";

import { api, authedFetch } from "@/api/client";
import { PageText } from "@/api/schemas";
import { Button, ErrorNote } from "@/components/ui";

pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

export type ViewerTarget = { docId: string; page: number; highlight?: string };

/** Shows the cited page. PDFs render as the real page image; HTML filings (no fixed pages) fall back to page text.
 *  Pages are 0-indexed in the data; the UI shows page + 1. */
export function DocumentViewer({ target, onPage }: { target: ViewerTarget | null; onPage: (p: number) => void }) {
  if (!target) return <p className="p-6 text-sm text-slate-500">Click a citation to open the source page.</p>;
  return <Loaded target={target} onPage={onPage} />;
}

function Loaded({ target, onPage }: { target: ViewerTarget; onPage: (p: number) => void }) {
  const { docId, page } = target;
  const text = useQuery({ queryKey: ["page", docId, page], queryFn: () => api(`/api/documents/${docId}/pages/${page}/`, PageText) });
  const [pdf, setPdf] = useState<{ url: string; failed: boolean } | null>(null);

  // fetch the PDF through authedFetch so the JWT is sent; render from a blob URL
  useEffect(() => {
    let url: string | null = null;
    let alive = true;
    setPdf(null);
    authedFetch(`/api/documents/${docId}/file/`)
      .then(async (r) => {
        if (!alive) return;
        if (r.ok && r.headers.get("content-type")?.includes("pdf")) {
          url = URL.createObjectURL(await r.blob());
          setPdf({ url, failed: false });
        } else setPdf({ url: "", failed: true });
      })
      .catch(() => alive && setPdf({ url: "", failed: true }));
    return () => {
      alive = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [docId]);

  const count = text.data?.page_count ?? 0;
  const body = useMemo(() => highlight(text.data?.text ?? "", target.highlight), [text.data, target.highlight]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-slate-200 bg-white px-3 py-2 text-sm">
        <span className="truncate font-medium" title={docId}>{docId}</span>
        <span className="flex items-center gap-2">
          <Button variant="ghost" disabled={page <= 0} onClick={() => onPage(page - 1)} aria-label="Previous page">‹</Button>
          <span data-testid="page-indicator">Page {page + 1}{count ? ` / ${count}` : ""}</span>
          <Button variant="ghost" disabled={!count || page >= count - 1} onClick={() => onPage(page + 1)} aria-label="Next page">›</Button>
        </span>
      </div>
      <div className="flex-1 overflow-auto bg-slate-100 p-3">
        <ErrorNote error={text.error} />
        {pdf && !pdf.failed ? (
          <Document file={pdf.url} loading={<p className="text-sm text-slate-500">Loading PDF…</p>} error={<p className="text-sm text-red-600">Could not render the PDF.</p>}>
            <Page pageNumber={page + 1} width={560} renderTextLayer={false} renderAnnotationLayer={false} />
          </Document>
        ) : (
          <article className="whitespace-pre-wrap rounded bg-white p-4 text-sm leading-relaxed" aria-label="Page text">{body}</article>
        )}
        {pdf && !pdf.failed && target.highlight && (
          <details className="mt-3 rounded bg-white p-3 text-sm">
            <summary className="cursor-pointer font-medium">Cited passage</summary>
            <p className="mt-2 whitespace-pre-wrap">{highlight(text.data?.text ?? "", target.highlight)}</p>
          </details>
        )}
      </div>
    </div>
  );
}

/** Wrap the first occurrence of the cited snippet in <mark>. Whitespace-insensitive because PDF text is ragged. */
export function highlight(text: string, snippet?: string): React.ReactNode {
  if (!snippet) return text;
  const words = snippet.trim().split(/\s+/).slice(0, 12).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (words.length < 3) return text;
  const m = new RegExp(words.join("\\s+"), "i").exec(text);
  if (!m) return text;
  return (
    <>
      {text.slice(0, m.index)}
      <mark className="rounded bg-yellow-200 px-0.5">{m[0]}</mark>
      {text.slice(m.index + m[0].length)}
    </>
  );
}
