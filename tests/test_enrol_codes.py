"""enrol-codes + mailer pure cores: code assignment must fill only blanks and stay unique
(a clash would let one student claim another's row), the message must carry the code, and
the roster must round-trip with the new enrol_code column. SMTP send is wiring, not tested.
"""

from __future__ import annotations

from dsl_course import enrol_codes, mailer, roster


def _student(email="a@x.edu", name="Ada", code="", handle=""):
    return roster.Student("1", email, name, handle, "", "A", code)


def test_assign_codes_fills_blanks_only_and_is_unique():
    students = [_student(code=""), _student(code="dsl-keep"), _student(code="")]
    # deterministic generator so the test can assert behaviour, not randomness
    seq = iter(
        ["dsl-aaa", "dsl-keep", "dsl-bbb"]
    )  # second clashes with existing -> skipped
    added = enrol_codes.assign_codes(students, gen=lambda: next(seq))
    assert added == 2
    assert students[1].enrol_code == "dsl-keep"  # existing untouched
    codes = [s.enrol_code for s in students]
    assert len(set(codes)) == 3 and "" not in codes  # all filled, all unique


def test_make_code_shape():
    code = enrol_codes.make_code()
    assert code.startswith("dsl-") and len(code) == 10
    suffix = code[4:]  # the random part (the "dsl-" prefix legitimately contains 'l')
    assert not (
        set(suffix) & set("0o1il")
    )  # ambiguous chars excluded from the random part


def test_code_message_contains_code_and_targets_university_email():
    s = _student(email="ada@uni.edu", name="Ada", code="dsl-xyz123")
    to, subject, body = enrol_codes.code_message(
        s, "https://github.com/org/welcome/issues"
    )
    assert to == "ada@uni.edu"
    assert "dsl-xyz123" in body and "welcome" in body


def test_roster_dump_roundtrips_with_enrol_code():
    students = [
        _student(email="ada@uni.edu", name="Ada", code="dsl-abc", handle="ada-l")
    ]
    reparsed = roster.parse(roster.dump(students))
    assert reparsed[0].enrol_code == "dsl-abc"
    assert reparsed[0].hertie_email == "ada@uni.edu"
    assert reparsed[0].onboarded is True


def test_mailer_dry_run_previews_without_config():
    msgs = [("a@x.edu", "Subj", "Body"), ("b@x.edu", "Subj", "Body")]
    # no SMTP env needed for a dry-run preview
    assert mailer.send_bulk(msgs, dry_run=True) == 2


def test_smtp_config_from_env_needs_all_three(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert mailer.smtp_config_from_env() is None
    monkeypatch.setenv("SMTP_HOST", "smtp.x")
    monkeypatch.setenv("SMTP_USER", "u")
    monkeypatch.setenv("SMTP_PASSWORD", "p")
    cfg = mailer.smtp_config_from_env()
    assert cfg and cfg.port == 587 and cfg.from_addr == "u"  # defaults applied


def test_graph_config_from_env_needs_all_four(monkeypatch):
    for k in ("GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET", "GRAPH_SENDER"):
        monkeypatch.delenv(k, raising=False)
    assert mailer.graph_config_from_env() is None
    monkeypatch.setenv("GRAPH_TENANT_ID", "t")
    monkeypatch.setenv("GRAPH_CLIENT_ID", "c")
    monkeypatch.setenv("GRAPH_CLIENT_SECRET", "s")
    assert mailer.graph_config_from_env() is None  # sender still missing
    monkeypatch.setenv("GRAPH_SENDER", "bot@x.edu")
    cfg = mailer.graph_config_from_env()
    assert cfg and cfg.sender == "bot@x.edu" and cfg.tenant_id == "t"
