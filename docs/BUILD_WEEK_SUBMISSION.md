# OpenAI Build Week submission pack

## Recommended track

**Developer Tools** — InspoMCP is an MCP developer tool that turns visual UI
references into reusable design specifications and framework-specific component
starter code. It fits the track's focus on developer tooling and agentic
workflows more precisely than the general productivity track.

## Devpost project copy

**Project title:** `InspoMCP: Evidence-to-UI Developer Tool`

**Tagline:**

> A privacy-aware MCP developer tool that turns UI reference screenshots into reusable, evidence-backed design kits and component code.

**Built with:** Python, FastMCP, Pydantic, SQLite, Playwright, Ollama, Docker,
OpenTelemetry, and Codex.

**Repository:** `https://github.com/Amrita-creator/open-build-project`

### Description to paste into Devpost

## Inspiration references should accelerate implementation, not create copying risk

Product teams regularly collect screenshots and landing pages as visual
references, then spend hours manually translating them into a usable hierarchy,
component plan, design tokens, and starter code. InspoMCP turns that scattered
reference process into a safe, inspectable developer workflow.

InspoMCP is an MCP server that accepts two or three UI reference screenshots
and/or safe public URLs. It captures sanitized evidence, extracts page
structure, runs local visual analysis, and synthesizes an original reusable UI
kit. Developers can then retrieve durable progress, generate an evidence-based
kit, and request framework-specific starter code for one component card.

## What it does

- Validates URLs to block localhost, private networks, unsafe redirects, and
  non-standard ports.
- Treats screenshots as primary evidence and safely captures text and metadata
  for public URL enrichment.
- Extracts sections, calls to action, cards, and hierarchy before visual
  synthesis.
- Persists runs, status, warnings, analysis, and generated kits in SQLite so
  long-running work can be retrieved after a restart.
- Generates reusable component cards and original React/Tailwind, React/CSS, or
  framework-agnostic starter code.
- Adds privacy controls: secret rejection, text redaction before persistence,
  opaque source labels, retention metadata, and explicit run deletion.
- Includes ten MCP prompts that help users turn an unclear product idea into a
  better UI-kit request.

## Why it matters

InspoMCP makes reference-driven implementation more reliable and safer. Rather
than copying source wording, branding, or layouts, it extracts reusable
patterns. It also handles failures as first-class product states: blocked
websites, slow visual analysis, and partial evidence return clear status and
next actions instead of silently failing.

## Built with Codex

I used Codex to plan the milestone architecture, implement the FastMCP tools,
iterate on the SQLite pipeline, add tests, harden capture and privacy behavior,
prepare Docker deployment, and create the judge-demo flow. The repository has
80 automated tests covering the capture pipeline, persistence, retrieval,
component generation, production configuration, privacy, and hosted-demo flow.

## Judge quick start

The README includes local installation, Docker instructions, supported-platform
notes, and a Railway deployment guide. The Docker image contains two
self-authored demo screenshots. For a hosted demo, `run_hosted_demo` uses
precomputed, disclosed evidence from those assets, so judges can test the MCP
workflow without providing local files or waiting for a hosted Ollama model.
Use the temporary MCP URL and bearer token supplied in the Devpost
judge-instructions field.

## Required Devpost fields

| Field | What to provide |
|---|---|
| Submitter Type | Select your real status: Individual, Team of Individuals, or Organization. |
| Country of Residence | Select your actual country. |
| Category | `Developer Tools`. |
| Code repository | The repository URL above. Make it public with a license, or share a private repo with `testing@devpost.com` and `build-week-event@openai.com`. |
| Judge test link/instructions | Hosted MCP URL, temporary bearer token, and the judge request from `deployment/railway.md`. |
| `/feedback` Session ID | The ID from the Codex session where most core work was performed. |
| Plugin/dev-tool instructions | Paste the section below. |

### Plugin/developer-tool instructions to paste

Supported platforms: Windows 11 with Python 3.10+ is the tested local path.
Docker Desktop is supported for the containerized HTTP service. macOS and Linux
host setups are not yet verified.

Local setup: follow `README.md` under **Run locally**, then start Inspector with
`fastmcp dev src/inspo_mcp/server.py:mcp`.

Hosted judge test: connect to the supplied HTTPS MCP endpoint using
`Authorization: Bearer <temporary-demo-token>`. Call `run_hosted_demo`, then
use its `demo_...` run ID with `get_kit` and `generate_component_code`. This
tool transparently uses precomputed evidence from self-authored bundled assets;
it does not claim to analyze judge-provided images or call Ollama. The complete
request is in `deployment/railway.md`.

## Before pressing Submit

1. Run `/feedback` in the Codex session that contains most of the core project
   work and copy the generated Session ID.
2. Record and upload the required public, voiceover demo video (under three
   minutes); use `docs/BUILD_WEEK_DEMO_SCRIPT.md`.
3. Deploy the temporary Railway judge instance and paste its URL and bearer
   token into Devpost's private judge-instructions field.
4. Add an open-source license before making the repository public. MIT is a
   simple option, but choose the license yourself before it is added.
5. Confirm that any statement about using GPT-5.6 is true for the Codex session
   whose feedback ID you submit. Do not claim a model version that you did not
   use.
