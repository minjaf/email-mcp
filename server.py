#!/usr/bin/env python3
"""Personal MCP server: Yandex (or any) mailbox over IMAP + SMTP.

Uses stdio transport by default — no TCP listen port on this host (avoids
conflicts with panels/VPN such as 3xUI on 443/2096/etc.).

Environment:
  MAILBOX_EMAIL, MAILBOX_PASSWORD — required (aliases: YANDEX_EMAIL, YANDEX_APP_PASSWORD)
  IMAP_HOST (default imap.yandex.com), IMAP_PORT (993)
  SMTP_HOST (default smtp.yandex.com), SMTP_PORT (465)
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mail_ops import (
    MailConfig,
    list_mail_folders,
    read_message_by_uid,
    search_messages,
    send_message,
)

mcp = FastMCP(
    "personal-mail",
    instructions=(
        "Personal mailbox tools over IMAP/SMTP. "
        "Use an app password for Yandex; From must match the authenticated address."
    ),
)


def _config() -> MailConfig:
    return MailConfig.from_env()


def _parse_recipients(csv: str) -> list[str]:
    return [p.strip() for p in csv.replace(";", ",").split(",") if p.strip()]


@mcp.tool()
def list_folders() -> list[dict]:
    """List IMAP folders with name, delimiter, and flags."""
    return list_mail_folders(_config())


@mcp.tool()
def search_emails(
    folder: str = "INBOX",
    text: str | None = None,
    unseen_only: bool = False,
    since_date: str | None = None,
    limit: int = 30,
) -> list[dict]:
    """Search messages in a folder by optional full-text, unseen filter, and SINCE date.

    since_date: optional ISO date YYYY-MM-DD (IMAP SINCE, mail date on server).
    Returns uid, subject, from, to, date, flags, size_bytes (newest first, truncated to limit).
    """
    return search_messages(
        _config(),
        folder=folder,
        text=text,
        unseen_only=unseen_only,
        since_iso=since_date,
        limit=limit,
    )


@mcp.tool()
def read_email(uid: int, folder: str = "INBOX") -> dict:
    """Fetch one message by IMAP UID (does not mark as read). Plain + HTML bodies when present."""
    return read_message_by_uid(_config(), folder, uid)


@mcp.tool()
def send_email(
    to: str,
    subject: str,
    body: str,
    body_html: str | None = None,
    cc: str = "",
    bcc: str = "",
    reply_to: str | None = None,
) -> dict:
    """Send mail via SMTP/SSL. `to`, `cc`, `bcc` are comma-separated addresses.

    From is always the configured mailbox. Use an app password for Yandex.
    """
    to_list = _parse_recipients(to)
    if not to_list:
        raise ValueError("At least one recipient in `to` is required.")
    cc_list = _parse_recipients(cc) if cc else []
    bcc_list = _parse_recipients(bcc) if bcc else []
    return send_message(
        _config(),
        to_addrs=to_list,
        subject=subject,
        body_text=body,
        body_html=body_html,
        cc=cc_list or None,
        bcc=bcc_list or None,
        reply_to=reply_to,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
