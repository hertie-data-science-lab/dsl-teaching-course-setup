"""dsl-course mailer -- send templated per-recipient email over SMTP (preview-then-send).

The reusable, previewable replacement for the Excel -> Power Automate -> Outlook mail-merge:
build one message per roster row, print them all for review (`dry_run`), then send via SMTP
using credentials from the environment (one SMTP_* secret). Shared by enrolment-code
distribution and grade notifications - both just hand `send_bulk` a list of messages.

Environment (set as repo/org secrets, wired into the workflow):
    SMTP_HOST, SMTP_USER, SMTP_PASSWORD   (required)
    SMTP_PORT (default 587), SMTP_FROM (default = SMTP_USER)
"""

from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from .utils import log, log_err, log_ok

# A single message: (recipient, subject, body).
Message = tuple[str, str, str]


@dataclass
class SMTPConfig:
    host: str
    port: int
    user: str
    password: str
    from_addr: str


def smtp_config_from_env() -> SMTPConfig | None:
    """Build the SMTP config from env, or None if the required secrets are unset."""
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    if not (host and user and password):
        return None
    return SMTPConfig(
        host=host,
        port=int(os.environ.get("SMTP_PORT", "587")),
        user=user,
        password=password,
        from_addr=os.environ.get("SMTP_FROM", user),
    )


def send_one(cfg: SMTPConfig, to: str, subject: str, body: str) -> bool:
    """Send one plain-text message over STARTTLS. Returns True on success."""
    msg = EmailMessage()
    msg["From"] = cfg.from_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(cfg.host, cfg.port) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(cfg.user, cfg.password)
            server.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        log_err(f"send to {to} failed: {exc}")
        return False


def send_bulk(
    messages: list[Message], dry_run: bool = False, cfg: SMTPConfig | None = None
) -> int:
    """Preview (dry_run) or send a batch. Returns the count previewed/sent.

    dry_run prints every message in full - the all-recipients-at-once preview the Power
    Automate flow never gave - and sends nothing."""
    if dry_run:
        for to, subject, body in messages:
            log(f"\n--- to: {to}\n--- subject: {subject}\n{body}")
        log_ok(f"DRY-RUN previewed {len(messages)} message(s) - nothing sent")
        return len(messages)

    cfg = cfg or smtp_config_from_env()
    if cfg is None:
        log_err(
            "SMTP not configured (set SMTP_HOST / SMTP_USER / SMTP_PASSWORD) - "
            "nothing sent."
        )
        return 0
    sent = 0
    for to, subject, body in messages:
        if send_one(cfg, to, subject, body):
            log_ok(f"sent -> {to}")
            sent += 1
    return sent
