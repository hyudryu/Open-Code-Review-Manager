/** Docs page — static in-app documentation matching the shipped product.
 * Sources: README.md, docs/ARCHITECTURE.md, docs/API.md, docs/MCP.md,
 * docs/WEBHOOKS.md. */

import { Link } from "react-router-dom";
import { PageHeader } from "../layouts/AppLayout";
import { Badge, CopyButton, Table, TBody, Td, Th, THead, Tr } from "../components/ui";
import { IconExternal } from "../components/ui/icons";
import layout from "../layouts/layout.module.css";

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className={`${layout.section} ${layout.stack}`} aria-label={title}>
      <h2 className={layout.sectionTitle} style={{ margin: 0 }}>{title}</h2>
      {children}
    </section>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className={layout.monoPath} style={{ fontSize: 12.5 }}>{children}</code>
  );
}

function CodeBlock({ text, copyLabel }: { text: string; copyLabel?: string }) {
  return (
    <div style={{ position: "relative" }}>
      {copyLabel ? (
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 6 }}>
          <CopyButton text={text} label={copyLabel} />
        </div>
      ) : null}
      <pre
        style={{
          font: "var(--text-code)",
          background: "var(--code-bg)",
          borderRadius: 8,
          padding: 12,
          overflowX: "auto",
          margin: 0,
        }}
      >
        {text}
      </pre>
    </div>
  );
}

function P({ children }: { children: React.ReactNode }) {
  return (
    <p className={layout.small} style={{ margin: 0, lineHeight: 1.6 }}>{children}</p>
  );
}

const TOC = [
  { id: "getting-started", label: "Getting started" },
  { id: "concepts", label: "Concepts" },
  { id: "architecture", label: "Architecture" },
  { id: "api", label: "REST API" },
  { id: "mcp", label: "MCP" },
  { id: "webhooks", label: "Webhooks" },
  { id: "exports", label: "Exports" },
  { id: "security", label: "Security & privacy" },
  { id: "troubleshooting", label: "Troubleshooting" },
];

const API_GROUPS = [
  { group: "/folders", routes: "CRUD, /{id}/scan, /{id}/register", purpose: "Watched roots scanned for git repositories" },
  { group: "/projects", routes: "CRUD, /{id}/refresh-branches, /{id}/fetch, /{id}/branches, /{id}/pull-requests, /{id}/jobs", purpose: "Registered repositories, their branch cache, and open pull requests" },
  { group: "/providers", routes: "CRUD, /{id}/test, /{id}/discover-models, /{id}/models", purpose: "LLM endpoints, credentials, and models" },
  { group: "/review-profiles", routes: "CRUD, /{id}/duplicate", purpose: "Reusable review configuration bundles" },
  { group: "/jobs", routes: "CRUD + /preview, /cancel, /retry, /resume, /duplicate, /move, /pause, /findings, /logs, /session, /export, /events (SSE)", purpose: "Review submission, lifecycle, and results" },
  { group: "/queue", routes: "GET, /pause, /resume, /reorder, /clear-completed", purpose: "Durable dispatch queue" },
  { group: "/webhooks", routes: "CRUD, /{id}/test, /{id}/deliveries, /webhook-deliveries/{id}/replay", purpose: "Signed delivery callbacks" },
  { group: "/ (system)", routes: "/health, /system/info, /system/ocr, /system/mcp, /system/diagnostics/bundle, /settings", purpose: "Health, diagnostics, and editable settings" },
];

const EXPORT_FORMATS = [
  { format: "md", use: "Markdown report for people" },
  { format: "json", use: "Full structured result (same as the MCP result resource)" },
  { format: "csv", use: "Spreadsheet import" },
  { format: "jsonl", use: "One finding per line for pipelines" },
  { format: "txt", use: "Plain text summary" },
  { format: "agent-prompt", use: "Findings formatted as a fix-it prompt for a coding agent" },
  { format: "github-summary", use: "GitHub-flavored summary for PR comments" },
];

