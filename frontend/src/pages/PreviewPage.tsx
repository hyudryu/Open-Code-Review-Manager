/** File preview (SPEC §7, §33.7) — POST /jobs/preview; never calls the LLM. */

import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { usePreviewJob, useProject } from "../api/hooks";
import { PageHeader } from "../layouts/AppLayout";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Skeleton,
  Table,
  TBody,
  Td,
  Th,
  THead,
  Tr,
} from "../components/ui";
import { IconChevronLeft, IconFile } from "../components/ui/icons";
import type { JobMode, JobPreview } from "../types";
import layout from "../layouts/layout.module.css";

const STATE_BADGE: Record<string, { label: string; tone: "success" | "warning" | "danger" | "neutral" | "accent" }> = {
  A: { label: "added", tone: "success" },
  M: { label: "modified", tone: "accent" },
  R: { label: "renamed", tone: "warning" },
  D: { label: "deleted", tone: "danger" },
};

export function PreviewPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const projectId = params.get("project") ?? "";
  const requestedMode = params.get("mode") ?? "range";
  const mode: JobMode = ["range", "commit", "workspace", "pr", "scan"].includes(requestedMode)
    ? requestedMode as JobMode
    : "range";
  const baseRef = params.get("base") || null;
  const targetRef = params.get("target") || null;
  const commitRef = params.get("commit") || null;
  const prNumber = params.get("pr") ? Number(params.get("pr")) : null;
  const profileId = params.get("profile") || null;
  const excludes = (params.get("excludes") ?? "").split(",").filter(Boolean);

  const project = useProject(projectId);
  const preview = usePreviewJob();
  const [result, setResult] = useState<JobPreview | null>(null);
  const [showExcluded, setShowExcluded] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    preview
      .mutateAsync({
        project_id: projectId,
        mode,
        base_ref: baseRef,
        target_ref: targetRef,
        commit_ref: commitRef,
        pr_number: prNumber,
        profile_id: profileId,
        exclude_patterns: excludes.length ? excludes : null,
      })
      .then(setResult)
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const included = useMemo(
    () => (result?.files ?? []).filter((f) => f.will_review),
    [result],
  );
  const excluded = useMemo(
    () => (result?.files ?? []).filter((f) => !f.will_review),
    [result],
  );

  const visible = showExcluded ? excluded : included;

  return (
    <>
      <PageHeader
        title="File preview"
        subtitle={
          project.data
            ? `${project.data.display_name} · ${mode === "range" ? `${baseRef ?? "?"} → ${targetRef ?? "?"}` : mode === "commit" ? commitRef : mode === "pr" ? `PR #${prNumber ?? "?"}` : mode === "scan" ? "full repository" : "working tree"}`
            : "Files OCR will review — no LLM calls are made for a preview."
        }
        actions={
          <Button variant="secondary" onClick={() => navigate(-1)}>
            <IconChevronLeft size={14} /> Back to review form
          </Button>
        }
      />

      {preview.isPending ? (
        <div className={layout.stack}>
          <Skeleton height={28} width={280} />
          <Skeleton height={320} />
          <p className={layout.small}>Running OCR preview (no model calls)…</p>
        </div>
      ) : preview.error ? (
        <ErrorState title="Preview failed" error={preview.error} onRetry={() => window.location.reload()} />
      ) : result ? (
        <div className={`${layout.stack} ${layout.stackLg}`}>
          <div className={layout.row} style={{ gap: 24 }}>
            <span><strong>{result.reviewable_count ?? included.length}</strong> <span className={layout.small}>files will be reviewed</span></span>
            <span><strong>{result.excluded_count ?? excluded.length}</strong> <span className={layout.small}>excluded</span></span>
            {result.total_insertions != null ? (
              <span style={{ color: "var(--success)" }}>+{result.total_insertions}</span>
            ) : null}
            {result.total_deletions != null ? (
              <span style={{ color: "var(--danger)" }}>−{result.total_deletions}</span>
            ) : null}
            <span style={{ marginLeft: "auto" }}>
              <Button variant="secondary" size="small" onClick={() => setShowExcluded((v) => !v)}>
                {showExcluded ? `Show included (${included.length})` : `Show excluded (${excluded.length})`}
              </Button>
            </span>
          </div>

          {visible.length === 0 ? (
            <div className={layout.section}>
              <EmptyState
                icon={<IconFile size={28} />}
                title={showExcluded ? "No excluded files" : "Nothing to review"}
                body={
                  showExcluded
                    ? "Every changed file will be reviewed."
                    : "The selected range contains no reviewable changes. Check the refs or your exclude patterns."
                }
              />
            </div>
          ) : (
            <Table>
              <THead>
                <tr>
                  <Th>File</Th>
                  <Th style={{ width: 100 }}>State</Th>
                  <Th style={{ width: 120 }}>Changes</Th>
                  {showExcluded ? <Th style={{ width: 260 }}>Reason</Th> : null}
                </tr>
              </THead>
              <TBody>
                {visible.map((file) => {
                  const state = STATE_BADGE[file.status ?? ""] ?? {
                    label: file.status ?? "changed",
                    tone: "neutral" as const,
                  };
                  return (
                    <Tr key={file.path}>
                      <Td>
                        <span className={layout.monoPath} style={{ fontSize: 12.5 }}>
                          {file.path}
                        </span>
                      </Td>
                      <Td>
                        <Badge tone={state.tone}>{state.label}</Badge>
                      </Td>
                      <Td className={layout.small}>
                        {file.insertions != null || file.deletions != null ? (
                          <>
                            <span style={{ color: "var(--success)" }}>+{file.insertions ?? 0}</span>{" "}
                            <span style={{ color: "var(--danger)" }}>−{file.deletions ?? 0}</span>
                          </>
                        ) : (
                          "—"
                        )}
                      </Td>
                      {showExcluded ? (
                        <Td className={layout.small}>{file.exclude_reason ?? "excluded"}</Td>
                      ) : null}
                    </Tr>
                  );
                })}
              </TBody>
            </Table>
          )}

          <p className={layout.small}>
            Preview is computed locally from the diff — the LLM is never called.{" "}
            <Link to={`/reviews/new?project=${projectId}`}>Return to the review form</Link> to queue it.
          </p>
        </div>
      ) : null}
    </>
  );
}
