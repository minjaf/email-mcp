"""IMAP read path and SMTP send for a single mailbox (e.g. Yandex over TLS)."""

from __future__ import annotations

import base64
import mimetypes
import os
import smtplib
from dataclasses import dataclass
from datetime import date
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from imapclient import IMAPClient


def _env(name: str, *alts: str, default: str | None = None) -> str | None:
    for key in (name, *alts):
        v = os.environ.get(key)
        if v:
            return v
    return default


@dataclass(frozen=True)
class MailConfig:
    address: str
    password: str
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int

    @classmethod
    def from_env(cls) -> "MailConfig":
        address = _env("MAILBOX_EMAIL", "YANDEX_EMAIL")
        password = _env("MAILBOX_PASSWORD", "YANDEX_APP_PASSWORD")
        if not address or not password:
            raise ValueError(
                "Missing credentials: set MAILBOX_EMAIL and MAILBOX_PASSWORD "
                "(or YANDEX_EMAIL and YANDEX_APP_PASSWORD)."
            )
        imap_host = _env("IMAP_HOST", default="imap.yandex.com") or "imap.yandex.com"
        smtp_host = _env("SMTP_HOST", default="smtp.yandex.com") or "smtp.yandex.com"
        imap_port = int(_env("IMAP_PORT", default="993") or "993")
        smtp_port = int(_env("SMTP_PORT", default="465") or "465")
        return cls(
            address=address,
            password=password,
            imap_host=imap_host,
            imap_port=imap_port,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
        )


def imap_client(cfg: MailConfig) -> IMAPClient:
    return IMAPClient(cfg.imap_host, port=cfg.imap_port, ssl=True)


def list_mail_folders(cfg: MailConfig) -> list[dict[str, Any]]:
    with imap_client(cfg) as client:
        client.login(cfg.address, cfg.password)
        out: list[dict[str, Any]] = []
        for flags, delimiter, name in client.list_folders():
            out.append(
                {
                    "name": _decode_text(name),
                    "delimiter": delimiter.decode() if isinstance(delimiter, bytes) else delimiter,
                    "flags": [f.decode() if isinstance(f, bytes) else str(f) for f in (flags or ())],
                }
            )
        return out


def _criteria(
    *,
    text: str | None,
    unseen_only: bool,
    since_iso: str | None,
) -> list[Any]:
    parts: list[Any] = []
    if unseen_only:
        parts.append("UNSEEN")
    if since_iso:
        y, m, d = (int(x) for x in since_iso.strip().split("-", 2))
        parts.extend(["SINCE", date(y, m, d)])
    if text:
        parts.extend(["TEXT", text])
    if not parts:
        parts = ["ALL"]
    return parts


