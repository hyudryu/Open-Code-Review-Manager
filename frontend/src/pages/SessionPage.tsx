/** Raw OCR session inspector (SPEC §15, §33.12) — paginated, never whole-file.
 * Search/filter are server-side (q / task_type / file query params) so the
 * full transcript is never loaded into the browser. */

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useJob, useJobSession } from "../api/hooks";
import { requestText } from "../api/client";
import { PageHeader } from "../layouts/AppLayout";
import {
  Badge,
  Button,
  CopyButton,
  EmptyState,
  ErrorState,
  Input,
  Skeleton,
  toast,
} from "../components/ui";
import { IconDownload, IconSearch } from "../components/ui/icons";
import type { SessionRecord } from "../types";
import layout from "../layouts/layout.module.css";
import styles from "./pages.module.css";

const PAGE = 200;

const TASK_TYPES = [
  "",
  "plan_task",
  "main_task",
  "review_filter_task",
  "memory_compression_task",
  "re_location_task",
];

/** Debounce a string value so typing does not fire a request per keystroke. */
function useDebounced(value: string, delayMs = 300): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

function downloadJsonl(jobId: string) {
  requestText(`/api/v1/jobs/${jobId}/export`, { format: "jsonl" })
    .then((content) => {
      const blob = new Blob([content], { type: "application/x-ndjson" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `session-${jobId.slice(0, 8)}.jsonl`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    })
    .catch((err: Error) => toast.error("Download failed", err.message));
}

function RecordRow({ record }: { record: SessionRecord }) {
  const [open, setOpen] = useState(false);
  const raw = record.raw ?? record;
  const tokens =
    (record.prompt_tokens ?? 0) + (record.completion_tokens ?? 0) || null;

  return (
    <div
      style={{
        borderBottom: "1px solid var(--border-subtle)",
        padding: "8px 0",
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          width: "100%",
          background: "none",
          border: "none",
          cursor: "pointer",
          textAlign: "left",
          padding: 0,
        }}
      >
        <span className={layout.small} style={{ width: 40, flex: "none" }}>
          #{record.seq ?? "—"}
        </span>
        <Badge tone={record.error ? "danger" : record.record_type === "llm_request" ? "accent" : "neutral"}>
          {record.record_type ?? "record"}
        </Badge>
        {record.task_type ? <Badge>{record.task_type}</Badge> : null}
        <span className={`${layout.monoPath} ${styles.ellipsize}`} style={{ fontSize: 12, flex: 1 }}>
          {record.file_path ?? record.tool_name ?? record.session_id ?? ""}
        </span>
        <span className={layout.small} style={{ flex: "none" }}>
          {tokens ? `${tokens} tok` : ""}
          {record.duration_ms != null ? ` · ${Math.round(record.duration_ms)} ms` : ""}
          {record.comments_count != null ? ` · ${record.comments_count} comments` : ""}
        </span>
      </button>
      {record.error ? (
        <p className={layout.small} style={{ color: "var(--danger)", marginTop: 4 }}>
          {record.error}
        </p>
      ) : null}
      {open ? (
        <div style={{ marginTop: 8, position: "relative" }}>
          <div style={{ position: "absolute", top: 6, right: 6 }}>
            <CopyButton text={JSON.stringify(raw, null, 2)} label="Copy JSON" />
          </div>
          <pre className={styles.codeBlock} style={{ maxHeight: 320, overflowY: "auto" }}>
            {JSON.stringify(raw, null, 2)}
          </pre>
        </div>
      ) : null}
    </div>
  );
}

export function SessionPage() {
  const { jobId = "" } = useParams();
  const job = useJob(jobId);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [fileFilter, setFileFilter] = useState("");
  const [taskFilter, setTaskFilter] = useState("");

  const debouncedQuery = useDebounced(query);
  const debouncedFile = useDebounced(fileFilter);
  const filters = {
    q: debouncedQuery.trim() || undefined,
    file: debouncedFile.trim() || undefined,
    task_type: taskFilter || undefined,
  };
  const session = useJobSession(jobId, offset, PAGE, filters);

  // Filtering changes the result set — always restart from the first page.
  const filterKey = `${filters.q ?? ""}|${filters.file ?? ""}|${filters.task_type ?? ""}`;
  const [lastFilterKey, setLastFilterKey] = useState(filterKey);
  if (filterKey !== lastFilterKey) {
    setLastFilterKey(filterKey);
    setOffset(0);
  }

  const records = session.data?.records ?? [];
  const filtersActive = Boolean(filters.q || filters.file || filters.task_type);

  const total = session.data?.total ?? 0;
  const page = Math.floor(offset / PAGE) + 1;
  const pages = Math.max(1, Math.ceil(total / PAGE));

  return (
    <>
      <PageHeader
        title="Session inspector"
        subtitle={
          session.data?.session_id
            ? `OCR session ${session.data.session_id} · ${total} records${filtersActive ? " (filtered)" : ""}`
            : "Raw OCR session records"
        }
        actions={
          <>
            <Link to={`/reviews/${jobId}`}>
              <Button variant="secondary">Back to result</Button>
            </Link>
            <Button variant="secondary" onClick={() => downloadJsonl(jobId)}>
              <IconDownload size={14} /> Download JSONL
            </Button>
          </>
        }
      />

      <div className={`${layout.stack} ${layout.stackLg}`}>
        <div className={styles.filterBar}>
          <div className={styles.filterItem} style={{ minWidth: 240 }}>
            <Input
              label="Search records (server-side)"
              type="search"
              placeholder="Text anywhere in the record…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <div className={styles.filterItem} style={{ minWidth: 200 }}>
            <Input
              label="File (path contains)"
              type="search"
              placeholder="e.g. src/app.py"
              value={fileFilter}
              onChange={(e) => setFileFilter(e.target.value)}
              aria-label="Filter by file"
            />
          </div>
          <div className={styles.filterItem}>
            <label className={layout.small} style={{ display: "block", marginBottom: 4 }}>
              Task type
            </label>
            <select
              value={taskFilter}
              onChange={(e) => setTaskFilter(e.target.value)}
              aria-label="Filter by task type"
              style={{
                height: 32,
                width: "100%",
                borderRadius: 8,
                border: "1px solid var(--border-strong)",
                background: "var(--bg-surface)",
                color: "var(--text-primary)",
                padding: "0 10px",
              }}
            >
              {TASK_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t || "All task types"}
                </option>
              ))}
            </select>
          </div>
        </div>

        {session.error ? (
          <ErrorState title="Could not load session" error={session.error} onRetry={() => session.refetch()} />
        ) : session.isLoading ? (
          <div className={layout.stack}>
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} height={36} />
            ))}
          </div>
        ) : total === 0 ? (
          <div className={layout.section}>
            <EmptyState
              icon={<IconSearch size={28} />}
              title={filtersActive ? "No records match the filters" : "No session records"}
              body={
                filtersActive
                  ? "Try a different search term, file, or task type."
                  : job.data?.ocr_session_id
                    ? "The session file could not be read or contains no records."
                    : "This job has no recorded OCR session. Session files appear after OCR runs."
              }
            />
          </div>
        ) : (
          <>
            <div className={layout.section} style={{ padding: "8px 20px" }}>
              {records.length === 0 ? (
                <p className={layout.small} style={{ padding: "12px 0" }}>
                  No records on this page.
                </p>
              ) : (
                records.map((record, i) => (
                  <RecordRow key={`${record.seq ?? i}`} record={record} />
                ))
              )}
            </div>
            <div className={layout.row} style={{ justifyContent: "space-between" }}>
              <span className={layout.small}>
                Page {page} of {pages} · {total} {filtersActive ? "matching" : ""} records (loaded in pages of {PAGE} — the full transcript is never loaded at once)
              </span>
              <div className={layout.row}>
                <Button
                  variant="secondary"
                  size="small"
                  disabled={offset === 0 || session.isFetching}
                  onClick={() => setOffset((o) => Math.max(0, o - PAGE))}
                >
                  Previous
                </Button>
                <Button
                  variant="secondary"
                  size="small"
                  disabled={offset + PAGE >= total || session.isFetching}
                  onClick={() => setOffset((o) => o + PAGE)}
                >
                  Next
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}
