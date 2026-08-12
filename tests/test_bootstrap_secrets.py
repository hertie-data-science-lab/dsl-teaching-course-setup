"""Central mail secrets propagate to each org exactly like DSL_BOT_TOKEN.

The enrolment-code and grade-distribution buttons run in a course org and read GRAPH_*
(preferred) or SMTP_* from that org's secrets (dsl_course.mailer). Rather than pasting
nine secrets into every course org by hand, they are held once on the central repo and
copied on at bootstrap. What these pin:

- only what is actually configured centrally propagates, and an UNSET secret arrives from
  Actions as an empty string, so empty must mean absent (never "set to blank");
- the copy carries the bot token's scoping (visibility=selected over the existing infra
  repos) - `selected` is what reaches the public `.github` repo the send buttons run in,
  and it keeps the credentials out of student-facing/content repos;
- no secret VALUE is ever printed.
"""

from __future__ import annotations

import pytest

from dsl_course import bootstrap_course as bc

SECRET_VALUES = {
    "GRAPH_TENANT_ID": "tenant-uuid",
    "GRAPH_CLIENT_ID": "client-uuid",
    "GRAPH_CLIENT_SECRET": "s3cret-value",
    "GRAPH_SENDER": "no-reply@hertie-school.org",
}


class FakeGh:
    """Records the gh invocations, and answers the repo-existence/visibility probes."""

    def __init__(self, existing=(".github",), private=()):
        self.existing = set(existing)
        self.private = set(private)
        self.calls: list[tuple[str, ...]] = []

    def gh(self, *args):
        self.calls.append(args)
        return 0, ""

    def repo_exists(self, org, name):
        self.calls.append(("repo_exists", name))
        return name in self.existing

    def repo_is_private(self, org, name):
        return name in self.private

    def secret_sets(self) -> dict[str, tuple[str, ...]]:
        """{secret name: the `gh secret set` argv} for each org-secret call."""
        return {c[2]: c for c in self.calls if c[:2] == ("secret", "set")}


@pytest.fixture
def fake(monkeypatch):
    f = FakeGh()
    monkeypatch.setattr(bc, "gh", f.gh)
    monkeypatch.setattr(bc, "repo_exists", f.repo_exists)
    monkeypatch.setattr(bc, "repo_is_private", f.repo_is_private)
    for name in bc.MAIL_SECRETS:
        monkeypatch.delenv(name, raising=False)
    return f


def test_no_mail_secrets_configured_centrally_is_a_silent_skip(fake, capsys):
    assert bc.propagate_mail_secrets("Course-E1") == 0
    assert fake.calls == []  # nothing set, and not even a repo probe
    assert "no mail secrets configured centrally" in capsys.readouterr().out


def test_unset_secrets_arrive_empty_and_count_as_absent(fake, monkeypatch):
    # GitHub passes an undeclared `secrets.X` to the step as "", so a whole env of empty
    # strings must behave exactly like an env with nothing set - NOT set nine blanks.
    for name in bc.MAIL_SECRETS:
        monkeypatch.setenv(name, "")
    assert bc.propagate_mail_secrets("Course-E1") == 0
    assert fake.calls == []


def test_only_the_configured_secrets_propagate(fake, monkeypatch):
    # A Graph-only central config (the preferred transport): the four GRAPH_* secrets go,
    # the five SMTP_* fallbacks stay absent rather than being created empty.
    for name, value in SECRET_VALUES.items():
        monkeypatch.setenv(name, value)

    assert bc.propagate_mail_secrets("Course-E1") == 4
    assert set(fake.secret_sets()) == set(SECRET_VALUES)


def test_propagated_secrets_carry_the_bot_token_scoping(fake, monkeypatch):
    # visibility=selected over the EXISTING infra repos: gh defaults org secrets to
    # `private`, which never reaches the public `.github` repo the send buttons run in.
    fake.existing = {".github", "welcome", "classroom-config"}
    monkeypatch.setenv("GRAPH_TENANT_ID", "tenant-uuid")

    bc.propagate_mail_secrets("Cohort-f2026")

    argv = fake.secret_sets()["GRAPH_TENANT_ID"]
    assert argv[:3] == ("secret", "set", "GRAPH_TENANT_ID")
    assert argv[argv.index("--org") + 1] == "Cohort-f2026"
    assert argv[argv.index("--visibility") + 1] == "selected"
    assert argv[argv.index("--repos") + 1] == ".github,welcome,classroom-config"


def test_scoping_probe_runs_once_for_the_whole_batch(fake, monkeypatch):
    # _infra_repos costs one API call per infra repo; nine secrets must not mean nine
    # probes of the same three repos.
    for name, value in SECRET_VALUES.items():
        monkeypatch.setenv(name, value)

    bc.propagate_mail_secrets("Course-E1")

    probes = [c for c in fake.calls if c[0] == "repo_exists"]
    assert probes == [("repo_exists", r) for r in bc.INFRA_REPOS]


def test_private_infra_repos_get_the_repo_level_mirror(fake, monkeypatch):
    # Free-plan gap: a `selected` org secret is never delivered to a PRIVATE repo, so the
    # value is mirrored as a repo secret there - same as DSL_BOT_TOKEN.
    fake.existing = {".github", "classroom-config"}
    fake.private = {"classroom-config"}
    monkeypatch.setenv("SMTP_HOST", "smtp.example.org")

    bc.propagate_mail_secrets("Cohort-f2026")

    mirrors = [c for c in fake.calls if "--repo" in c]
    assert len(mirrors) == 1
    assert mirrors[0][mirrors[0].index("--repo") + 1] == "Cohort-f2026/classroom-config"


def test_no_secret_value_is_ever_logged(fake, monkeypatch, capsys):
    for name, value in SECRET_VALUES.items():
        monkeypatch.setenv(name, value)
    fake.private = {".github"}  # exercise the repo-level mirror log line too

    bc.propagate_mail_secrets("Course-E1")

    out = capsys.readouterr()
    printed = out.out + out.err
    for value in SECRET_VALUES.values():
        assert value not in printed
    assert "4 mail secret(s) propagated" in printed


def test_values_are_stripped_before_being_set(fake, monkeypatch):
    # A pasted secret often carries a trailing newline; it must not end up in the token.
    monkeypatch.setenv("GRAPH_SENDER", " no-reply@hertie-school.org\n")
    bc.propagate_mail_secrets("Course-E1")
    argv = fake.secret_sets()["GRAPH_SENDER"]
    assert argv[argv.index("--body") + 1] == "no-reply@hertie-school.org"


def test_mail_secret_names_match_what_the_mailer_reads():
    # The names ARE the contract: mailer reads them straight from env in the course org,
    # so a rename here silently stops every enrolment-code / grade email.
    from dsl_course import mailer

    source = (
        mailer.graph_config_from_env.__code__,
        mailer.smtp_config_from_env.__code__,
    )
    read = {c for code in source for c in code.co_consts if isinstance(c, str)}
    assert set(bc.MAIL_SECRETS) <= read
