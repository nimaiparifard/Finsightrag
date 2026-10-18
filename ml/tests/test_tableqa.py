import json

import pytest

from finsight.evaluation.tableqa import load_finqa, load_tatqa, run_tableqa, to_hits
from finsight.llm import FakeLLMProvider


@pytest.fixture
def finqa_dir(tmp_path):
    d = tmp_path / "finqa" / "dataset"
    d.mkdir(parents=True)
    (d / "test.json").write_text(json.dumps([{
        "id": "AAA/2019/page_1.pdf-1", "pre_text": ["Revenue is in millions."], "post_text": ["End."],
        "table": [["", "2019", "2018"], ["revenue", "1,200", "1,000"]],
        "qa": {"question": "what was the percent change in revenue?", "answer": "20%", "program": "subtract(1200, 1000), divide(#0, 1000)"}}]))
    return str(tmp_path / "finqa")


@pytest.fixture
def tatqa_dir(tmp_path):
    d = tmp_path / "tatqa" / "dataset_raw"
    d.mkdir(parents=True)
    (d / "tatqa_dataset_dev.json").write_text(json.dumps([{
        "table": {"uid": "t1", "table": [["", "2019"], ["Sales", "50"]]},
        "paragraphs": [{"uid": "p2", "order": 2, "text": "Second."}, {"uid": "p1", "order": 1, "text": "First."}],
        "questions": [
            {"uid": "q1", "order": 1, "question": "What are the sales?", "answer": [50], "answer_type": "span"},
            {"uid": "q2", "order": 2, "question": "Who is the CEO?", "answer": ["Ann"], "answer_type": "span"},
            {"uid": "q3", "order": 3, "question": "Sales doubled?", "answer": 100, "answer_type": "arithmetic"}]}]))
    return str(tmp_path / "tatqa")


def test_loaders(finqa_dir, tatqa_dir):
    f = load_finqa(finqa_dir)
    assert len(f) == 1 and f[0].answer == "20%" and f[0].text == "Revenue is in millions. End." and f[0].answer_type == "arithmetic"
    t = load_tatqa(tatqa_dir)
    assert [q.id for q in t] == ["q1", "q3"]  # the non-numeric 'CEO' question is dropped
    assert t[0].text == "First. Second."  # paragraphs ordered by `order`
    assert len(load_tatqa(tatqa_dir, numeric_only=False)) == 3


def test_gold_context_reaches_the_prompt_and_calculator_scores(finqa_dir):
    item = load_finqa(finqa_dir)[0]
    hits = to_hits(item)
    assert [h.chunk.chunk_type for h in hits] == ["table", "text"] and "| revenue | 1,200 | 1,000 |" in hits[0].chunk.text

    seen = {}

    def responder(msgs):
        seen["sys"] = msgs[0].content
        return "Revenue rose <calc>(1200 - 1000) / 1000 * 100</calc>%."

    out = run_tableqa(FakeLLMProvider(responder=responder), [item])
    assert "1,200" in seen["sys"]
    assert out["numeric_em"] == 1.0 and out["used_calculator_rate"] == 1.0 and out["em_when_calculator_used"] == 1.0
    wrong = run_tableqa(FakeLLMProvider(reply="It rose 55%."), [item])
    assert wrong["numeric_em"] == 0.0 and wrong["used_calculator_rate"] == 0.0
