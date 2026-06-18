"""collect pure cores -- the grading-spec parse, the junit -> result.json contract, and
the summary glyphs. The gh/git/subprocess wiring is deliberately not tested (testing
strategy: cover the pure logic, not the fan-out).
"""

from __future__ import annotations

from dsl_course import collect


def test_parse_grading_spec_defaults_and_overrides():
    assert collect.parse_grading_spec("") == {
        "type": "individual",
        "format": "py",
        "autograde": True,
        "max_auto": None,
        "tests": "tests",
    }
    spec = collect.parse_grading_spec(
        "type: group\nformat: notebook\nautograde: false\nmax_auto: 20\ntests: solution/tests\n"
    )
    assert spec["type"] == "group" and spec["format"] == "notebook"
    assert spec["autograde"] is False
    assert spec["max_auto"] == 20 and spec["tests"] == "solution/tests"


def test_score_from_junit_counts_only_clean_passes():
    xml = """<testsuite>
      <testcase name="t_pass"/>
      <testcase name="t_fail"><failure>boom</failure></testcase>
      <testcase name="t_err"><error>kaboom</error></testcase>
      <testcase name="t_skip"><skipped/></testcase>
    </testsuite>"""
    result = collect.score_from_junit(xml)
    assert result["max"] == 4 and result["score"] == 1
    passed = {c["name"]: c["passed"] for c in result["tests"]}
    assert passed == {"t_pass": True, "t_fail": False, "t_err": False, "t_skip": False}


def test_score_from_junit_handles_testsuites_root():
    xml = '<testsuites><testsuite><testcase name="a"/></testsuite></testsuites>'
    result = collect.score_from_junit(xml)
    assert result == {"score": 1, "max": 1, "tests": [{"name": "a", "passed": True}]}


def test_summary_lines_use_tick_cross_not_emoji():
    result = {
        "score": 1,
        "max": 2,
        "tests": [{"name": "a", "passed": True}, {"name": "b", "passed": False}],
    }
    text = "\n".join(collect.summary_lines(result))
    assert "✓ a" in text and "✗ b" in text
    assert "✅" not in text and "❌" not in text
