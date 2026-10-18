import json
from unittest import mock

import httpx
import pytest

from apps.chat.clients import ServingClient
from apps.chat.models import Conversation, Feedback, Message
from apps.collections.models import Watchlist
from apps.core.exceptions import UpstreamError
from apps.documents.models import Company, Filing, IngestionJob
from apps.evaluation.models import EvalRun
from apps.evaluation.services import import_runs

ANSWER = {"answer": "Net sales were 5,000 million [Acme_2023_10K:2].", "citations": [{"doc_id": "Acme_2023_10K", "page": 2}],
          "refused": False, "cached": False, "latency_s": 0.4, "guardrails_ok": True, "prompt_version": "answer_v1",
          "chunks": [{"doc_id": "Acme_2023_10K", "page": 2, "score": 0.9, "type": "text"}],
          "usage": {"prompt_tokens": 1000, "completion_tokens": 100}}

SSE = ("event: retrieval\ndata: " + json.dumps({"chunks": ANSWER["chunks"], "filters": {}}) + "\n\n"
       "event: token\ndata: Net sales\n\n"
       "event: final\ndata: " + json.dumps({"answer": ANSWER["answer"], "citations": ANSWER["citations"],
                                            "refused": False, "latency_s": 0.4, "guardrails": {"ok": True},
                                            "prompt_version": "answer_v1"}) + "\n\n")


def serving(handler):
    return ServingClient(base_url="http://s", transport=httpx.MockTransport(handler), retries=2)


# ---- auth ------------------------------------------------------------------------------------
def test_register_login_me(anon, db):
    r = anon.post("/api/auth/register/", {"email": "New@Example.com", "password": "a-long-password-1"})
    assert r.status_code == 201 and "password" not in r.data
    tok = anon.post("/api/auth/token/", {"email": "new@example.com", "password": "a-long-password-1"}).data
    anon.credentials(HTTP_AUTHORIZATION=f"Bearer {tok['access']}")
    assert anon.get("/api/auth/me/").data["email"] == "new@example.com"
    assert anon.post("/api/auth/register/", {"email": "new@example.com", "password": "a-long-password-1"}).status_code == 400


def test_endpoints_require_auth(anon, db):
    for url in ["/api/companies/", "/api/filings/", "/api/chat/conversations/", "/api/collections/"]:
        assert anon.get(url).status_code == 401


def test_health_is_public(anon, db):
    assert anon.get("/api/health/").json() == {"status": "ok"}


# ---- documents -------------------------------------------------------------------------------
def test_ingest_endpoint_validates_and_queues(api, db):
    with mock.patch("apps.documents.tasks.run_ingestion_job.delay") as delay:
        r = api.post("/api/filings/ingest/", {"ticker": "aapl", "years": [2022, 2024], "forms": ["10-K"]}, format="json")
    assert r.status_code == 202 and r.data["params"]["ticker"] == "AAPL" and r.data["status"] == "queued"
    delay.assert_called_once()
    assert api.post("/api/filings/ingest/", {"ticker": "AAPL", "years": [2024, 2020], "forms": ["10-K"]},
                    format="json").status_code == 400
    assert api.post("/api/filings/ingest/", {"ticker": "AA PL!", "years": [2020, 2022], "forms": ["10-K"]},
                    format="json").status_code == 400
    assert api.post("/api/filings/ingest/", {"ticker": "AAPL", "years": [2020, 2022], "forms": ["8-K"]},
                    format="json").status_code == 400


