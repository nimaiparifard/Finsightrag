"""Safe arithmetic: walks the AST and allows only numbers and + - * / ** % ( ). No eval()."""

from __future__ import annotations

import ast
import operator
import re
from collections.abc import Callable

_BIN: dict[type, Callable[[float, float], float]] = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY: dict[type, Callable[[float], float]] = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_CALC_TAG = re.compile(r"<calc>(.*?)</calc>", re.S)
_BARE_NUMBER = re.compile(r"[$]?-?\d[\d,]*(?:\.\d+)?%?")


class CalculatorError(ValueError):
    pass


def evaluate(expr: str) -> float:
    expr = expr.replace(",", "").replace("$", "").replace("%", "/100").replace("^", "**").strip()
    if len(expr) > 200:
        raise CalculatorError("expression too long")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise CalculatorError(f"bad expression: {expr!r}") from e
    return _eval(tree.body)


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 10:
            raise CalculatorError("exponent too large")
        try:
            return _BIN[type(node.op)](left, right)
        except ZeroDivisionError as e:
            raise CalculatorError("division by zero") from e
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    raise CalculatorError(f"disallowed syntax: {type(node).__name__}")


def fmt(value: float) -> str:
    return f"{value:,.0f}" if abs(value) >= 1000 and value == int(value) else f"{value:,.4g}" if abs(value) >= 1000 else f"{value:.4g}"


def run_calc_tags(text: str) -> tuple[str, list[float]]:
    """Replace <calc>expr</calc> with 'expr = result'. Returns the new text and the computed values."""
    new, values, _ = run_calc_tags_detailed(text)
    return new, values


def run_calc_tags_detailed(text: str) -> tuple[str, list[float], list[str]]:
    """Like run_calc_tags, also returning the rendered 'expr = result' strings (for guardrails)."""
    results: list[float] = []
    rendered: list[str] = []

    def sub(m: re.Match[str]) -> str:
        try:
            v = evaluate(m.group(1))
        except CalculatorError:
            return m.group(1).strip()
        if _BARE_NUMBER.fullmatch(m.group(1).strip()):
            return m.group(1).strip()  # '<calc>1,577</calc>' is just the number, not a calculation
        results.append(v)
        out = f"{m.group(1).strip()} = {fmt(v)}"
        rendered.append(out)
        return out

    return _CALC_TAG.sub(sub, text), results, rendered
