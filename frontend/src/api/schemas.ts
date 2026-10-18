import { z } from "zod";

export const Page = <T extends z.ZodTypeAny>(item: T) =>
  z.object({ count: z.number(), next: z.string().nullable(), previous: z.string().nullable(), results: z.array(item) });

export const Company = z.object({ id: z.string(), ticker: z.string(), name: z.string(), cik: z.string(), filing_count: z.number() });
export type Company = z.infer<typeof Company>;

export const Filing = z.object({
  id: z.string(),
  ticker: z.string(),
  doc_id: z.string(),
  form: z.string(),
  fiscal_year: z.number(),
  status: z.enum(["pending", "downloaded", "indexed", "failed"]),
  chunk_count: z.number(),
  error: z.string(),
});
export type Filing = z.infer<typeof Filing>;

export const IngestionJob = z.object({
  id: z.string(),
  status: z.enum(["queued", "running", "done", "failed"]),
  total: z.number(),
  done: z.number(),
  failed: z.number(),
  progress: z.number(),
  error: z.string(),
  params: z.object({ ticker: z.string() }).passthrough(),
});
export type IngestionJob = z.infer<typeof IngestionJob>;

export const Citation = z.object({ doc_id: z.string(), page: z.number() });
export type Citation = z.infer<typeof Citation>;

export const RetrievedChunk = z.object({
  doc_id: z.string(),
  page: z.number(),
  score: z.number(),
  type: z.string(),
  section: z.string().optional(),
  preview: z.string().optional(),
});
export type RetrievedChunk = z.infer<typeof RetrievedChunk>;

export const Message = z.object({
  id: z.string(),
  role: z.enum(["user", "assistant"]),
  content: z.string(),
  citations: z.array(Citation),
  chunks: z.array(RetrievedChunk),
  latency_s: z.number().nullable(),
  cost_usd: z.union([z.string(), z.number()]),
  cached: z.boolean(),
  refused: z.boolean(),
  guardrails: z.object({ ok: z.boolean() }).passthrough().nullable(),
  prompt_version: z.string(),
  thumbs_up: z.boolean().nullable().optional(),
});
export type Message = z.infer<typeof Message>;

export const Conversation = z.object({ id: z.string(), title: z.string(), filters: z.record(z.unknown()) });
export type Conversation = z.infer<typeof Conversation>;
export const ConversationDetail = Conversation.extend({ messages: z.array(Message) });
export type ConversationDetail = z.infer<typeof ConversationDetail>;

export const EvalRun = z.object({
  id: z.string(),
  config_name: z.string(),
  dataset: z.string(),
  n_questions: z.number(),
  metrics: z.record(z.number().nullable()),
  created_at: z.string(),
});
export type EvalRun = z.infer<typeof EvalRun>;

export const PageText = z.object({
  doc_id: z.string(),
  page: z.number(),
  page_count: z.number(),
  text: z.string(),
  tables: z.array(z.string()),
});
export type PageText = z.infer<typeof PageText>;

export const Tokens = z.object({ access: z.string(), refresh: z.string() });
