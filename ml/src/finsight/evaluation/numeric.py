"""Numeric exact match with tolerance, tolerant of unit scale (1,577 vs $1.577 billion)."""

from __future__ import annotations

import re

_NUM = re.compile(r"-?\(?\$?\s?\d[\d,]*(?:\.\d+)?\)?%?")
_SCALES = (1.0, 1e3, 1e-3, 1e6, 1e-6)


def extract_numbers(text: str) -> list[float]:
    out = []
    for raw in _NUM.findall(text):
        neg = raw.startswith("-") or (raw.startswith("(") and raw.endswith(")"))
        digits = re.sub(r"[^\d.]", "", raw)
        if not digits or digits == ".":
            continue
        try:
            v = float(digits)
        except ValueError:
            continue
        out.append(-v if neg else v)
    return out


def numeric_match(pred: str, gold: str, rel_tol: float = 0.01) -> bool | None:
    """None if the gold answer has no number (not a numeric question)."""
    gold_nums = extract_numbers(gold)
    if not gold_nums:
        return None
    target = gold_nums[0]
    for p in extract_numbers(pred):
        for s in _SCALES:
            cand = p * s
            if target == 0:
                if abs(cand) < 1e-9:
                    return True
            elif abs(cand - target) <= rel_tol * abs(target):
                return True
            elif abs(abs(cand) - abs(target)) <= rel_tol * abs(target):  # sign wording ("decreased by 5")
                return True
    return False