def test_run_job_end_to_end_with_fakes(api, user, db, tmp_path):
    from apps.documents import services
    from finsight.ingestion.edgar_client import FilingRef

    ref = FilingRef("AAPL", "0000320193", "Apple Inc.", "10-K", "0000320193-23-000106", "a.htm", "2023-09-30", "2023-11-03")

    class FakeEdgar:
        def list_filings(self, *a):
            return [ref]

        def download(self, r, d):
            p = tmp_path / f"{r.doc_id}.htm"
            p.write_text("<html/>")
            return p

    seen = {}

    def indexer(doc_id, path, meta):
        seen.update(doc_id=doc_id, meta=meta)
        return 42

    job = IngestionJob.objects.create(requested_by=user, params={"ticker": "AAPL", "years": [2023, 2023], "forms": ["10-K"]})
    with mock.patch.object(services, "_notify_reload") as reload_:
        services.run_job(str(job.id), edgar=FakeEdgar(), indexer=indexer, raw_dir=str(tmp_path))
    job.refresh_from_db()
    f = Filing.objects.get()
    assert (job.status, job.progress, job.done) == ("done", 100, 1)
    assert (f.status, f.chunk_count, f.doc_id, f.index_version) == ("indexed", 42, "AAPL_2023_10K", 1)
    assert seen["meta"]["company"] == "Apple" and seen["meta"]["year"] == "2023"
    reload_.assert_called_once()

    # re-running is idempotent: the indexed filing is not indexed again
    job2 = IngestionJob.objects.create(requested_by=user, params=job.params)
    seen.clear()
    services.run_job(str(job2.id), edgar=FakeEdgar(), indexer=indexer, raw_dir=str(tmp_path))
    assert not seen and Filing.objects.get().index_version == 1

    assert api.get(f"/api/ingestion-jobs/{job.id}/").data["progress"] == 100
    assert api.get("/api/filings/?ticker=aapl").data["count"] == 1
    assert Company.objects.get().name == "Apple Inc."


def test_run_job_records_filing_failure(user, db, tmp_path):
    from apps.documents import services
    from finsight.ingestion.edgar_client import FilingRef

    ref = FilingRef("AAPL", "0000320193", "Apple Inc.", "10-K", "acc-1", "a.htm", "2023-09-30", "2023-11-03")

    class Edgar:
        def list_filings(self, *a):
            return [ref]

        def download(self, r, d):
            raise RuntimeError("boom")

    job = IngestionJob.objects.create(requested_by=user, params={"ticker": "AAPL", "years": [2023, 2023], "forms": ["10-K"]})
    services.run_job(str(job.id), edgar=Edgar(), indexer=lambda *a: 1, raw_dir=str(tmp_path))
    job.refresh_from_db()
    assert job.status == "failed" and job.failed == 1 and Filing.objects.get().status == "failed"
    assert "boom" in Filing.objects.get().error


# ---- chat ------------------------------------------------------------------------------------
def test_ask_persists_both_messages(api, user, db):
    from apps.chat import services

    conv = Conversation.objects.create(user=user, filters={"company": ["Acme"]})
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json=ANSWER)

    msg = services.ask(conv, "What were Acme net sales?", {"year": ["2023"]}, client=serving(handler))
    assert seen["company"] == ["Acme"] and seen["year"] == ["2023"] and seen["stream"] is False  # filters merged
    assert msg.role == "assistant" and msg.citations == ANSWER["citations"] and msg.prompt_version == "answer_v1"
    assert conv.messages.count() == 2 and conv.title.startswith("What were")


def test_chat_api_isolates_users(api, other_user, db):
    c = api.post("/api/chat/conversations/", {"title": "mine"}, format="json").data
    assert api.get(f"/api/chat/conversations/{c['id']}/").status_code == 200
    from rest_framework.test import APIClient

    stranger = APIClient()
    stranger.force_authenticate(other_user)
    assert stranger.get(f"/api/chat/conversations/{c['id']}/").status_code == 404
    assert stranger.get("/api/chat/conversations/").data["count"] == 0


def test_chat_message_endpoint_and_feedback(api, user, db):
    conv = api.post("/api/chat/conversations/", {}, format="json").data
    with mock.patch("apps.chat.services.ServingClient") as C:
        C.return_value.query.return_value = ANSWER
        r = api.post(f"/api/chat/conversations/{conv['id']}/messages/", {"question": "Acme net sales?"}, format="json")
    assert r.status_code == 201 and r.data["citations"][0]["page"] == 2
    fb = api.post(f"/api/chat/messages/{r.data['id']}/feedback/", {"thumbs_up": False, "comment": "wrong year"},
                  format="json")
    assert fb.status_code == 200 and Feedback.objects.get().comment == "wrong year"
    detail = api.get(f"/api/chat/conversations/{conv['id']}/").data
    assert detail["messages"][-1]["thumbs_up"] is False
    user_msg = Message.objects.get(role="user")
    assert api.post(f"/api/chat/messages/{user_msg.id}/feedback/", {"thumbs_up": True}, format="json").status_code == 400


