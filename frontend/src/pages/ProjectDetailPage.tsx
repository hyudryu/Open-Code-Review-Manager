/** Project detail (SPEC §5) — all fields and actions, grouped branch lists. */

import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  useBranches,
  useDeleteProject,
  useProject,
  useProjectJobs,
  useRefreshBranches,
  useUpdateProject,
} from "../api/hooks";
import { PageHeader } from "../layouts/AppLayout";
import {
  Badge,
  Button,
  ConfirmDialog,
  CopyButton,
  EmptyState,
  ErrorState,
  Input,
  Menu,
  Modal,
  Skeleton,
  StatusDot,
  toast,
} from "../components/ui";
import {
  IconBranch,
  IconCloud,
  IconMore,
  IconPlay,
  IconRefresh,
  IconTag,
} from "../components/ui/icons";
import { formatDateTime, relativeTime, shortSha } from "../lib/format";
import { jobTargetLabel, STATUS_LABEL, STATUS_TONE } from "../lib/status";
import type { Branch } from "../types";
import layout from "../layouts/layout.module.css";
import styles from "./pages.module.css";

function BranchList({ branches, title, icon }: { branches: Branch[]; title: string; icon: React.ReactNode }) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return branches;
    return branches.filter(
      (b) =>
        b.name.toLowerCase().includes(q) ||
        (b.commit_subject ?? "").toLowerCase().includes(q),
    );
  }, [branches, query]);

  return (
    <section className={`${layout.section} ${layout.sectionTight}`} aria-label={title}>
      <div className={layout.sectionHeader}>
        <h2 className={layout.sectionTitle} style={{ margin: 0, display: "flex", gap: 6, alignItems: "center" }}>
          {icon}
          {title}
          <span className={layout.small}>({branches.length})</span>
        </h2>
        <input
          type="search"
          placeholder={`Search ${title.toLowerCase()}…`}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label={`Search ${title}`}
          style={{
            height: 28,
            width: 200,
            borderRadius: 6,
            border: "1px solid var(--border-strong)",
            background: "var(--bg-surface)",
            color: "var(--text-primary)",
            padding: "0 10px",
            font: "var(--text-body)",
            fontSize: 12.5,
          }}
        />
      </div>
      {filtered.length === 0 ? (
        <p className={layout.small}>
          {branches.length === 0 ? "None cached — refresh branches." : "No matches."}
        </p>
      ) : (
        <ul style={{ maxHeight: 280, overflowY: "auto" }}>
          {filtered.map((branch) => (
            <li key={branch.id} className={styles.compactRow} style={{ gap: 8 }}>
              <div className={styles.compactRowMain}>
                <span className={`${styles.compactRowTitle} ${layout.monoPath}`} style={{ fontSize: 12.5 }}>
                  {branch.name}
                  {branch.is_current ? (
                    <> <Badge tone="accent">current</Badge></>
                  ) : null}
                  {branch.is_default ? <> <Badge>default</Badge></> : null}
                </span>
                <span className={styles.compactRowMeta}>
                  {shortSha(branch.commit_sha)} · {branch.commit_subject ?? "—"} ·{" "}
                  {relativeTime(branch.commit_timestamp)}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function ProjectDetailPage() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const project = useProject(projectId);
  const branches = useBranches(projectId);
  const jobs = useProjectJobs(projectId);
  const refresh = useRefreshBranches();
  const update = useUpdateProject();
  const remove = useDeleteProject();

  const [removeOpen, setRemoveOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editName, setEditName] = useState("");
  const [editError, setEditError] = useState<unknown>(null);

  const grouped = useMemo(() => {
    const all = branches.data ?? [];
    return {
      local: all.filter((b) => b.kind === "local"),
      remote: all.filter((b) => b.kind === "remote"),
      tags: all.filter((b) => b.kind === "tag"),
    };
  }, [branches.data]);

  if (project.isLoading) {
    return (
      <div className={layout.stack}>
        <Skeleton height={36} width={320} />
        <Skeleton height={160} />
        <Skeleton height={200} />
      </div>
    );
  }

  if (project.error || !project.data) {
    return (
      <ErrorState
        title="Could not load project"
        error={project.error}
        onRetry={() => project.refetch()}
      />
    );
  }

  const p = project.data;

  async function doRefresh(fetch: boolean) {
    try {
      const result = await refresh.mutateAsync({ projectId, fetch });
      if (result.fetch_error) {
        toast.error("Fetch failed — kept existing branch cache", result.fetch_error);
      } else {
        toast.success(fetch ? "Fetched and refreshed branches" : "Branches refreshed");
      }
    } catch (err) {
      toast.error("Branch refresh failed", err instanceof Error ? err.message : undefined);
    }
  }

  return (
    <>
      <PageHeader
        title={
          <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
            {p.display_name}
            <StatusDot
              tone={!p.is_available ? "danger" : p.is_dirty ? "warn" : "ok"}
              label={!p.is_available ? "Unavailable" : p.is_dirty ? "Dirty" : "Clean"}
            />
          </span>
        }
        subtitle={<span className={layout.monoPath} style={{ fontSize: 12.5 }}>{p.absolute_path}</span>}
        actions={
          <>
            <Button variant="primary" onClick={() => navigate(`/reviews/new?project=${p.id}`)}>
              <IconPlay size={14} /> Start review
            </Button>
            <Button
              variant="secondary"
              onClick={() => doRefresh(false)}
              disabled={refresh.isPending}
            >
              <IconRefresh size={14} /> Refresh branches
            </Button>
            <Menu
              ariaLabel="More project actions"
              trigger={
                <Button variant="secondary" aria-label="More actions">
                  <IconMore size={16} />
                </Button>
              }
              items={[
                {
                  key: "fetch",
                  label: "Fetch remote + prune",
                  icon: <IconCloud size={14} />,
                  onSelect: () => doRefresh(true),
                },
                {
                  key: "copy",
                  label: "Copy path",
                  onSelect: () => void navigator.clipboard.writeText(p.absolute_path),
                },
                {
                  key: "edit",
                  label: "Edit project",
                  onSelect: () => {
                    setEditName(p.display_name);
                    setEditOpen(true);
                  },
                },
                { key: "sep", label: "", type: "separator" },
                {
                  key: "remove",
                  label: "Remove project",
                  danger: true,
                  onSelect: () => setRemoveOpen(true),
                },
              ]}
            />
          </>
        }
      />

      <div className={`${layout.stack} ${layout.stackLg}`}>
        <section className={`${layout.section} ${layout.sectionTight}`} aria-label="Project details">
          <dl className={layout.dl}>
            <dt>Remote</dt>
            <dd>
              {p.remote_url ? (
                <span className={layout.monoPath} style={{ fontSize: 12.5 }}>
                  {p.remote_name ?? "origin"} · {p.remote_url}
                </span>
              ) : (
                <span className={layout.muted}>No remote configured</span>
              )}
            </dd>
            <dt>Current branch</dt>
            <dd className={layout.monoPath} style={{ fontSize: 12.5 }}>
              {p.current_branch ?? "— (detached HEAD)"}
            </dd>
            <dt>Default branch</dt>
            <dd className={layout.monoPath} style={{ fontSize: 12.5 }}>{p.default_branch ?? "—"}</dd>
            <dt>Last branch refresh</dt>
            <dd>{formatDateTime(p.last_branch_refresh_at)}</dd>
            <dt>Path</dt>
            <dd style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className={layout.monoPath} style={{ fontSize: 12.5 }}>{p.absolute_path}</span>
              <CopyButton text={p.absolute_path} aria-label="Copy project path" />
            </dd>
          </dl>
        </section>

        <div className={layout.grid2} style={{ gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
          <BranchList branches={grouped.local} title="Local branches" icon={<IconBranch size={14} />} />
          <BranchList branches={grouped.remote} title="Remote branches" icon={<IconCloud size={14} />} />
          <BranchList branches={grouped.tags} title="Tags" icon={<IconTag size={14} />} />
        </div>

        <section aria-label="Review history">
          <div className={layout.sectionHeader}>
            <h2 className={layout.sectionTitle} style={{ margin: 0 }}>Recent reviews</h2>
            <Link to={`/reviews?project=${p.id}`} className={layout.small}>View history</Link>
          </div>
          <div className={`${layout.section} ${layout.sectionTight}`}>
            {(jobs.data ?? []).length === 0 ? (
              <EmptyState
                title="No reviews yet"
                body="Start a review to compare branches, inspect a commit, or check your working tree."
                action={
                  <Button variant="primary" size="small" onClick={() => navigate(`/reviews/new?project=${p.id}`)}>
                    Start review
                  </Button>
                }
              />
            ) : (
              (jobs.data ?? []).slice(0, 8).map((job) => (
                <div key={job.id} className={styles.compactRow}>
                  <div className={styles.compactRowMain}>
                    <Link
                      to={job.status === "running" || job.status === "preparing" || job.status === "queued" ? `/jobs/${job.id}` : `/reviews/${job.id}`}
                      className={styles.compactRowTitle}
                    >
                      {jobTargetLabel(job)}
                    </Link>
                    <span className={styles.compactRowMeta}>
                      {job.findings_count} findings · {relativeTime(job.queued_at)} · via {job.source}
                    </span>
                  </div>
                  <StatusDot tone={STATUS_TONE[job.status]} label={STATUS_LABEL[job.status]} />
                </div>
              ))
            )}
          </div>
        </section>
      </div>

      <Modal
        open={editOpen}
        onOpenChange={setEditOpen}
        title="Edit project"
        footer={
          <>
            <Button variant="secondary" onClick={() => setEditOpen(false)}>Cancel</Button>
            <Button
              variant="primary"
              disabled={update.isPending || !editName.trim()}
              onClick={async () => {
                setEditError(null);
                try {
                  await update.mutateAsync({ id: projectId, display_name: editName.trim() });
                  setEditOpen(false);
                  toast.success("Project updated");
                } catch (err) {
                  setEditError(err);
                }
              }}
            >
              Save
            </Button>
          </>
        }
      >
        <div className={layout.stack}>
          <Input
            label="Display name"
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            required
          />
          {editError ? <ErrorState title="Could not save" error={editError} /> : null}
        </div>
      </Modal>

      <ConfirmDialog
        open={removeOpen}
        onOpenChange={setRemoveOpen}
        title="Remove project"
        description={`Remove "${p.display_name}" from the control center? The Git repository at ${p.absolute_path} is never deleted or modified.`}
        confirmLabel="Remove project"
        destructive
        busy={remove.isPending}
        onConfirm={async () => {
          try {
            await remove.mutateAsync(projectId);
            toast.success("Project removed — repository left untouched");
            navigate("/projects");
          } catch (err) {
            toast.error("Could not remove project", err instanceof Error ? err.message : undefined);
          }
        }}
      />
    </>
  );
}
