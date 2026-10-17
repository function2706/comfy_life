"""条件式の評価.

書式: "key op value" をカンマ (または &&) で並べた AND 条件.
  op   : >= <= > < = !=
  value: 数値 / 文字列 / true,false / "07:30" (時刻→分) / "a|b" (= と != で OR)
例: "free=true, mood>=50, phase=night|midnight"
空文字は常に真. 未知のキーは偽.
"""
import re

_TERM = re.compile(r"^\s*([A-Za-z_][\w.]*)\s*(>=|<=|!=|=|>|<)\s*(.*?)\s*$")
_cache = {}


def parse(expr):
    expr = (expr or "").strip()
    if expr in _cache:
        return _cache[expr]
    terms = []
    for part in re.split(r",|&&", expr):
        if not part.strip():
            continue
        m = _TERM.match(part)
        if not m:
            raise ValueError("条件式を解釈できません: %r" % part.strip())
        if m.group(2) in ("<", ">", "<=", ">="):
            try:
                _num(m.group(3))
            except ValueError:
                raise ValueError("大小比較の値が数値ではありません: %r" % part.strip())
        terms.append((m.group(1), m.group(2), m.group(3)))
    _cache[expr] = terms
    return terms


def count(expr):
    try:
        return len(parse(expr))
    except ValueError:
        return 0


def _num(s):
    s = str(s).strip()
    if re.match(r"^\d{1,2}:\d{2}$", s):
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    return float(s)


def _eq(v, a):
    a = a.strip()
    if isinstance(v, bool):
        return (a.lower() in ("true", "1", "yes", "on")) == v
    if isinstance(v, (int, float)):
        try:
            return float(v) == _num(a)
        except ValueError:
            return False
    return str(v) == a


def check(expr, ctx):
    try:
        terms = parse(expr)
    except ValueError:
        return False
    for key, op, val in terms:
        if key not in ctx:
            return False
        v = ctx[key]
        if op in ("=", "!="):
            hit = any(_eq(v, a) for a in val.split("|"))
            if (op == "=") != hit:
                return False
            continue
        try:
            x, y = float(v), _num(val)
        except (TypeError, ValueError):
            return False
        if op == ">=" and not x >= y:
            return False
        if op == "<=" and not x <= y:
            return False
        if op == ">" and not x > y:
            return False
        if op == "<" and not x < y:
            return False
    return True
