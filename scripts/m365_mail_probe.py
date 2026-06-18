#!/usr/bin/env python3
"""
m365_mail_probe.py - discover which email transport a Microsoft 365 / Outlook
tenant exposes to an unattended bot (SMTP AUTH vs. Microsoft Graph).

Stdlib only (Python 3.10+): smtplib, ssl, urllib, json, os, argparse.

------------------------------------------------------------------------------
WHAT IT TESTS
------------------------------------------------------------------------------
  (a) SMTP AUTH  - smtp.office365.com:587, STARTTLS, LOGIN with SMTP_USER /
                   SMTP_PASSWORD. Detects the tell-tale tenant lockout:
                   "5.7.139 ... SmtpClientAuthentication is disabled".
  (b) Graph      - client-credentials OAuth token, then optional sendMail via
                   /users/{GRAPH_SENDER}/sendMail.
  (c) Summary    - which transport(s) work + a one-line recommendation.

Each test self-skips if its env vars are missing. Nothing crashes on absence.

------------------------------------------------------------------------------
HOW TO RUN
------------------------------------------------------------------------------
Set whichever creds you have, then run. (In a Claude Code session, prefix the
whole command with `!` to run it in your shell.)

  # --- SMTP path (basic auth / app password) ---
  export SMTP_USER='bot@hertie-school.org'
  export SMTP_PASSWORD='********'

  # --- Graph path (Entra app registration, client credentials) ---
  export GRAPH_TENANT_ID='xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'
  export GRAPH_CLIENT_ID='xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'
  export GRAPH_CLIENT_SECRET='********'
  export GRAPH_SENDER='datasciencelab@hertie-school.org'

  # Auth-only probe (no mail leaves the building):
  python3 scripts/m365_mail_probe.py

  # Also send ONE real test email through whichever transport authenticates:
  python3 scripts/m365_mail_probe.py --send-to you@example.com

Exit code is 0 if at least one transport is usable, else 1.
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

SMTP_HOST = "smtp.office365.com"
SMTP_PORT = 587
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
LOGIN_BASE = "https://login.microsoftonline.com"


# --------------------------------------------------------------------------- #
# small output helpers
# --------------------------------------------------------------------------- #
def hdr(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def line(label: str, value: str) -> None:
    print(f"  {label:<14} {value}")


# --------------------------------------------------------------------------- #
# (a) SMTP AUTH
# --------------------------------------------------------------------------- #
def test_smtp(send_to: str | None) -> bool:
    """Return True if SMTP AUTH login succeeds."""
    hdr("(a) SMTP AUTH  -  smtp.office365.com:587 (STARTTLS)")

    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    if not user or not password:
        line("SKIP", "SMTP_USER / SMTP_PASSWORD not set - skipping SMTP test.")
        return False

    line("User", user)
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.ehlo()
            smtp.login(user, password)  # raises on failure
            line("RESULT", "PASS - SMTP AUTH login succeeded.")

            if send_to:
                msg = (
                    f"From: {user}\r\n"
                    f"To: {send_to}\r\n"
                    f"Subject: M365 probe - SMTP transport OK\r\n"
                    f"\r\n"
                    f"This message confirms SMTP AUTH works for {user}.\r\n"
                )
                smtp.sendmail(user, [send_to], msg)
                line("SENT", f"Test email delivered to {send_to}.")
            return True

    except smtplib.SMTPAuthenticationError as e:
        detail = _decode(e.smtp_error)
        line("RESULT", "FAIL - authentication rejected.")
        line("Code", str(e.smtp_code))
        line("Server", detail)
        if "5.7.139" in detail or "SmtpClientAuthentication is disabled" in detail:
            print(
                "\n  >> DIAGNOSIS: SMTP AUTH is DISABLED for this tenant/mailbox.\n"
                "     Error 5.7.139 means Microsoft has turned off basic-auth SMTP\n"
                "     submission (the default for modern tenants). This is NOT a bad\n"
                "     password. The supported path for an unattended bot is Microsoft\n"
                "     Graph with an Entra app registration (see the Graph test below\n"
                "     and the IT request)."
            )
        else:
            print(
                "\n  >> Check the username/password (or app password if MFA is on).\n"
                "     If this mailbox should use SMTP, an admin may still need to\n"
                "     enable Authenticated SMTP for it."
            )
        return False

    except (smtplib.SMTPException, ssl.SSLError, OSError) as e:
        line("RESULT", f"FAIL - connection/protocol error: {e}")
        return False


def _decode(raw) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return str(raw)


# --------------------------------------------------------------------------- #
# (b) Microsoft Graph
# --------------------------------------------------------------------------- #
def test_graph(send_to: str | None) -> bool:
    """Return True if a Graph token is obtained (and sendMail succeeds if asked)."""
    hdr("(b) Microsoft Graph  -  client-credentials flow")

    tenant = os.environ.get("GRAPH_TENANT_ID")
    client_id = os.environ.get("GRAPH_CLIENT_ID")
    secret = os.environ.get("GRAPH_CLIENT_SECRET")
    sender = os.environ.get("GRAPH_SENDER")

    missing = [
        name
        for name, val in (
            ("GRAPH_TENANT_ID", tenant),
            ("GRAPH_CLIENT_ID", client_id),
            ("GRAPH_CLIENT_SECRET", secret),
            ("GRAPH_SENDER", sender),
        )
        if not val
    ]
    if missing:
        line("SKIP", "Missing: " + ", ".join(missing) + " - skipping Graph test.")
        return False

    line("Tenant", tenant)
    line("Client", client_id)
    line("Sender", sender)

    # --- 1. token request -------------------------------------------------- #
    token = _graph_token(tenant, client_id, secret)
    if token is None:
        return False
    line("RESULT", "PASS - access token obtained.")

    if not send_to:
        print("\n  (Pass --send-to ADDR to also send a real test email via Graph.)")
        return True

    # --- 2. sendMail ------------------------------------------------------- #
    return _graph_send(token, sender, send_to)


def _graph_token(tenant: str, client_id: str, secret: str) -> str | None:
    url = f"{LOGIN_BASE}/{tenant}/oauth2/v2.0/token"
    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }
    ).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            return data.get("access_token")
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", "replace")
        line("RESULT", f"FAIL - token request HTTP {e.code}.")
        line("Body", _trim(err))
        try:
            j = json.loads(err)
            if j.get("error") == "invalid_client":
                print("\n  >> Bad/expired client secret, or client_id wrong.")
            elif j.get("error") == "unauthorized_client":
                print("\n  >> App not authorized in this tenant / wrong tenant id.")
        except json.JSONDecodeError:
            pass
        return None
    except (urllib.error.URLError, OSError) as e:
        line("RESULT", f"FAIL - network error reaching login endpoint: {e}")
        return None


def _graph_send(token: str, sender: str, send_to: str) -> bool:
    url = f"{GRAPH_BASE}/users/{urllib.parse.quote(sender)}/sendMail"
    payload = json.dumps(
        {
            "message": {
                "subject": "M365 probe - Graph transport OK",
                "body": {
                    "contentType": "Text",
                    "content": f"This message confirms Graph sendMail works as {sender}.",
                },
                "toRecipients": [{"emailAddress": {"address": send_to}}],
            },
            "saveToSentItems": True,
        }
    ).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            # sendMail returns 202 Accepted with an empty body on success.
            line("SENT", f"HTTP {resp.status} - test email accepted for {send_to}.")
            return True
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", "replace")
        line("RESULT", f"FAIL - sendMail HTTP {e.code}.")
        line("Body", _trim(err))
        if e.code == 403:
            print(
                "\n  >> 403 = token is valid but the app may not send AS this mailbox.\n"
                "     Likely causes: Mail.Send APPLICATION permission missing/not\n"
                "     admin-consented, OR an Application Access Policy / RBAC scope\n"
                "     excludes this mailbox. See the IT request."
            )
        elif e.code == 404:
            print("\n  >> 404 = GRAPH_SENDER mailbox not found (typo / not licensed).")
        return False
    except (urllib.error.URLError, OSError) as e:
        line("RESULT", f"FAIL - network error calling Graph: {e}")
        return False


def _trim(s: str, n: int = 500) -> str:
    s = s.strip().replace("\n", " ")
    return s if len(s) <= n else s[:n] + " ..."


# --------------------------------------------------------------------------- #
# (c) summary
# --------------------------------------------------------------------------- #
def summarise(smtp_ok: bool, graph_ok: bool) -> int:
    hdr("(c) SUMMARY")
    line("SMTP AUTH", "AVAILABLE" if smtp_ok else "not available")
    line("Graph", "AVAILABLE" if graph_ok else "not available")

    print()
    if graph_ok:
        print("  RECOMMENDATION: Use Microsoft Graph (client credentials) - the "
              "modern, supported transport for an unattended bot.")
    elif smtp_ok:
        print("  RECOMMENDATION: SMTP AUTH works today, but Microsoft is phasing out "
              "basic-auth SMTP - plan to move to Graph (see the IT request).")
    else:
        print("  RECOMMENDATION: No transport is usable yet. Ask IT to enable the "
              "Graph path (Entra app + Mail.Send application permission + access "
              "policy scoped to the sender mailbox). See the IT request.")
    return 0 if (smtp_ok or graph_ok) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe M365 email transports for a bot.")
    ap.add_argument(
        "--send-to",
        metavar="ADDR",
        help="If set, send one real test email through each transport that authenticates.",
    )
    args = ap.parse_args()

    if args.send_to:
        print(f"NOTE: --send-to is set; real test emails will be sent to {args.send_to}.")

    smtp_ok = test_smtp(args.send_to)
    graph_ok = test_graph(args.send_to)
    return summarise(smtp_ok, graph_ok)


if __name__ == "__main__":
    sys.exit(main())
