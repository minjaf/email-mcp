# email-mcp

Small personal MCP server for a single mailbox over IMAP + SMTP.

It is aimed at a private setup first:
- one mailbox
- credentials supplied through environment variables
- read mail over IMAP
- send mail over SMTP
- works well with Yandex Mail defaults, but can be pointed at any IMAP/SMTP provider

## What I changed

This repo originally worked only in `stdio` mode. That is fine for local MCP clients, but **ChatGPT web integration needs an HTTP MCP endpoint**. The server now supports:

- `stdio` for local/dev use
- `streamable-http` for ChatGPT web app use
- `sse` for compatibility

I also fixed a mail-threading issue:
- the old `reply_to` parameter only set the `Reply-To` header
- real replies should usually use `In-Reply-To` and `References`
- `read_email` now returns those headers so they can be passed back into `send_email`

And I improved `read_email` output by returning:
- decoded headers
- attachment metadata
- message threading headers

## Files

- `server.py` — MCP tool definitions and transport startup
- `mail_ops.py` — IMAP/SMTP implementation
- `requirements.txt` — Python dependencies

## Environment

Required:

```bash
export MAILBOX_EMAIL="you@example.com"
export MAILBOX_PASSWORD="your-app-password"
```

Optional provider settings:

```bash
export IMAP_HOST="imap.yandex.com"
export IMAP_PORT="993"
export SMTP_HOST="smtp.yandex.com"
export SMTP_PORT="465"
```

Optional MCP server settings:

```bash
export MCP_TRANSPORT="stdio"
export MCP_HOST="0.0.0.0"
export MCP_PORT="8000"
```

Aliases also supported for convenience:

```bash
export YANDEX_EMAIL="you@yandex.ru"
export YANDEX_APP_PASSWORD="..."
```

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run locally with stdio

```bash
python server.py
```

This is the right mode for local MCP clients that spawn the process directly.

## Run for ChatGPT web app

ChatGPT web needs a public HTTPS MCP endpoint. Start the server in HTTP mode:

```bash
python server.py --transport streamable-http --host 0.0.0.0 --port 8000
```

Then expose that port through a public HTTPS tunnel or reverse proxy, and register the resulting MCP URL in ChatGPT.

## Tools exposed

### `list_folders()`
Lists available IMAP folders.

### `search_emails(folder="INBOX", text=None, unseen_only=False, since_date=None, limit=30)`
Searches messages by IMAP criteria.

Returns items like:
- `uid`
- `subject`
- `from`
- `to`
- `date`
- `flags`
- `size_bytes`

### `read_email(uid, folder="INBOX")`
Fetches a full message without marking it read.

Returns:
- decoded headers
- `message_id`
- `in_reply_to`
- `references`
- `attachments`
- `body_plain`
- `body_html`

### `send_email(...)`
Sends a message through SMTP.

Important parameters:
- `reply_to_header` — sets the Reply-To header
- `in_reply_to` — threading header
- `references` — threading header

For a real reply, use `in_reply_to` and usually also `references`.

## Yandex notes

Typical Yandex defaults are:

- IMAP: `imap.yandex.com:993` over SSL/TLS
- SMTP: `smtp.yandex.com:465` over SSL/TLS

Use an **app password**, not your main account password.

## Next sensible upgrades

- attachment download tool
- move/archive/delete tools with confirmation
- OAuth instead of env-based credentials
- tests with mocked IMAP/SMTP backends