export function DocsPage() {
  return (
    <>
      <PageHeader
        title="Documentation"
        subtitle="How OCR Manager works — setup, concepts, API, MCP, webhooks, and troubleshooting."
      />

      <div className={layout.row} style={{ gap: 6, marginBottom: 24, maxWidth: 860 }}>
        {TOC.map((item) => (
          <a key={item.id} href={`#${item.id}`} style={{ textDecoration: "none" }}>
            <Badge tone="neutral">{item.label}</Badge>
          </a>
        ))}
      </div>

      <div className={`${layout.stack} ${layout.stackLg}`} style={{ maxWidth: 860 }}>
        <Section id="getting-started" title="Getting started">
          <P>
            OCR Manager is a local-first control plane for the{" "}
            <Code>ocr</Code> CLI (Alibaba OpenCodeReview). Prerequisites: Python 3.12+,
            Node.js 20+, Git, and the review engine itself:
          </P>
          <CodeBlock text="npm i -g @alibaba-group/open-code-review" copyLabel="Copy" />
          <P>
            The app runs fine without <Code>ocr</Code> installed — OCR-dependent
            actions show a clear "OCR not detected" state until it is.
          </P>
          <P>Start everything with one command from the repository root:</P>
          <CodeBlock
            text={"start.bat        # Windows (double-click or run)\n./start.sh       # macOS / Linux / Git Bash"}
            copyLabel="Copy"
          />
          <P>
            The launcher creates the virtualenv and installs dependencies on first run,
            builds the frontend when needed, then starts a single process on{" "}
            <Code>http://127.0.0.1:8372</Code> serving the UI, the REST API
            (<Code>/api/v1</Code>), and the MCP endpoint (<Code>/mcp</Code>). Database
            migrations, the queue worker, and the webhook worker all start with it.
          </P>
          <P>
            Override the port for one startup with{" "}
            <Code>scripts/start.ps1 -Port 9000</Code> or{" "}
            <Code>scripts/start.sh --port 9000</Code>. The persistent setting is{" "}
            <Code>OCR_CC_PORT</Code> in <Code>.env</Code>.
          </P>
          <P>
            On first launch, the <Link to="/setup">setup wizard</Link> walks through
            five steps — Environment (OCR detection), Project, Provider, Profile, Done —
            so a working review is one minute away.
          </P>
        </Section>

        <Section id="concepts" title="Concepts">
          <dl className={layout.dl}>
            <dt>Folders</dt>
            <dd>
              Watched root directories. A depth-limited, symlink-safe scan discovers git
              repositories inside them; discovered repos register as projects in one click.
            </dd>
            <dt>Projects</dt>
            <dd>
              Registered git repositories with a cached branch list (local + remote refs),
              refreshed on demand or via <Code>git fetch --prune</Code>.
            </dd>
            <dt>Providers &amp; models</dt>
            <dd>
              An LLM endpoint: protocol (<Code>openai</Code>,{" "}
              <Code>openai-responses</Code>, or <Code>anthropic</Code>), base URL, and an
              optional credential stored in the OS keyring — never in the database.
              Models arrive via discovery (<Code>GET /models</Code> on OpenAI-compatible
              endpoints) or manual entry.
            </dd>
            <dt>Profiles</dt>
            <dd>
              Reusable review settings: provider + model, language, concurrency, timeouts,
              planning controls, exclude patterns, rule/tools files, and expert extra
              arguments. Planning controls are validated against the detected OCR binary's
              capabilities at job creation.
            </dd>
            <dt>Queue</dt>
            <dd>
              A durable SQLite-backed queue with priorities, manual reordering, pause, and
              global / per-project / per-provider concurrency limits (all 1 by default).
            </dd>
            <dt>Review modes</dt>
            <dd>
              <Code>range</Code> compares two refs, <Code>commit</Code> reviews one
              commit, <Code>workspace</Code> reviews uncommitted changes, and{" "}
              <Code>pr</Code> reviews an open pull request head against its base.
              PRs are listed from the GitHub API when the project's remote is a GitHub
              URL (optional <Code>OCR_CC_GITHUB_TOKEN</Code> for private repos and
              higher rate limits), with a{" "}
              <Code>git ls-remote refs/pull/*/head</Code> fallback everywhere else —
              that fallback cannot see the PR base, so the form asks for a base branch.
              Base and target SHAs are captured immutably at queue time; the generated
              command is the range form.
            </dd>
            <dt>Worktree &amp; job isolation</dt>
            <dd>
              Range, commit, and pull-request reviews run in detached worktrees under{" "}
              <Code>&lt;data_dir&gt;/worktrees</Code> — your repo is never mutated.
              Workspace reviews run on the real path under a per-project exclusive lock.
              Every job gets its own HOME with its own OCR config, so concurrent jobs can
              use different providers without races.
            </dd>
          </dl>
        </Section>

        <Section id="architecture" title="Architecture">
          <P>
            One Python process runs everything: the FastAPI REST API, SSE event streams,
            the MCP server, the built React frontend, the queue worker, and the webhook
            worker. SQLite (WAL) is the only datastore; Alembic migrations run at
            startup.
          </P>
          <P>
            The only external integration points are <Code>git</Code>, the{" "}
            <Code>ocr</Code> CLI, and the OS keyring. Processes are spawned as argv
            arrays — never through a shell — and cancellation kills the whole process
            tree (POSIX process groups / Windows job objects) after a grace period.
          </P>
          <P>
            Job events are persisted and fanned out in-process; the SSE endpoint replays
            from <Code>Last-Event-ID</Code> and closes on terminal states. The full
            module map and data flow live in <Code>docs/ARCHITECTURE.md</Code> in the
            repository.
          </P>
        </Section>

        <Section id="api" title="REST API overview">
          <P>
            Base URL <Code>http://127.0.0.1:8372/api/v1</Code>. State-changing requests
            require the CSRF double-submit: echo the <Code>ocrcc_csrf</Code> cookie in
            the <Code>X-OCR-CSRF</Code> header. Errors share one envelope:{" "}
            <Code>{"{error: {code, message, detail, next_action}}"}</Code>.
          </P>
          <Table>
            <THead>
              <tr>
                <Th>Route group</Th>
                <Th>Routes</Th>
                <Th>Purpose</Th>
              </tr>
            </THead>
            <TBody>
              {API_GROUPS.map((row) => (
                <Tr key={row.group}>
                  <Td><Code>{row.group}</Code></Td>
                  <Td className={layout.small}>{row.routes}</Td>
                  <Td className={layout.small}>{row.purpose}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
          <P>
            The exhaustive request/response reference is <Code>docs/API.md</Code> in the
            repository; interactive Swagger UI is served by the backend at{" "}
            <a href="/api/docs" target="_blank" rel="noreferrer">
              /api/docs <IconExternal size={12} style={{ verticalAlign: "-1px" }} />
            </a>
            .
          </P>
        </Section>

        <Section id="mcp" title="MCP">
          <P>
            The built-in MCP server speaks Streamable HTTP at <Code>/mcp</Code> — same
            process, same port, stateless (no session affinity). Tools are thin wrappers
            over the same services as the REST API, so a job submitted by an agent
            behaves identically to one submitted from the UI.
          </P>
          <P>
            The <Link to="/mcp">MCP tab</Link> shows live server status, every tool,
            resource, and prompt, and a copy-ready client configuration. Submission is
            asynchronous: <Code>ocr_submit_review</Code> returns a durable job id; use{" "}
            <Code>ocr_get_job</Code> for status or <Code>ocr_get_job_results</Code> to
            wait for the complete export.
          </P>
        </Section>

        <Section id="webhooks" title="Webhooks">
          <P>
            Endpoints receive signed JSON callbacks when a job changes state
            (<Code>review.queued</Code>, <Code>review.started</Code>,{" "}
            <Code>review.completed</Code>, <Code>review.completed_with_warnings</Code>,{" "}
            <Code>review.failed</Code>, <Code>review.cancelled</Code>). Manage them under{" "}
            <Link to="/integrations/webhooks">Integrations → Webhooks</Link>.
          </P>
          <P>Every delivery carries these headers:</P>
          <CodeBlock
            text={
              "X-OCR-Event: review.completed\n" +
              "X-OCR-Delivery: 0192…            # == payload.id, the idempotency key\n" +
              "X-OCR-Timestamp: 1721800200      # unix seconds; reject outside ±5 min\n" +
              'X-OCR-Signature-256: sha256=…   # HMAC-SHA256(secret, timestamp + "." + raw_body)'
            }
          />
          <P>
            Delivery policy: any 2xx succeeds. 400/401/403/404/410 fail permanently;
            everything else retries on a fixed backoff of{" "}
            <Code>0s, 60s, 5m, 30m, 2h, 12h, 24h</Code> plus up to 20% jitter (a{" "}
            <Code>Retry-After</Code> header overrides the schedule for that attempt).
            Requests time out after 15 s; response bodies are read up to 64 KB and stored
            as a redacted 500-character excerpt. Replays keep the same delivery id, so
            idempotent receivers safely ignore them. Receiver-side verification examples
            (Python, Node, curl) are in <Code>docs/WEBHOOKS.md</Code>.
          </P>
        </Section>

        <Section id="exports" title="Exports">
          <P>
            Every finished job exports via{" "}
            <Code>GET /api/v1/jobs/{"{id}"}/export?format=…</Code>:
          </P>
          <Table>
            <THead>
              <tr>
                <Th>Format</Th>
                <Th>Use</Th>
              </tr>
            </THead>
            <TBody>
              {EXPORT_FORMATS.map((row) => (
                <Tr key={row.format}>
                  <Td><Code>{row.format}</Code></Td>
                  <Td className={layout.small}>{row.use}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
          <P>
            Exports never include credentials. Raw model reasoning (<Code>thinking</Code>)
            is excluded everywhere unless explicitly requested with{" "}
            <Code>include_reasoning=true</Code>.
          </P>
        </Section>

        <Section id="security" title="Security &amp; privacy">
          <ul className={layout.stack} style={{ gap: 8, margin: 0, paddingLeft: 18 }}>
            <li className={layout.small}>
              The backend binds to <Code>127.0.0.1</Code> only; CORS origins are restricted
              to the app origin.
            </li>
            <li className={layout.small}>
              Provider credentials live in the OS credential store (Windows Credential
              Manager / Keychain / Secret Service). The database only holds opaque
              references — responses carry <Code>has_credential</Code>, never material.
            </li>
            <li className={layout.small}>
              A credential redactor scrubs logs, command previews, exports, webhook
              payloads, and the diagnostics bundle. Managed jobs run with telemetry
              disabled.
            </li>
            <li className={layout.small}>
              Project and folder paths are normalized and symlink-resolved, and can be
              locked to allowlisted roots. Git refs are validated and passed after{" "}
              <Code>--end-of-options</Code>; expert extra arguments are parsed into argv
              and shell metacharacters are rejected.
            </li>
            <li className={layout.small}>
              Webhooks require HTTPS and block private-network targets unless explicitly
              enabled in Settings.
            </li>
          </ul>
        </Section>

        <Section id="troubleshooting" title="Troubleshooting">
          <P>
            Start at the <Link to="/diagnostics">Diagnostics page</Link>: versions,
            paths, worker status, storage usage, and recent sanitized errors. The{" "}
            <em>Download bundle</em> button produces a sanitized zip (system info,
            settings, recent errors, capped log excerpts) — no credentials, no source
            file content.
          </P>
          <dl className={layout.dl}>
            <dt>OCR not detected</dt>
            <dd>
              Install the engine (<Code>npm i -g @alibaba-group/open-code-review</Code>)
              or point Settings → OCR Installation at a custom executable, then use
              Re-detect. The API reports <Code>ocr_not_found</Code> until then; queued
              jobs wait safely.
            </dd>
            <dt>Blank page / strict MIME errors</dt>
            <dd>
              Some Windows machines map <Code>.js</Code> to <Code>text/plain</Code> in the
              registry, so browsers refuse to execute module scripts. The backend
              force-corrects web-critical MIME types at startup — hard-refresh the browser
              after upgrading.
            </dd>
            <dt>Connection test fails</dt>
            <dd>
              The test sends a real minimal request to the endpoint. The result panel
              shows what failed, why, and what to do next — check the base URL (with or
              without the <Code>/v1</Code> suffix), the credential, and that the selected
              model exists on the server.
            </dd>
            <dt>Webhook deliveries fail</dt>
            <dd>
              HTTPS is required by default and private-network targets are blocked — both
              can be relaxed in Settings → Security for local receivers. Check the delivery
              log for HTTP status and the redacted response excerpt.
            </dd>
          </dl>
        </Section>
      </div>
    </>
  );
}