def search_messages(
    cfg: MailConfig,
    *,
    folder: str,
    text: str | None,
    unseen_only: bool,
    since_iso: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    criteria = _criteria(text=text, unseen_only=unseen_only, since_iso=since_iso)
    lim = max(1, min(limit, 500))
    with imap_client(cfg) as client:
        client.login(cfg.address, cfg.password)
        client.select_folder(folder, readonly=True)
        uids = client.search(criteria)
        uids = sorted(uids, reverse=True)[:lim]
        if not uids:
            return []
        fetched = client.fetch(uids, ["ENVELOPE", "FLAGS", "RFC822.SIZE"])
        rows: list[dict[str, Any]] = []
        for uid in uids:
            data = fetched.get(uid) or {}
            env = data.get(b"ENVELOPE")
            subj = ""
            frm = ""
            to = ""
            date_hdr = ""
            if env:
                subj = _decode_mime_words(env.subject or b"") if env.subject else ""
                if env.from_:
                    frm = _format_addresses(env.from_)
                if env.to:
                    to = _format_addresses(env.to)
                if env.date:
                    date_hdr = env.date.isoformat() if hasattr(env.date, "isoformat") else str(env.date)
            flags = data.get(b"FLAGS") or ()
            flag_list = [f.decode() if isinstance(f, bytes) else str(f) for f in flags]
            size = int(data.get(b"RFC822.SIZE") or 0)
            rows.append(
                {
                    "uid": uid,
                    "subject": subj,
                    "from": frm,
                    "to": to,
                    "date": date_hdr,
                    "flags": flag_list,
                    "size_bytes": size,
                }
            )
        return rows


def _decode_mime_words(s: bytes | str) -> str:
    if isinstance(s, str):
        return s
    try:
        return str(make_header(decode_header(s.decode("latin-1", errors="replace"))))
    except Exception:
        return s.decode("utf-8", errors="replace")


def _decode_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return _decode_mime_words(value)
    return str(value)


def _format_address(addr: Any) -> str:
    name = _decode_text(getattr(addr, "name", None)).strip()
    mailbox = _decode_text(getattr(addr, "mailbox", None)).strip()
    host = _decode_text(getattr(addr, "host", None)).strip()

    if mailbox and host:
        email_addr = f"{mailbox}@{host}"
    else:
        email_addr = _decode_text(addr).strip()

    if name and email_addr and name != email_addr:
        return f"{name} <{email_addr}>"
    return email_addr or name


def _format_addresses(addr_list: Any) -> str:
    if not addr_list:
        return ""
    parts = [_format_address(a) for a in addr_list]
    return ", ".join(part for part in parts if part)


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _safe_part_content(part: Message) -> str:
    try:
        return part.get_content()
    except Exception:
        raw = part.get_payload(decode=True)
        if raw is None:
            return ""
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return str(raw)


def _extract_bodies(msg: Message) -> tuple[str, str]:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain" and not part.get_content_disposition():
                plain_parts.append(_safe_part_content(part))
            elif ctype == "text/html" and not part.get_content_disposition():
                html_parts.append(_safe_part_content(part))
    else:
        ctype = msg.get_content_type()
        if ctype == "text/plain":
            plain_parts.append(_safe_part_content(msg))
        elif ctype == "text/html":
            html_parts.append(_safe_part_content(msg))
        else:
            plain_parts.append(_safe_part_content(msg))

    return ("\n\n".join(plain_parts).strip(), "\n\n".join(html_parts).strip())


def _iter_attachment_parts(msg: Message) -> list[tuple[int, Message]]:
    attachments: list[tuple[int, Message]] = []
    idx = 0
    for part in msg.walk():
        disposition = part.get_content_disposition()
        filename = part.get_filename()
        if disposition == "attachment" or filename:
            attachments.append((idx, part))
            idx += 1
    return attachments


def _extract_attachments(msg: Message) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for idx, part in _iter_attachment_parts(msg):
        payload = part.get_payload(decode=True)
        attachments.append(
            {
                "attachment_index": idx,
                "filename": _decode_header_value(part.get_filename()),
                "content_type": part.get_content_type(),
                "content_disposition": part.get_content_disposition() or "attachment",
                "content_id": _decode_header_value(part.get("Content-ID")),
                "size_bytes": len(payload) if isinstance(payload, bytes) else None,
            }
        )
    return attachments


def _fetch_message(cfg: MailConfig, folder: str, uid: int) -> tuple[Message, list[str]]:
    parser = BytesParser(policy=policy.default)
    with imap_client(cfg) as client:
        client.login(cfg.address, cfg.password)
        client.select_folder(folder, readonly=True)
        fetched = client.fetch([uid], ["BODY.PEEK[]", "FLAGS"])
        data = fetched.get(uid) or {}
        raw = data.get(b"BODY[]")
        if raw is None:
            for k, v in data.items():
                if isinstance(k, bytes) and k.startswith(b"BODY") and isinstance(v, (bytes, memoryview)):
                    raw = bytes(v)
                    break
        if not raw:
            raise ValueError(f"No body returned for UID {uid} in folder {folder!r}")
        msg: Message = parser.parsebytes(raw if isinstance(raw, bytes) else bytes(raw))
        flags = data.get(b"FLAGS") or ()
        flag_list = [f.decode() if isinstance(f, bytes) else str(f) for f in flags]
        return msg, flag_list


def read_message_by_uid(cfg: MailConfig, folder: str, uid: int) -> dict[str, Any]:
    msg, flag_list = _fetch_message(cfg, folder, uid)
    plain, html = _extract_bodies(msg)
    return {
        "uid": uid,
        "folder": folder,
        "subject": _decode_header_value(msg.get("subject")),
        "from": _decode_header_value(msg.get("from")),
        "to": _decode_header_value(msg.get("to")),
        "cc": _decode_header_value(msg.get("cc")),
        "reply_to": _decode_header_value(msg.get("reply-to")),
        "message_id": _decode_header_value(msg.get("message-id")),
        "in_reply_to": _decode_header_value(msg.get("in-reply-to")),
        "references": _decode_header_value(msg.get("references")),
        "date": _decode_header_value(msg.get("date")),
        "flags": flag_list,
        "attachments": _extract_attachments(msg),
        "body_plain": plain,
        "body_html": html,
    }


def get_attachment_content(
    cfg: MailConfig,
    folder: str,
    uid: int,
    attachment_index: int | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    msg, _ = _fetch_message(cfg, folder, uid)
    attachments = _iter_attachment_parts(msg)
    if not attachments:
        raise ValueError(f"Message UID {uid} in folder {folder!r} has no attachments")

    selected: tuple[int, Message] | None = None
    if attachment_index is not None:
        for idx, part in attachments:
            if idx == attachment_index:
                selected = (idx, part)
                break
        if selected is None:
            raise ValueError(f"Attachment index {attachment_index} not found")
    elif filename:
        wanted = filename.strip().lower()
        for idx, part in attachments:
            if _decode_header_value(part.get_filename()).strip().lower() == wanted:
                selected = (idx, part)
                break
        if selected is None:
            raise ValueError(f"Attachment filename {filename!r} not found")
    elif len(attachments) == 1:
        selected = attachments[0]
    else:
        raise ValueError("Message has multiple attachments; provide attachment_index or filename")

    idx, part = selected
    payload = part.get_payload(decode=True)
    content = payload if isinstance(payload, bytes) else b""
    return {
        "uid": uid,
        "folder": folder,
        "attachment_index": idx,
        "filename": _decode_header_value(part.get_filename()),
        "content_type": part.get_content_type(),
        "content_disposition": part.get_content_disposition() or "attachment",
        "size_bytes": len(content),
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


def _guess_content_type(filename: str | None, explicit: str | None) -> tuple[str, str]:
    if explicit:
        guessed = explicit
    else:
        guessed = mimetypes.guess_type(filename or "")[0] or "application/octet-stream"
    maintype, _, subtype = guessed.partition("/")
    if not maintype or not subtype:
        return ("application", "octet-stream")
    return (maintype, subtype)


def _attachment_bytes_from_spec(spec: dict[str, Any]) -> tuple[str, bytes, str | None]:
    path_value = spec.get("path")
    filename = spec.get("filename")
    content_type = spec.get("content_type")

    if path_value:
        path = Path(str(path_value)).expanduser()
        data = path.read_bytes()
        return (filename or path.name, data, content_type)

    if "content_text" in spec:
        if not filename:
            raise ValueError("Attachment spec with content_text requires filename")
        return (str(filename), str(spec.get("content_text") or "").encode("utf-8"), content_type or "text/plain")

    if "content_base64" in spec:
        if not filename:
            raise ValueError("Attachment spec with content_base64 requires filename")
        encoded = str(spec.get("content_base64") or "")
        data = base64.b64decode(encoded, validate=True)
        return (str(filename), data, content_type)

    raise ValueError("Attachment spec must include one of: path, content_text, content_base64")


def _add_attachments_to_message(msg: EmailMessage, attachments: list[dict[str, Any]] | None) -> list[str]:
    attachment_names: list[str] = []
    for spec in attachments or []:
        filename, data, explicit_type = _attachment_bytes_from_spec(spec)
        maintype, subtype = _guess_content_type(filename, explicit_type)
        attachment_names.append(filename)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return attachment_names


def send_message(
    cfg: MailConfig,
    *,
    to_addrs: list[str],
    subject: str,
    body_text: str,
    body_html: str | None,
    cc: list[str] | None,
    bcc: list[str] | None,
    reply_to_header: str | None,
    in_reply_to: str | None,
    references: str | None,
    attachments: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    msg = EmailMessage()
    msg["From"] = cfg.address
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = ", ".join(cc)
    if reply_to_header:
        msg["Reply-To"] = reply_to_header
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    if body_html:
        msg.set_content(body_text or "(no plain text body)")
        msg.add_alternative(body_html, subtype="html")
    else:
        msg.set_content(body_text)

    attachment_names = _add_attachments_to_message(msg, attachments)

    recipients = list(to_addrs)
    if cc:
        recipients.extend(cc)
    if bcc:
        recipients.extend(bcc)

    with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=60) as smtp:
        smtp.login(cfg.address, cfg.password)
        smtp.send_message(msg, from_addr=cfg.address, to_addrs=recipients)

    return {
        "ok": True,
        "to": recipients,
        "subject": subject,
        "in_reply_to": in_reply_to or "",
        "attachment_count": len(attachment_names),
        "attachment_names": attachment_names,
    }