def test_chat_stream_proxies_sse_and_saves_message(api, user, db):
    conv = api.post("/api/chat/conversations/", {}, format="json").data
    with mock.patch("apps.chat.services.ServingClient") as C:
        C.return_value.stream.return_value = iter([
            {"event": "retrieval", "data": json.loads(SSE.split("data: ")[1].split("\n")[0])},
            {"event": "token", "data": "Net sales"},
            {"event": "final", "data": {"answer": ANSWER["answer"], "citations": ANSWER["citations"], "refused": False,
                                        "latency_s": 0.4, "guardrails": {"ok": True}, "prompt_version": "answer_v1"}}])
        r = api.post(f"/api/chat/conversations/{conv['id']}/messages/", {"question": "Acme net sales?", "stream": True},
                     format="json")
        body = b"".join(r.streaming_content).decode()
    events = [b.split("\n")[0] for b in body.strip().split("\n\n")]
    assert events == ["event: retrieval", "event: token", "event: final", "event: saved"]
    saved = Message.objects.get(role="assistant")
    assert str(saved.id) in body and saved.chunks == ANSWER["chunks"]


def test_serving_client_parses_sse_and_retries(db):
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] < 3 else httpx.Response(200, json=ANSWER)

    assert serving(flaky).query("q")["refused"] is False and calls["n"] == 3

    evs = list(serving(lambda req: httpx.Response(200, text=SSE)).stream("q"))
    assert [e["event"] for e in evs] == ["retrieval", "token", "final"] and evs[1]["data"] == "Net sales"

    with pytest.raises(UpstreamError):
        serving(lambda req: httpx.Response(500)).query("q")
    with pytest.raises(UpstreamError):  # 4xx is not retried
        n = {"c": 0}

        def bad(req):
            n["c"] += 1
            return httpx.Response(422, text="bad")

        try:
            serving(bad).query("q")
        finally:
            assert n["c"] == 1


def test_upstream_error_maps_to_502(api, user, db):
    conv = api.post("/api/chat/conversations/", {}, format="json").data
    with mock.patch("apps.chat.services.ServingClient") as C:
        C.return_value.query.side_effect = UpstreamError("serving unavailable")
        r = api.post(f"/api/chat/conversations/{conv['id']}/messages/", {"question": "hello there"}, format="json")
    assert r.status_code == 502 and r.json()["error"]["code"] == "upstream_error"


# ---- collections & evaluation ------------------------------------------------------------------
def test_watchlist_crud_and_ownership(api, user, other_user, db):
    Company.objects.create(ticker="AAPL", name="Apple Inc.")
    r = api.post("/api/collections/", {"name": "Big tech", "tickers": ["AAPL"]}, format="json")
    assert r.status_code == 201 and r.data["company_names"] == ["Apple Inc."]
    assert api.post("/api/collections/", {"name": "Big tech", "tickers": []}, format="json").status_code == 400
    Watchlist.objects.create(owner=other_user, name="secret")
    assert [w["name"] for w in api.get("/api/collections/").data["results"]] == ["Big tech"]


def test_import_eval_runs_is_idempotent(api, db, tmp_path):
    (tmp_path / "hybrid.json").write_text(json.dumps({"config": "hybrid", "n": 150, "metrics": {"recall@5": 0.61}}))
    assert import_runs(str(tmp_path)) == 1 and import_runs(str(tmp_path)) == 0
    r = api.get("/api/evaluation/runs/").data["results"][0]
    assert r["config_name"] == "hybrid" and r["metrics"]["recall@5"] == 0.61
    assert api.post("/api/evaluation/runs/refresh/").status_code == 403  # admin only
    assert EvalRun.objects.count() == 1


def test_openapi_schema_builds(api, db):
    r = api.get("/api/schema/")
    assert r.status_code == 200 and b"/api/chat/conversations/" in r.content


