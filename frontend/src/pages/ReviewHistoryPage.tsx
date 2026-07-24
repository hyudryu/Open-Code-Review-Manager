/** Review history (SPEC §20 Reviews) — searchable, filtered, paginated. */

import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useJobs, useProjects, useProviders } from "../api/hooks";
import { useUiStore } from "../hooks/store";
import { PageHeader } from "../layouts/AppLayout";
import {
  Button,
  EmptyState,
  ErrorState,
  Input,
  Select,
  Skeleton,
  StatusDot,
  Table,
  TBody,
  Td,
  Th,
  THead,
  Tr,
} from "../components/ui";
import { IconReviews } from "../components/ui/icons";
import { relativeTime } from "../lib/format";
import { jobTargetLabel, MODE_LABEL, STATUS_LABEL, STATUS_TONE } from "../lib/status";
import { TERMINAL_STATUSES, type Job } from "../types";
import layout from "../layouts/layout.module.css";
import styles from "./pages.module.css";

const PAGE_SIZE = 25;

const STATUS_OPTIONS = [
  "",
  "queued",
  "preparing",
  "running",
  "completed",
  "completed_with_warnings",
  "failed",
  "cancelled",
  "interrupted",
];

export function ReviewHistoryPage() {
  const [params] = useSearchParams();
  const { historyFilters, setHistoryFilters } = useUiStore();
  const [offset, setOffset] = useState(0);
  const projects = useProjects();
  const providers = useProviders();

  // Deep link: /reviews?project=<id>
  useEffect(() => {
    const projectParam = params.get("project");
    if (projectParam && projectParam !== historyFilters.project_id) {
      setHistoryFilters({ project_id: projectParam });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  useEffect(() => {
    setOffset(0);
  }, [historyFilters]);

  const jobs = useJobs({
    status: historyFilters.status || undefined,
    project_id: historyFilters.project_id || undefined,
    source: historyFilters.source || undefined,
    provider_id: historyFilters.provider_id || undefined,
    limit: PAGE_SIZE * 4, // fetch a window; client-side refinements below
    offset: 0,
  });

  const filtered = useMemo(() => {
    let items: Job[] = (jobs.data?.items ?? []).slice();
    const q = historyFilters.search.trim().toLowerCase();
    if (q) {
      items = items.filter((j) => {
        const project = projects.data?.find((p) => p.id === j.project_id);
        return (
          project?.display_name.toLowerCase().includes(q) ||
          (j.base_ref ?? "").toLowerCase().includes(q) ||
          (j.target_ref ?? "").toLowerCase().includes(q) ||
          (j.commit_ref ?? "").toLowerCase().includes(q)
        );
      });
    }
    if (historyFilters.mode) items = items.filter((j) => j.mode === historyFilters.mode);
    if (historyFilters.has_findings) items = items.filter((j) => j.findings_count > 0);
    if (historyFilters.has_warnings)
      items = items.filter(
        (j) => (j.warnings_json?.length ?? 0) > 0 || j.status === "completed_with_warnings",
      );
    return items;
  }, [jobs.data, historyFilters, projects.data]);

  const pageItems = filtered.slice(offset, offset + PAGE_SIZE);
  const projectName = (id: string) =>
    projects.data?.find((p) => p.id === id)?.display_name ?? "Unknown project";

  return (
    <>
      <PageHeader
        title="Reviews"
        subtitle="Full review history — every job the control plane has run."
      />

      <div className={styles.filterBar} role="search" aria-label="Review filters">
        <div className={styles.filterItem} style={{ minWidth: 220 }}>
          <Input
            label="Search"
            type="search"
            placeholder="Project or ref…"
            value={historyFilters.search}
            onChange={(e) => setHistoryFilters({ search: e.target.value })}
          />
        </div>
        <div className={styles.filterItem}>
          <Select
            label="Status"
            value={historyFilters.status}
            onChange={(e) => setHistoryFilters({ status: e.target.value })}
          >
            <option value="">All statuses</option>
            {STATUS_OPTIONS.filter(Boolean).map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s as keyof typeof STATUS_LABEL]}
              </option>
            ))}
          </Select>
        </div>
        <div className={styles.filterItem}>
          <Select
            label="Project"
            value={historyFilters.project_id}
            onChange={(e) => setHistoryFilters({ project_id: e.target.value })}
          >
            <option value="">All projects</option>
            {(projects.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.display_name}
              </option>
            ))}
          </Select>
        </div>
        <div className={styles.filterItem}>
          <Select
            label="Provider"
            value={historyFilters.provider_id}
            onChange={(e) => setHistoryFilters({ provider_id: e.target.value })}
          >
            <option value="">All providers</option>
            {(providers.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </div>
        <div className={styles.filterItem}>
          <Select
            label="Mode"
            value={historyFilters.mode}
            onChange={(e) => setHistoryFilters({ mode: e.target.value })}
          >
            <option value="">All modes</option>
            <option value="range">Range</option>
            <option value="commit">Commit</option>
            <option value="workspace">Workspace</option>
          </Select>
        </div>
        <div className={styles.filterItem}>
          <Select
            label="Source"
            value={historyFilters.source}
            onChange={(e) => setHistoryFilters({ source: e.target.value })}
          >
            <option value="">All sources</option>
            <option value="web">Web</option>
            <option value="mcp">MCP</option>
            <option value="api">API</option>
            <option value="retry">Retry</option>
          </Select>
        </div>
        <div className={styles.filterItem} style={{ display: "flex", gap: 16, paddingBottom: 6 }}>
          <label className={layout.small} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <input
              type="checkbox"
              checked={historyFilters.has_findings}
              onChange={(e) => setHistoryFilters({ has_findings: e.target.checked })}
            />
            Has findings
          </label>
          <label className={layout.small} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <input
              type="checkbox"
              checked={historyFilters.has_warnings}
              onChange={(e) => setHistoryFilters({ has_warnings: e.target.checked })}
            />
            Has warnings
          </label>
        </div>
      </div>

      {jobs.error ? (
        <ErrorState title="Could not load reviews" error={jobs.error} onRetry={() => jobs.refetch()} />
      ) : jobs.isLoading ? (
        <div className={layout.stack}>
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} height={40} />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className={layout.section}>
          <EmptyState
            icon={<IconReviews size={28} />}
            title="No reviews match"
            body={
              (jobs.data?.items ?? []).length === 0
                ? "Queue your first review from a project page."
                : "Adjust the filters to see more results."
            }
            action={
              (jobs.data?.items ?? []).length === 0 ? (
                <Link to="/reviews/new">
                  <Button variant="primary" size="small">New review</Button>
                </Link>
              ) : undefined
            }
          />
        </div>
      ) : (
        <>
          <Table>
            <THead>
              <tr>
                <Th>Review</Th>
                <Th>Project</Th>
                <Th>Mode</Th>
                <Th>Findings</Th>
                <Th>Source</Th>
                <Th>Queued</Th>
                <Th>Status</Th>
              </tr>
            </THead>
            <TBody>
              {pageItems.map((job) => (
                <Tr key={job.id}>
                  <Td>
                    <Link
                      to={TERMINAL_STATUSES.includes(job.status) ? `/reviews/${job.id}` : `/jobs/${job.id}`}
                      style={{ color: "var(--text-primary)" }}
                    >
                      {jobTargetLabel(job)}
                    </Link>
                  </Td>
                  <Td>{projectName(job.project_id)}</Td>
                  <Td className={layout.small}>{MODE_LABEL[job.mode]}</Td>
                  <Td>{job.findings_count}</Td>
                  <Td className={layout.small}>{job.source}</Td>
                  <Td className={layout.small}>{relativeTime(job.queued_at)}</Td>
                  <Td>
                    <StatusDot tone={STATUS_TONE[job.status]} label={STATUS_LABEL[job.status]} />
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
          <div className={layout.row} style={{ justifyContent: "space-between", marginTop: 12 }}>
            <span className={layout.small}>
              {offset + 1}–{Math.min(offset + PAGE_SIZE, filtered.length)} of {filtered.length}
              {jobs.data && jobs.data.total > (jobs.data.items.length || 0)
                ? ` (${jobs.data.total} total on server)`
                : ""}
            </span>
            <div className={layout.row}>
              <Button
                variant="secondary"
                size="small"
                disabled={offset === 0}
                onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                size="small"
                disabled={offset + PAGE_SIZE >= filtered.length}
                onClick={() => setOffset((o) => o + PAGE_SIZE)}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      )}
    </>
  );
}
