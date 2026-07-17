# Three-minute OpenAI Build Week demo script

Record a public YouTube video under three minutes. Use a real voiceover; music
and a silent screencast alone do not meet the submission requirement.

## 0:00–0:20 — Problem

> UI reference screenshots are useful, but translating them into a build-ready
> design system is slow and can accidentally encourage copying. InspoMCP turns
> references into original, reusable developer artifacts.

Show the two self-authored sample screenshots or your own permitted references.

## 0:20–0:50 — Create a run

Open FastMCP Inspector or your MCP client. Call `create_inspiration_kit` with
the two screenshots and a clear product goal.

> The server validates every URL, accepts screenshots as primary evidence, and
> creates a durable run ID immediately rather than making the user wait for
> visual analysis.

## 0:50–1:15 — Durable status and privacy

Show `get_status` and, if relevant, `get_vision_analyses`.

> Every stage is persisted in SQLite. The user sees capture, extraction, and
> vision state per source, including warnings and next actions. Privacy mode
> rejects obvious secrets, redacts common sensitive text before storage, and
> hides source identities in client-facing output.

## 1:15–1:50 — Evidence-derived kit

When at least one vision analysis is complete, call `generate_reusable_kit`,
then `get_kit`.

> The output is not a copied page. It is an original kit: design direction,
> page blueprint, component cards, design tokens, and prioritized build tasks,
> synthesized from reusable patterns in the evidence.

## 1:50–2:15 — Component code

Call `generate_component_code` for a visible component card such as
`HeroPanel`.

> The developer can move directly from the kit into framework-specific starter
> code. The server supports Next.js with Tailwind, React with CSS, and
> framework-agnostic HTML and CSS.

## 2:15–2:35 — Judge-ready service

Show `/healthz`, the Docker/hosted endpoint, or the Railway guide.

> The project ships with Docker, bearer-token authentication, structured logs,
> OpenTelemetry support, health checks, and self-authored demo screenshots so
> judges can test the developer tool without rebuilding it from scratch.

## 2:35–3:00 — Codex and GPT-5.6 disclosure

Use only truthful details from your actual build session:

> I built and iterated on InspoMCP in Codex using GPT-5.6. Codex accelerated
> the architecture, tool contracts, capture safety, durable retrieval, privacy
> controls, tests, and deployment packaging. My `/feedback` Session ID for the
> primary build session is [SAY OR SHOW YOUR REAL SESSION ID].

Do not use this wording until you have verified that your primary build session
used GPT-5.6. Otherwise, record what you actually used and continue building in
an eligible Codex/GPT-5.6 session before submitting.
