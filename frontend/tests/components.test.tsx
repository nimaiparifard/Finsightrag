import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Message } from "@/api/schemas";
import { AnswerText, DebugDrawer } from "@/features/chat/AnswerView";
import { highlight } from "@/features/viewer/DocumentViewer";

describe("AnswerText", () => {
  it("renders citations as buttons that open the cited page", async () => {
    const onCite = vi.fn();
    render(<AnswerText text="Net sales were 5,000 million [Acme_2023_10K:2]." onCite={onCite} />);
    const chip = screen.getByRole("button", { name: "Acme_2023 p.3" });
    await userEvent.click(chip);
    expect(onCite).toHaveBeenCalledWith("Acme_2023_10K", 2); // data is 0-indexed, label shows page + 1
  });
});

const msg: Message = {
  id: "1", role: "assistant", content: "x", citations: [], latency_s: 1.23, cost_usd: "0.000123", cached: true,
  refused: false, guardrails: { ok: false }, prompt_version: "answer_v1",
  chunks: [{ doc_id: "A_2023_10K", page: 4, score: 0.9123, type: "table" }],
};

describe("DebugDrawer", () => {
  it("shows status badges and reveals retrieved chunks on demand", async () => {
    const onCite = vi.fn();
    render(<DebugDrawer m={msg} onCite={onCite} />);
    expect(screen.getByText("cache hit")).toBeInTheDocument();
    expect(screen.getByText(/unverified/)).toBeInTheDocument();
    expect(screen.queryByText("0.912")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Debug" }));
    await userEvent.click(screen.getByText("0.912"));
    expect(onCite).toHaveBeenCalledWith("A_2023_10K", 4);
  });
});

describe("highlight", () => {
  it("marks the cited snippet even when whitespace differs", () => {
    const { container } = render(<p>{highlight("Total  net sales\nwere $383,285 million in 2023", "net sales were $383,285")}</p>);
    expect(container.querySelector("mark")?.textContent).toBe("net sales\nwere $383,285");
  });

  it("returns the text unchanged when there is no usable snippet", () => {
    expect(highlight("abc", undefined)).toBe("abc");
    expect(highlight("abc", "ab")).toBe("abc");
  });
});
