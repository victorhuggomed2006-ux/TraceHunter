# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's private reporting:
the repository's **Security** tab → **Report a vulnerability**. You will get a reply as soon as
possible, and a fix will be coordinated with you before details are made public.

## Supported versions

Only the latest release receives security fixes (the project is in alpha).

## Threat model, in short

TraceHunter stores what your application sends to it: prompts, documents, tool arguments and model
answers can all end up in the database. Treat the database file as sensitive.

- **No authentication.** The web viewer is meant for the local machine. It binds to `127.0.0.1`
  by default and rejects any `Host` header other than `127.0.0.1`, `localhost` and `[::1]`
  (override with `TRACEHUNTER_ALLOWED_HOSTS`). Binding it to another interface exposes every trace
  to everyone who can reach the port. If you need remote access, put an authenticating reverse
  proxy with TLS in front of it.
- **The Claude Code collector stores what the assistant saw.** Each tool result is cut at 300
  characters and common secret formats are masked, but a file the assistant read can still contain
  secrets that end up in the database. Do not share or commit the database file.
- **Redaction is best effort.** `@tracer.observe()` masks arguments whose *name* looks like a
  secret and caps each recorded value at 1000 characters. It cannot recognise a secret inside a
  value. Use `capture_io=False` for functions that handle sensitive data.
- **Database permissions.** The SQLite file is created with mode `0600` where the platform
  supports it. On Windows the folder's ACLs apply.
- **Read-only API.** The HTTP API only reads traces; nothing is ingested over HTTP.
