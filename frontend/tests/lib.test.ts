import { describe, expect, it } from "vitest";

import { splitCitations } from "@/lib/citations";
import { parseSSE } from "@/lib/sse";

describe("parseSSE", () => {
  it("parses complete events and keeps the unfinished remainder", () => {
    const { events, rest } = parseSSE("event: token\ndata: Net\n\nevent: token\ndata: sales\n\nevent: fin");
    expect(events).toEqual([
      { event: "token", data: "Net" },
      { event: "token", data: "sales" },
    ]);
    expect(rest).toBe("event: fin");
  });

  it("joins multi-line data and handles CRLF", () => {
    const { events } = parseSSE("event: final\r\ndata: line1\r\ndata: line2\r\n\r\n");
    expect(events).toEqual([{ event: "final", data: "line1\nline2" }]);
  });

  it("works when a chunk boundary splits an event", () => {
    let buf = "event: token\nda";
    let r = parseSSE(buf);
    expect(r.events).toHaveLength(0);
    buf = r.rest + "ta: hi\n\n";
    r = parseSSE(buf);
    expect(r.events).toEqual([{ event: "token", data: "hi" }]);
  });
});

describe("splitCitations", () => {
  it("turns [doc:page] into cite segments", () => {
    expect(splitCitations("Sales were $5B [AAPL_2023_10K:41]. Costs fell [MSFT_2024_10K:7].")).toEqual([
      { kind: "text", text: "Sales were $5B " },
      { kind: "cite", docId: "AAPL_2023_10K", page: 41 },
      { kind: "text", text: ". Costs fell " },
      { kind: "cite", docId: "MSFT_2024_10K", page: 7 },
      { kind: "text", text: "." },
    ]);
  });

  it("leaves text without citations alone and ignores bracketed non-citations", () => {
    expect(splitCitations("No cites [see note] here")).toEqual([{ kind: "text", text: "No cites [see note] here" }]);
  });
});
