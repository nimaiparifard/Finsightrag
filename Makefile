# On Windows without make: every target is a plain command, run them directly (or use WSL / Git Bash + make).
.PHONY: setup up down logs migrate seed data index train evaluate ablation test lint types docs

COMPOSE = docker compose -f infra/docker-compose.yml --env-file .env

setup:            ## install Python + JS deps and git hooks
	pip install -e "ml[dev]" -r backend/requirements-dev.txt -r serving/requirements.txt llama-index-core langgraph
	cd frontend && npm install
	pre-commit install

up:               ## build and start the whole stack
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail 100

migrate:
	cd backend && python manage.py migrate

seed:             ## create a demo admin user (admin@example.com / admin-demo-pass)
	cd backend && python manage.py shell -c "from apps.users.models import User; User.objects.filter(email='admin@example.com').exists() or User.objects.create_superuser('admin@example.com','admin-demo-pass')"

data:             ## download FinanceBench + FinQA + TAT-QA (SEC filings are fetched from the UI / API)
	mkdir -p data/raw
	git clone --depth 1 https://github.com/patronus-ai/financebench.git data/raw/financebench
	git clone --depth 1 https://github.com/czyssrs/FinQA.git data/raw/finqa
	git clone --depth 1 https://github.com/NExTplusplus/TAT-QA.git data/raw/tatqa

index:            ## parse, embed and index the FinanceBench filings
	finsight ingest --config ml/configs/dense_rerank_ctx.yaml

train: index      ## RAG has no model to train: "train" = (re)index

evaluate:
	finsight eval --config ml/configs/dense_rerank_ctx.yaml --filter-mode none

ablation:         ## run every ablation config and rebuild docs/results.md
	for c in baseline hybrid dense_ctx hybrid_ctx hybrid_rerank hybrid_rerank_ctx dense_rerank dense_rerank_ctx; do \
	  finsight eval --config ml/configs/$$c.yaml --filter-mode none; done
	finsight report $$(ls data/processed/eval/*.json) --out docs/results.md

test:
	pytest ml/tests serving/tests
	cd backend && pytest
	cd frontend && npm test

lint:
	ruff check ml serving backend
	ruff format --check ml serving backend
	cd frontend && npm run typecheck

types:            ## regenerate frontend TS types from the Django OpenAPI schema
	cd backend && python manage.py spectacular --file schema.yml
	cd frontend && npm run types

docs:
	@echo "docs are plain Markdown in docs/"
