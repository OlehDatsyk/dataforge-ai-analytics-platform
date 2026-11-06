# Security

This document describes the controls that exist, how they were checked, and what isn't covered. It hasn't had an independent security audit or penetration test.

## Reporting a vulnerability

Please don't open a public issue. Use GitHub's private vulnerability reporting on this repository, once it is enabled, and include steps to reproduce.

## Controls

| Area | Implementation | Checked by |
|---|---|---|
| Passwords | Argon2 hashing, at least 10 characters, mixed character types | Automated tests |
| Sessions | Random 256-bit tokens, stored as SHA-256 hashes, HttpOnly, SameSite=Lax, Secure in production, 72-hour lifetime | Automated tests |
| CSRF | Token derived from the session, required in a header on state-changing requests, plus an origin check | Automated tests |
| Login abuse | Rate limits, identical error messages, and a dummy hash check so timing doesn't reveal accounts | Automated tests (limits and messages) |
| Password reset | Single-use hashed tokens, one-hour expiry, identical responses for unknown addresses, all sessions ended afterwards | Automated tests |
| Authorisation | Server-side workspace and role checks on every request; other workspaces' records return 404 | Tests across all resource types, plus a browser test |
| SQL injection | ORM with bound parameters. Dataset queries quote validated column names and bind values. | Injection strings in tests |
| AI-generated SQL | Not possible. Models produce validated plans only. | Tests with hostile plans |
| DuckDB sandbox | External access disabled and configuration locked after the single file is attached, with memory, thread, and time limits | Tests that attempt to read other files |
| XSS | React escaping, no raw HTML rendering of user data, strict Content Security Policy for scripts | Browser test checks for CSP errors |
| Security headers | CSP, nosniff, frame denial, referrer policy, permissions policy, no-store on the API, HSTS in production | Automated tests |
| File uploads | Content signature must match the extension. Limits on size, rows, and columns. Macro rejection, archive bomb checks, and XML protection. Uploads aren't executed, and formulas aren't evaluated. | Automated tests |
| SSRF | http(s) only, allowed ports only, no URL credentials, all resolved addresses must be public, connection pinned to the checked address, redirects re-validated, secrets dropped across hosts, response size and time limits | Automated tests |
| Stored credentials | Fernet encryption, never returned by the API or logged | Automated tests |
| PostgreSQL connections | Read-only sessions, statement timeout, tables chosen from the server's own list with safely quoted names, generic error messages | Tests on a real server |
| Exports | Formula injection neutralised in CSV and XLSX, with numbers unchanged | Automated tests |
| Error handling | Generic 500 responses. Logs hold exception types only. | Automated test |
| Audit log | Records important actions with identifiers and counts, not data values | Automated test |
| Dependencies | `pip-audit` and `npm audit`, also in the CI workflow | Run for this release, no known vulnerabilities |
| Static analysis | Ruff with security rules. Reviewed exclusions are listed in `pyproject.toml`. | Clean |

## Secrets

- `.env` and related files are ignored by Git, and `.env.example` holds placeholders only.
- Production refuses to start without `SECRET_KEY` and `ENCRYPTION_KEY`.
- Without configured keys in development, secrets are generated once in the ignored data directory.
- AI keys stay on the server and are never exposed by the status endpoint. The Gemini key travels in a header, so it can't appear in logged URLs.

If a secret is ever committed, **rotate it immediately.** Removing it from the current files isn't enough, because it remains in Git history. Revoke and replace the key first, then clean the history if needed.

## Known limitations

- **No independent security review.**
- **No multi-factor authentication or single sign-on.** Accounts aren't locked after failures; only rate limits apply.
- **Rate limits are in-memory and per process,** and they reset on restart. Behind a proxy, configure forwarded headers, or all users share one address.
- **Dataset files and the database aren't encrypted by the application.** Use volume encryption.
- **Malware isn't scanned.** Original files are stored without being executed, and they aren't offered for download by the API, but don't serve the data directory directly.
- **Sign-up is open.** Anyone who can reach the server can register. Restrict access at the network level for private deployments.
- **CSP allows inline styles,** which the chart library needs. Scripts remain restricted to the app's own files.
- **The interactive API docs page** at `/api/docs` is exempt from the CSP, because it loads assets from a public CDN. It contains no user data.
- **Audit logs can be read by workspace admins** and aren't tamper-proof.
- **A determined prompt injection** could mislead an AI explanation, within limits. See [docs/AI_ANALYSIS.md](docs/AI_ANALYSIS.md).
- **`ALLOW_PRIVATE_CONNECTIONS=true`** disables the internal-address protection. Use it only in trusted environments.

## Production checklist

See [Production deployment](docs/INSTALLATION.md#production-deployment).