# ---- document viewer endpoints ---------------------------------------------------------------
def test_document_file_and_page_endpoints(api, db, settings, tmp_path):
    settings.FINSIGHT_DATA_DIR = str(tmp_path)
    pdfs = tmp_path / "raw" / "financebench" / "pdfs"
    pdfs.mkdir(parents=True)
    (pdfs / "Acme_2023_10K.pdf").write_bytes(b"%PDF-1.4 fake")
    parsed = tmp_path / "interim" / "parsed" / "pdf"
    parsed.mkdir(parents=True)
    (parsed / "Acme_2023_10K.json").write_text(json.dumps(
        {"pages": [{"text": "cover", "tables": []}, {"text": "Net sales 5,000", "tables": [{"markdown": "| a |"}]}]}))

    r = api.get("/api/documents/Acme_2023_10K/file/")
    assert r.status_code == 200 and r["Content-Type"] == "application/pdf" and b"".join(r.streaming_content).startswith(b"%PDF")
    p = api.get("/api/documents/Acme_2023_10K/pages/1/").data
    assert p["text"] == "Net sales 5,000" and p["tables"] == ["| a |"] and p["page_count"] == 2
    assert api.get("/api/documents/Acme_2023_10K/pages/9/").status_code == 404
    assert api.get("/api/documents/Nope_2020_10K/file/").status_code == 404


def test_document_file_blocks_traversal(api, db, settings, tmp_path):
    settings.FINSIGHT_DATA_DIR = str(tmp_path / "data")
    (tmp_path / "data").mkdir()
    (tmp_path / "secret.pdf").write_bytes(b"top secret")
    for bad in ["..%2Fsecret", "....secret", ".."]:
        assert api.get(f"/api/documents/{bad}/file/").status_code in (404,)
    # a Filing row pointing outside the data dir must not be served either
    f = Filing.objects.create(company=Company.objects.create(ticker="X", name="X"), form="10-K", fiscal_year=2023,
                              accession="a1", doc_id="X_2023_10K", storage_path=str(tmp_path / "secret.pdf"))
    assert f and api.get("/api/documents/X_2023_10K/file/").status_code == 404


def test_compare_endpoint_proxies_to_serving(api, db):
    with mock.patch("apps.chat.api.views.ServingClient") as C:
        C.return_value.compare.return_value = {"answer": "A beat B [X_2023_10K:1]", "citations": [], "refused": False, "latency_s": 2.0}
        r = api.post("/api/chat/compare/", {"question": "Compare Apple and Microsoft on operating margin", "company": ["Apple", "Microsoft"]}, format="json")
    assert r.status_code == 200 and r.data["answer"].startswith("A beat B")
    C.return_value.compare.assert_called_once_with("Compare Apple and Microsoft on operating margin", {"company": ["Apple", "Microsoft"]})


# ---- request correlation ---------------------------------------------------------------------
def test_request_id_header_and_log_context(anon, db):
    import logging

    from apps.core.middleware import RequestContextFilter

    r = anon.get("/api/health/")
    assert len(r["X-Request-ID"]) == 32  # generated when the client sends none
    assert anon.get("/api/health/", HTTP_X_REQUEST_ID="trace-abc.1")["X-Request-ID"] == "trace-abc.1"
    hostile = "bad id with spaces; and \"quotes\""
    assert anon.get("/api/health/", HTTP_X_REQUEST_ID=hostile)["X-Request-ID"] != hostile  # replaced, not echoed
    rec = logging.LogRecord("t", logging.INFO, "", 0, "m", (), None)
    assert RequestContextFilter().filter(rec) and rec.request_id == "-"  # outside a request


# ---- abuse controls ----------------------------------------------------------------------------
def test_ingest_can_be_restricted_to_staff(api, user, settings, db):
    settings.INGEST_STAFF_ONLY = True
    body = {"ticker": "AAPL", "years": [2022, 2024], "forms": ["10-K"]}
    assert api.post("/api/filings/ingest/", body, format="json").status_code == 403
    assert IngestionJob.objects.count() == 0
    user.role = "admin"
    user.save()
    with mock.patch("apps.documents.tasks.run_ingestion_job.delay"):
        assert api.post("/api/filings/ingest/", body, format="json").status_code == 202


def test_registration_can_be_closed(anon, settings, db):
    settings.ALLOW_REGISTRATION = False
    r = anon.post("/api/auth/register/", {"email": "x@example.com", "password": "a-long-password-1"})
    assert r.status_code == 403 and "closed" in str(r.json())
