# Railway hosted judge demo

This project can be hosted as one authenticated FastMCP HTTP service. The
deployed MCP endpoint is `https://<generated-domain>/mcp` and the health check
is `https://<generated-domain>/healthz`.

## What this deployment includes

- The production Docker image and Streamable HTTP MCP endpoint.
- Bearer-token authentication.
- A persistent SQLite database and managed capture-artifact directory.
- Built-in, self-authored demo screenshot inputs at:
  - `/app/demo/aurora-landing.png`
  - `/app/demo/ops-dashboard.png`
- MCP tools, prompts, privacy guidance, health probes, and JSON logs.

The deployment does not automatically include an Ollama model. M3, M4, M7,
M8, M9, M10, and M11 remain usable, but M5 visual analysis and the evidence
derived M6 kit require a separately deployed local-vision sidecar or a future
approved hosted vision provider.

## Deploy from GitHub

1. Push the current branch to `Amrita-creator/open-build-project` on GitHub.
2. In Railway, create a project and choose **Deploy from GitHub Repo**.
3. Select `Amrita-creator/open-build-project`. Railway reads `railway.toml`
   and builds the existing Dockerfile.
4. Open the service **Variables** tab and set:

   ```text
   INSPO_MCP_ENVIRONMENT=production
   INSPO_MCP_AUTH_TOKEN=<long-random-demo-token>
   INSPO_MCP_DATABASE_PATH=/var/lib/inspo-mcp/inspo_mcp.db
   INSPO_MCP_CAPTURE_ROOT=/var/lib/inspo-mcp/captures
   INSPO_MCP_HTTP_PATH=/mcp
   INSPO_MCP_CONTACT_EMAIL=<your-contact-email>
   RAILWAY_RUN_UID=0
   ```

   Generate the token locally and paste it only into Railway's secret-value
   field:

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   `RAILWAY_RUN_UID=0` is required because Railway volumes are root-owned at
   mount time, while this image normally runs as an unprivileged application
   user. This is an acceptable temporary hackathon-demo trade-off; migrate to
   an entrypoint that drops privileges after initializing the mounted volume
   before treating this as a long-lived production service.

5. Attach one Railway Volume at `/var/lib/inspo-mcp`. Do not add replicas:
   SQLite and local capture files require a single writer.
6. In **Settings > Networking**, generate a public domain. Do not put the
   bearer token in the domain, README, or a client-side web page.
7. Railway uses `/healthz` from `railway.toml`; inspect deploy logs until the
   health check returns `200`.

Railway volumes preserve the SQLite database and captured artifacts across
deploys. A volume permits only one replica, which matches this server's
single-writer storage design.

## Judge connection and test

Give judges these two values through the hackathon submission, not a public
social post:

```text
MCP URL: https://<generated-domain>/mcp
Bearer token: <temporary-demo-token>
```

In a remote-MCP-capable client, add the MCP URL and use
`Authorization: Bearer <temporary-demo-token>`.

First verify the public service:

```powershell
Invoke-RestMethod https://<generated-domain>/healthz
```

Then call `create_inspiration_kit` with the server-side bundled images:

```json
{
  "project_goal": "Build a calm operations workspace for product teams that helps them identify priorities and resolve incidents. Primary action: Review priorities.",
  "framework": "nextjs-tailwind",
  "inspiration_urls": [],
  "inspiration_screenshots": [
    "/app/demo/aurora-landing.png",
    "/app/demo/ops-dashboard.png"
  ],
  "privacy_mode": true,
  "retention_days": 7
}
```

The paths above exist inside the deployed container. A remote MCP server cannot
read paths such as `C:/Users/Judge/Pictures/example.png` from a judge's own
computer. Use a future upload flow for arbitrary judge screenshots.

After the hackathon, rotate `INSPO_MCP_AUTH_TOKEN` or remove the service and
volume. The current bearer-token model is single-tenant and intended only for
a short-lived demo.
