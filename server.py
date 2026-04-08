#!/usr/bin/env python3
"""Personal MCP server: mailbox over IMAP + SMTP.

Default mode is stdio for local MCP clients. For ChatGPT web app integration,
run with --transport streamable-http and expose the port over public HTTPS.

Environment:
  MAILBOX_EMAIL, MAILBOX_PASSWORD — required
    (aliases: YANDEX_EMAIL, YANDEX_APP_PASSWORD)
  IMAP_HOST (default imap.yandex.com), IMAP_PORT (993)
  SMTP_HOST (default smtp.yandex.com), SMTP_PORT (465)
  MCP_TRANSPORT (default stdio), MCP_HOST (default 0.0.0.0), MCP_PORT (default 8000)
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from mail_ops import (
    MailConfig,
    get_attachment_content,
    list_mail_folders,
    read_message_by_uid,
    search_messages,
    send_message,
)

mcp = FastMCP(
    "personal-mail",
    instructions=(
        "Personal mailbox tools over IMAP/SMTP. "
        "Use an app password for Yandex; From must match the authenticated address. "
        "For actual threaded replies, pass in_reply_to and references headers from the original email. "
        "Attachments can be downloaded as base64 and sent either from local paths or base64 payloads."
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
    """Fetch one message by IMAP UID without marking it as read.

    Returns decoded headers, plain/html bodies, and attachment metadata.
    """
    return read_message_by_uid(_config(), folder, uid)


@mcp.tool()
def get_attachment(
    uid: int,
    folder: str = "INBOX",
    attachment_index: int | None = None,
    filename: str | None = None,
) -> dict:
    """Fetch one attachment from an email and return it as base64.

    Use attachment_index from read_email(). If the message has only one attachment,
    you can omit both attachment_index and filename.
    """
    return get_attachment_content(
        _config(),
        folder=folder,
        uid=uid,
        attachment_index=attachment_index,
        filename=filename,
    )


@mcp.tool()
def send_email(
    to: str,
    subject: str,
    body: str,
    body_html: str | None = None,
    cc: str = "",
    bcc: str = "",
    reply_to_header: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> dict:
    """Send mail via SMTP/SSL.

    `to`, `cc`, `bcc` are comma-separated addresses.
    `reply_to_header` sets the RFC Reply-To header.
    `in_reply_to` and `references` are used for proper message threading.

    `attachments` is an optional list. Each item must contain one of:
      - {"path": "/absolute/or/relative/file.pdf"}
      - {"filename": "note.txt", "content_text": "hello"}
      - {"filename": "file.pdf", "content_base64": "...", "content_type": "application/pdf"}
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
        reply_to_header=reply_to_header,
        in_reply_to=in_reply_to,
        references=references,
        attachments=attachments,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Personal email MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default=os.getenv("MCP_TRANSPORT", "stdio"),
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("MCP_HOST", "0.0.0.0"),
        help="Bind host for HTTP transports (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", "8000")),
        help="Bind port for HTTP transports (default: 8000)",
    )
    args = parser.parse_args()

    if args.transport != "stdio":
        mcp.settings.host = args.host
        mcp.settings.port = args.port

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
