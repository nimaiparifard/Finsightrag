# FinSight — financial filings analyst (RAG)

Ask questions about SEC filings (10-K / 10-Q) and get answers **with page citations**, tables included. Numbers are
computed by a calculator rather than by the model, every citation and number is checked against the retrieved text,
and the system answers "Not found in the provided documents." when the evidence isn't there.

> **Status:** the `ml/` core, the FastAPI serving layer, the Django backend and the React frontend are implemented and
> tested. Answer-quality numbers (faithfulness, answer relevancy, numeric EM) need an LLM run that has not been done
> yet — see [Results](#results) for exactly what is and isn't measured.

## Problem

Analysts read 100–300 page filings to answer questions like *"What was Apple's operating margin in FY2023 and why
did it change?"*. Generic chatbots hallucinate numbers. FinSight answers only from the documents, cites the exact
page, handles table numbers, compares across years/companies, and refuses when the answer isn't there.

## Architecture

See [docs/architecture.md](docs/architecture.md) (diagram, layers, query path) and [docs/adr/](docs/adr/).

```
React (chat · viewer · library · compare · eval)
   └─ /api ─▶ Django + DRF + Celery   (users, filings, conversations, ingestion jobs, SSE proxy)
                 └─ HTTP ─▶ FastAPI serving   (/v1/query SSE, /v1/compare, /v1/retrieve, /metrics)
                               └─ finsight (ml/)   parse → chunk → embed → hybrid retrieve → rerank → generate → verify
```

The `ml/` package never imports Django or FastAPI; every swappable part is behind a Protocol and picked from YAML.

## Results

<!-- RESULTS -->

## Tech stack

Python 3.12, PyMuPDF / BeautifulSoup (parsing), sentence-transformers (`bge-base-en-v1.5`, `bge-reranker-v2-m3`),
rank-bm25, pgvector + Postgres FTS, LlamaIndex and LangGraph adapters, Django 6 + DRF + Celery + Redis, FastAPI,
React 18 + TypeScript + Vite + Tailwind + TanStack Query + Recharts + react-pdf, Docker Compose, Prometheus + Grafana,
Langfuse (optional), MLflow (optional), GitHub Actions.

## Quick start

**Just the RAG core** (no services, no Docker):

```bash
pip install -e "ml[dev]"
make data                                   # FinanceBench, FinQA, TAT-QA  (or the three git clones in the Makefile)
finsight ingest --config ml/configs/baseline.yaml      # parse + embed the FinanceBench filings (GPU: ~1 h on an RTX 5070)
finsight eval   --config ml/configs/hybrid.yaml --filter-mode none
finsight ask "What is the FY2018 capital expenditure for 3M?" --config ml/configs/hybrid.yaml --company 3M
```

The LLM is `provider: auto`: it uses whichever is reachable — an API key in the environment
(`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`, …) or a local **Ollama** that has a model
(`ollama pull qwen2.5:7b-instruct`). Retrieval metrics need no LLM at all.

**Full stack:**

```bash
cp .env.example .env        # fill in the passwords; set SEC_USER_AGENT="Your Name you@email" to ingest from EDGAR
docker compose -f infra/docker-compose.yml --env-file .env up -d --build
# add --profile local-llm for an Ollama container
```

| Service | URL |
|---|---|
| App | http://localhost:3000 |
| API docs | http://localhost:8000/api/docs/ |
| Serving | http://localhost:8001/health |
| Grafana / Prometheus | http://localhost:3001 / http://localhost:9090 |
| Langfuse / MLflow | http://localhost:3002 / http://localhost:5000 |

The serving container needs an index at `/app/data/processed/index/…` (run `finsight ingest` inside the `worker`
container, or ingest from the Library page).

**Local development (no Docker):**

```bash
cd backend && python manage.py migrate && python manage.py runserver     # :8000 (SQLite)
cd serving && uvicorn app.main:get_app --factory --port 8001
cd frontend && npm install && npm run dev                               # :5173, proxies /api to :8000
```

## How to swap components

Everything is a name in YAML (`ml/configs/*.yaml`; a config can `extends:` another).

| To change | Edit |
|---|---|
| LLM | `llm.provider: ollama \| openai \| anthropic \| vllm \| groq \| together \| openrouter \| gemini \| auto` and `llm.params.model` |
| Embeddings | `embedder.params.model: BAAI/bge-m3` (multilingual) or any sentence-transformers model — re-ingest |
| Vector store | `store.backend: pgvector` and `FINSIGHT_PG_DSN=postgresql://…` |
| Retrieval | `retrieval.mode: dense \| hybrid`, `retrieval.rerank: true`, `retrieval.query_transform: multi_query \| hyde \| decompose` |
| Chunking | `chunker.name: recursive \| section`, `contextual_headers: true` — re-ingest |
| Prompt | add `ml/src/finsight/generation/prompts/answer_v2.jinja`, set `generation.prompt: answer_v2` |

Adding a new embedder/LLM/reranker is a class plus `@register("llm", "name")` — see `ml/src/finsight/llm.py`.

## Project structure

```
ml/          finsight package: ingestion · retrieval · generation · evaluation · integrations · configs · tests
serving/     FastAPI app (SSE streaming, Prometheus metrics, index reload)
backend/     Django apps: users · core · documents · chat · collections · evaluation
frontend/    React app: chat · viewer · library · compare · eval
infra/       docker-compose, Prometheus, Grafana (provisioned), Postgres init
docs/        architecture, ADRs, API, results
```

## Evaluation

* **Datasets:** FinanceBench (150 questions with evidence pages) for retrieval; FinQA / TAT-QA for the table +
  calculator path (`finsight eval-tableqa`); your own golden set (`finsight golden generate` drafts it with an LLM —
  **every item starts `verified: false` and only human-verified items are used for gating**).
* **Metrics:** Recall@k, MRR, nDCG against evidence pages; numeric exact match (±1%, scale-tolerant); refusal
  accuracy; LLM-judge faithfulness and answer relevancy (`--judge`); latency p50/p95; cost per query.
* **CI gate:** `finsight gate` fails a PR when a protected metric drops more than 3 points below
  `ml/eval/baseline_metrics.json` (`.github/workflows/ml-eval.yml`).

## Testing

```bash
pytest ml/tests serving/tests          # 58 tests; Postgres tests run when FINSIGHT_TEST_PG_DSN is set
cd backend && pytest                   # 18 tests
cd frontend && npm test                # 9 tests
```

LLM calls are replaced by a deterministic `FakeLLMProvider`, embeddings by a hashing embedder, so none of the above
needs a GPU, a model download or the network.

## Known limitations

* **RAGAS itself is not integrated**; faithfulness/relevancy use a small LLM-as-judge in the same spirit
  (`evaluation/judge.py`). Judge scores are only as good as the judge model.
* The golden set must be reviewed by a human before it means anything.
* HTML (EDGAR) filings have no real pages; they are split on page-break styles or a character budget, so their
  citations point at an approximate page. PDFs are page-exact.
* Table extraction uses PyMuPDF's `find_tables`; complex multi-header financial tables can come out imperfectly.
* Auth tokens are kept in `localStorage` (XSS-exposed); acceptable for this project, use httpOnly cookies for
  anything sensitive.
* The Persian/Codal extension and GraphRAG are not implemented.

## Roadmap

Fine-tuned embeddings on financial Q/A pairs, GraphRAG over filing entities, Codal.ir with `bge-m3`, a Helm chart.

## License

MIT
