# Security Policy

## Local-first threat model

Link is designed for local personal knowledge management. `serve.py` binds to
`127.0.0.1`, rejects host/bind flags, and rejects unexpected `Host` headers
outside `localhost`/`127.0.0.1`. It has no authentication, so it should not be
exposed directly to the public internet.

Local write APIs also require the `X-Link-Local-Action` header. When a browser
supplies `Origin` or `Referer`, Link accepts local mutations only from
`localhost` or `127.0.0.1`. Local mutation endpoints are also rate-limited in
memory so a runaway local client receives JSON `429` responses instead of
unbounded writes. Link does not grant browser CORS access; preflight requests
receive local JSON `405` responses without `Access-Control-Allow-Origin`.
The local viewer sends a Content Security Policy that limits scripts,
connections, images, and framing to local-safe sources. It also sends browser
isolation and permissions-policy headers. HTML pages, JSON API responses, and
served local static/raw files use `Cache-Control: no-store` plus legacy
`Pragma`/`Expires` cache guards because they can contain personal memory
snippets or source media.

The server and MCP package do not call external APIs, send telemetry, or require
secrets. Raw sources and generated wiki pages are user data and are ignored by
git by default.

Release hygiene fails if tracked Python or shell runtime code adds common
outbound HTTP clients or direct `curl`/`wget` calls. This keeps Link's
local-first promise testable instead of only documented.

`link ingest-status` and MCP `ingest_status` scan raw source files locally for
secret-looking values. If a pending raw file is flagged, Link withholds the
normal ingest prompt until the file is redacted.

## Sensitive files

Do not commit:

- `raw/` source files
- generated wiki pages under `wiki/sources/`, `wiki/concepts/`,
  `wiki/entities/`, `wiki/comparisons/`, or `wiki/explorations/`
- `.mcpregistry_*`
- `*.token`
- build outputs under `mcp_package/dist/`

Use `git status --ignored` before release if you want to inspect local-only
files, and use `git archive` or normal GitHub releases rather than zipping a
working directory.

## Reporting vulnerabilities

Please use a private maintainer contact channel for security issues first. Do
not post secrets, private wiki content, raw source files, or exploitable details
in public GitHub issues. If a public issue is the only available path, keep it
high level and ask for a private follow-up channel.
