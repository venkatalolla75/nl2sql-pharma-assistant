"""Collects structured test results (question/SQL/expected/actual/pass-fail) across the
whole pytest run and renders TESTS.md at session end — see conftest.py's
pytest_sessionfinish hook. This is the mechanism producing the graded deliverable
document; pytest's pass/fail is the "run it, fix failures, repeat" gate, and this module
is what turns that same run into the human-readable report.
"""

from dataclasses import dataclass, field


@dataclass
class Result:
    category: str
    name: str
    passed: bool
    question: str | None = None
    sql: str | None = None
    expected: str | None = None
    actual: str | None = None
    notes: str = ""


RESULTS: list[Result] = []


def record(category, name, passed, question=None, sql=None, expected=None,
           actual=None, notes=""):
    RESULTS.append(Result(
        category=category, name=name, passed=passed, question=question,
        sql=sql, expected=expected, actual=actual, notes=notes,
    ))
    return passed


def render_markdown(pytest_outcomes: list[tuple[str, str]] | None = None,
                     env_label: str | None = None) -> str:
    pytest_outcomes = pytest_outcomes or []
    env_label = env_label or (
        "FastAPI in-process + the local Postgres instance with the full 2M-row "
        "dataset loaded"
    )
    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r.passed)

    p_total = len(pytest_outcomes)
    p_passed = sum(1 for _, o in pytest_outcomes if o == "passed")
    p_failed = sum(1 for _, o in pytest_outcomes if o == "failed")
    p_skipped = sum(1 for _, o in pytest_outcomes if o == "skipped")

    skipped_note = (
        "" if total else
        "\n\n_No LLM-dependent cases produced rich records this run — either AWS "
        "credentials were not configured (see PLAN.md blockers) or this run only "
        "covered the DB-security/validator layer. The pytest summary below still "
        "reflects everything that actually ran._\n"
    )

    lines = [
        "# TESTS.md — Automated Test Results",
        "",
        f"**pytest: {p_passed}/{p_total} passed, {p_failed} failed, "
        f"{p_skipped} skipped.**",
        "",
        f"**Rich cases (question/SQL/expected/actual captured below): "
        f"{passed}/{total} passed.**" + skipped_note,
        "",
        "Generated automatically by `tests/report.py` via a `pytest_sessionfinish` hook "
        f"— every row below reflects an actual run against {env_label}, "
        "not hand-written expectations.",
        "",
    ]

    if pytest_outcomes:
        lines.append("## Full pytest results")
        lines.append("")
        lines.append("| Test | Outcome |")
        lines.append("|---|---|")
        icon = {"passed": "✅", "failed": "❌", "skipped": "⏭️"}
        for nodeid, outcome in pytest_outcomes:
            short = nodeid.split("::", 1)[-1]
            lines.append(f"| `{short}` | {icon.get(outcome, outcome)} {outcome} |")
        lines.append("")

    categories = sorted(set(r.category for r in RESULTS))
    for cat in categories:
        cat_results = [r for r in RESULTS if r.category == cat]
        cat_passed = sum(1 for r in cat_results if r.passed)
        lines.append(f"## {cat} ({cat_passed}/{len(cat_results)} passed)")
        lines.append("")
        for r in cat_results:
            status = "✅ PASS" if r.passed else "❌ FAIL"
            lines.append(f"### {status} — {r.name}")
            if r.question:
                lines.append(f"- **Question**: {r.question}")
            if r.sql:
                lines.append(f"- **Generated SQL**: `{r.sql}`")
            if r.expected is not None:
                lines.append(f"- **Expected**: {r.expected}")
            if r.actual is not None:
                lines.append(f"- **Actual**: {r.actual}")
            if r.notes:
                lines.append(f"- **Notes**: {r.notes}")
            lines.append("")

    return "\n".join(lines)
