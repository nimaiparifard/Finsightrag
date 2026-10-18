from finsight.generation.answer import build_messages, finalize_answer
from finsight.generation.calculator import run_calc_tags
from finsight.generation.guardrails import check_answer
from finsight.interfaces import Chunk, Hit


def hits():
    return [Hit(Chunk("3M_2018_10K", 59, "Purchases of property, plant and equipment (PP&E) (1,577) (1,373)",
                      meta={"company": "3M"}), 1.0)]


def test_placeholder_citation_from_a_live_run_is_rejected():
    # real output of qwen2.5-7b: it copied the prompt's placeholder instead of a real tag
    answer = "The FY2018 capital expenditure for 3M is 1,577 USD millions. [doc_id:38_45]"
    rep = check_answer(answer, hits())
    assert not rep.ok and rep.no_citations and rep.malformed_citations == ["[doc_id:38_45]"]


def test_answer_without_any_citation_fails_but_refusal_does_not():
    assert check_answer("Capex was 1,577 million.", hits()).no_citations
    assert check_answer("Capex was 1,577 million.", hits()).ok is False
    assert check_answer("Not found in the provided documents.", hits()).ok


def test_valid_citation_still_passes_and_a_stray_bad_one_fails():
    good = "Capex was 1,577 USD millions [3M_2018_10K:59]."
    assert check_answer(good, hits()).ok
    mixed = good + " Also see [3M_2018_10K:3]."  # well-formed but that page was not retrieved
    r = check_answer(mixed, hits())
    assert not r.ok and r.invalid_citations == [("3M_2018_10K", 3)]


def test_bare_number_in_calc_tag_is_not_rendered_as_a_calculation():
    text, vals = run_calc_tags("Capex was <calc>1,577</calc> million, up <calc>(1577-1373)/1373*100</calc>%.")
    assert text.startswith("Capex was 1,577 million") and "1,577 = 1,577" not in text
    assert len(vals) == 1 and "= 14.86" in text  # the real calculation is still computed


def test_prompt_v2_shows_a_real_example_tag_not_a_placeholder():
    msgs = build_messages("What was capex?", hits(), prompt="answer_v2")
    system = msgs[0].content
    assert "[3M_2018_10K:59]" in system and "--- [3M_2018_10K:59]" in system
    assert "[doc_id:page]" not in system  # the literal placeholder is what the 7B model copied before
    assert "Do not use <calc> for a number you simply read" in system


def test_finalize_answer_flags_the_live_failure_end_to_end():
    ans = finalize_answer("Capex is <calc>1,577</calc> USD millions. [doc_id:38_45]", hits())
    assert "1,577 = 1,577" not in ans.text and ans.citations == [] and ans.guardrails.ok is False
