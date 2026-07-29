/** Finding card (SPEC §15) — copy actions, user-state triage, note. */

import { useMemo, useState } from "react";
import type { Finding, FindingState } from "../../types";
import { useFindingReasoning, useUpdateFinding } from "../../api/hooks";
import { Badge, Button, CopyButton } from "../../components/ui";
import { toast } from "../../components/ui";
import layout from "../../layouts/layout.module.css";
import styles from "../../pages/pages.module.css";

export const FINDING_STATE_LABEL: Record<FindingState, string> = {
  unreviewed: "Unreviewed",
  accepted: "Accepted",
  dismissed: "Dismissed",
  needs_followup: "Follow-up",
};

export const FINDING_STATE_TONE: Record<FindingState, "neutral" | "success" | "warning" | "accent"> = {
  unreviewed: "neutral",
  accepted: "success",
  dismissed: "neutral",
  needs_followup: "warning",
};

const SEVERITY_TONE: Record<string, "danger" | "warning" | "yellow"> = {
  high: "danger",
  medium: "warning",
  low: "yellow",
};

function severityTone(severity: string | null): "danger" | "warning" | "yellow" {
  return SEVERITY_TONE[severity ?? ""] ?? "neutral";
}

export function FindingCard({ finding }: { finding: Finding }) {
  const update = useUpdateFinding();
  const [noteOpen, setNoteOpen] = useState(Boolean(finding.user_note));
  const [note, setNote] = useState(finding.user_note ?? "");
  const [reasoningOpen, setReasoningOpen] = useState(false);
  // Reasoning is fetched on demand, only while the disclosure is open.
  const reasoning = useFindingReasoning(finding.job_id, finding.id, reasoningOpen);

  function setState(user_state: FindingState) {
    update.mutate(
      { jobId: finding.job_id, findingId: finding.id, user_state },
      {
        onError: (err) =>
          toast.error("Could not update finding", err.message),
      },
    );
  }

  const lineRef =
    finding.start_line != null
      ? `${finding.path}:${finding.start_line}${finding.end_line && finding.end_line !== finding.start_line ? `-${finding.end_line}` : ""}`
      : finding.path;

  /** Build the full clipboard text: location → content → code blocks */
  const copyText = useMemo(() => {
    const parts = [`[${lineRef}]`, ""];
    parts.push(finding.content);
    if (finding.existing_code) {
      parts.push("");
      parts.push("---");
      parts.push(finding.existing_code);
    }
    if (finding.suggestion_code) {
      parts.push("");
      parts.push("---");
      parts.push(finding.suggestion_code);
    }
    return parts.join("\n");
  }, [finding.content, finding.existing_code, finding.suggestion_code, lineRef]);

  return (
    <article className={styles.findingCard} aria-label={`Finding in ${finding.path}`}>
      <div className={styles.findingHeader}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <code className={layout.monoPath} style={{ fontSize: 12.5 }}>{lineRef}</code>
            {finding.category ? <Badge>{finding.category}</Badge> : null}
            {finding.severity ? (
              <Badge tone={severityTone(finding.severity)}>
                {finding.severity.toUpperCase()}
              </Badge>
            ) : null}
            <Badge tone={FINDING_STATE_TONE[finding.user_state]}>
              {FINDING_STATE_LABEL[finding.user_state]}
            </Badge>
          </div>
        </div>
        <div style={{ display: "flex", gap: 2, flex: "none" }}>
          <CopyButton text={copyText} label="Copy finding" />
        </div>
      </div>

      <p className={styles.findingText}>{finding.content}</p>

      {finding.existing_code ? (
        <div>
          <div className={styles.codeBlockLabel}>
            <span>Existing code</span>
            <CopyButton text={finding.existing_code} label="Copy" />
          </div>
          <pre className={styles.codeBlock}>{finding.existing_code}</pre>
        </div>
      ) : null}

      {finding.suggestion_code ? (
        <div>
          <div className={styles.codeBlockLabel}>
            <span>Suggested replacement</span>
            <CopyButton text={finding.suggestion_code} label="Copy" />
          </div>
          <pre className={styles.codeBlock}>{finding.suggestion_code}</pre>
        </div>
      ) : null}

      {/* Reasoning stays behind an explicit disclosure control (SPEC §15). */}
      <div>
        <button
          type="button"
          className={layout.small}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            padding: 0,
            color: "var(--text-secondary)",
            textDecoration: "underline",
          }}
          onClick={() => setReasoningOpen((v) => !v)}
          aria-expanded={reasoningOpen}
        >
          {reasoningOpen ? "Hide reasoning" : "Show reasoning"}
        </button>
        {reasoningOpen ? (
          <div style={{ marginTop: 6 }}>
            {reasoning.isLoading ? (
              <p className={layout.small} style={{ fontStyle: "italic" }}>
                Loading reasoning…
              </p>
            ) : reasoning.error ? (
              <p className={layout.small} style={{ color: "var(--danger)" }}>
                Could not load reasoning: {reasoning.error.message}
              </p>
            ) : reasoning.data?.thinking ? (
              <pre
                className={styles.codeBlock}
                style={{ maxHeight: 240, overflowY: "auto", fontSize: 12 }}
              >
                {reasoning.data.thinking}
              </pre>
            ) : (
              <p className={layout.small} style={{ fontStyle: "italic" }}>
                No reasoning was recorded for this finding.
              </p>
            )}
          </div>
        ) : null}
      </div>

      {noteOpen ? (
        <div className={layout.stack} style={{ gap: 6 }}>
          <textarea
            aria-label="Finding note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            placeholder="Add a note for your future self or your team…"
            style={{
              width: "100%",
              borderRadius: 6,
              border: "1px solid var(--border-strong)",
              background: "var(--bg-surface)",
              color: "var(--text-primary)",
              padding: "8px 12px",
              font: "var(--text-body)",
              fontSize: 13,
              resize: "vertical",
            }}
          />
          <div className={layout.row}>
            <Button
              variant="secondary"
              size="small"
              disabled={update.isPending}
              onClick={() =>
                update.mutate(
                  { jobId: finding.job_id, findingId: finding.id, user_note: note || null },
                  {
                    onSuccess: () => toast.success("Note saved"),
                    onError: (err) => toast.error("Could not save note", err.message),
                  },
                )
              }
            >
              Save note
            </Button>
            <Button variant="tertiary" size="small" onClick={() => setNoteOpen(false)}>
              Close
            </Button>
          </div>
        </div>
      ) : null}

      <div className={layout.row} style={{ borderTop: "1px solid var(--border-subtle)", paddingTop: 12 }}>
        <Button
          variant={finding.user_state === "accepted" ? "primary" : "secondary"}
          size="small"
          onClick={() => setState("accepted")}
          disabled={update.isPending}
        >
          Accept
        </Button>
        <Button
          variant={finding.user_state === "dismissed" ? "primary" : "secondary"}
          size="small"
          onClick={() => setState("dismissed")}
          disabled={update.isPending}
        >
          Dismiss
        </Button>
        <Button
          variant={finding.user_state === "needs_followup" ? "primary" : "secondary"}
          size="small"
          onClick={() => setState("needs_followup")}
          disabled={update.isPending}
        >
          Needs follow-up
        </Button>
        <Button variant="tertiary" size="small" onClick={() => setNoteOpen((v) => !v)}>
          {finding.user_note ? "Edit note" : "Add note"}
        </Button>
      </div>
    </article>
  );
}
