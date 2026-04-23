"""
recdb._expr
~~~~~~~~~~~
Shared expression builder used by both the GNU recutils subprocess
backend and the python-recutils fallback backend.

The expression syntax is the recsel/python-recutils native format, e.g.:
    name = 'Widget A'
    stock < 10
    name ~ '.*Widget.*'   (LIKE translated to regex)
"""


def build_expr(conditions: list[dict]) -> str:
    """Translate a WHERE AST condition list into a recsel expression string."""
    if not conditions:
        return ""
    parts = []
    for c in conditions:
        col, op, val = c["col"], c["op"], c["value"]
        if op == "LIKE":
            parts.append(f"{col} ~ '{like_to_regex(str(val))}'")
        elif op == "=":
            parts.append(f"{col} = '{val}'")
        elif op == "!=":
            parts.append(f"{col} != '{val}'")
        elif op in ("<", ">", "<=", ">="):
            parts.append(f"{col} {op} {val}")
    return " && ".join(parts)


def like_to_regex(val: str) -> str:
    """Translate a SQL LIKE pattern to a recsel regex. % → .* and _ → ."""
    result = ""
    for ch in val:
        if ch == "%":
            result += ".*"
        elif ch == "_":
            result += "."
        elif ch in r"\.+?{}[]|()^$":
            result += "\\" + ch
        else:
            result += ch
    return result
