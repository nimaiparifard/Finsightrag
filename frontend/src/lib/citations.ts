export type Segment = { kind: "text"; text: string } | { kind: "cite"; docId: string; page: number };

const CITATION = /\[([A-Za-z0-9._-]+):(\d+)\]/g;

/** Split an answer into text and clickable citation segments. Pages are 0-indexed in the data, shown +1. */
export function splitCitations(text: string): Segment[] {
  const out: Segment[] = [];
  let last = 0;
  for (const m of text.matchAll(CITATION)) {
    if (m.index > last) out.push({ kind: "text", text: text.slice(last, m.index) });
    out.push({ kind: "cite", docId: m[1], page: Number(m[2]) });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}
