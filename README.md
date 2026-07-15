# InspoMCP

An MCP server that turns two or three public UI inspiration URLs into a reusable,
build-ready design starter kit. It has no frontend: connect it to an MCP client
such as Codex once the local server is running.

## Current status

The primary `create_inspiration_kit` tool is wired up with typed Pydantic
contracts and a deterministic mock response. It already returns the five product
artifacts:

1. design direction
2. page blueprint
3. reusable component cards
4. design tokens
5. implementation tasks

M1 adds a local SQLite run record behind the existing tool. Each successful call
now receives a persisted run ID and is stored as `completed`, while the output
remains a mock kit. The database is created at `data/inspo_mcp.db` by default.
Set `INSPO_MCP_DATABASE_PATH` to use another location.

M2 validates every submitted URL before a run is created. It allows only public
HTTP/HTTPS sources on their default ports and rejects localhost, private or
reserved IPs, and hostnames that resolve to private networks.

M3 captures evidence for each safe source before the mocked kit is produced:
sanitized visible text, a full-page Chromium screenshot, a SHA-256 content hash,
manual redirect metadata, and a SQLite `sources` record. Redirect destinations
and every browser-routed HTTP request are revalidated. Artifacts are stored at
`data/captures/<run-id>/` by default and successful captures are reused when the
same run is retried. Set `INSPO_MCP_CAPTURE_ROOT` to use another location.

When a site blocks automatic capture, callers can provide up to three local
PNG, JPEG, or WebP screenshots as URL-mapped fallbacks. The image is copied into
the managed evidence store only after automatic capture fails; the response then
contains a warning explaining that user-provided evidence was used.

Automatic requests use a transparent, configurable `User-Agent` and are paced at
one request per host per second by default. Set `INSPO_MCP_CONTACT_EMAIL` to a
real project contact; do not imitate a browser or retry a `403`/`429` response.
If a server sends `Retry-After`, the capture records that instruction and stops.

M4 turns sanitized page text into persisted per-site structure evidence: inferred
sections, calls to action, candidate cards, and a heading hierarchy. This stage
is intentionally conservative; screenshot-only fallback sources are marked
`awaiting_vision` rather than producing invented structure. Results are stored in
SQLite for the next phase.

The next phase adds multimodal, per-site analysis using this M4 evidence and
screenshots where available.

## Run locally

Prerequisite: Python 3.10 or newer. This machine's existing `.venv` points to a
missing Python installation, so recreate it after Python is available. Then
install the project dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m playwright install chromium
python -m unittest discover -s tests
fastmcp inspect src/inspo_mcp/server.py:mcp
fastmcp run src/inspo_mcp/server.py:mcp
```

## Test M3 capture

The M3 unit tests do not use the network or a real browser; they inject a fake
fetcher and screenshotter while checking safe redirects, text sanitization,
artifact persistence, SQLite metadata, and retry caching:

```powershell
python -m unittest discover -s tests -p "test_capture.py" -v
```

Run the complete suite with:

```powershell
python -m unittest discover -s tests -v
```

`stdio` is the default transport. Do not print application logs to standard
output while it is running; MCP messages use that channel.

## Example tool call

```json
{
  "inspiration_urls": [
    "https://example.com",
    "https://example.org"
  ],
  "project_goal": "Build a landing page for an AI developer tool.",
  "framework": "nextjs-tailwind",
  "fallback_screenshots": [
    {
      "source_url": "https://www.wikipedia.org/",
      "image_path": "C:\\Users\\Amrita\\Pictures\\wikipedia.png"
    }
  ]
}
```
