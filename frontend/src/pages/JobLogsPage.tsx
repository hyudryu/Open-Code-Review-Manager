/** Job logs viewer (stdout/stderr) — persisted OCR process output. */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useJob, useJobLogs } from "../api/hooks";
import { PageHeader } from "../layouts/AppLayout";
import {
  Badge,
  Button,
  CopyButton,
  EmptyState,
  ErrorState,
  Skeleton,
  toast,
} from "../components/ui";
import { IconDownload } from "../components/ui/icons";
import { requestText } from "../api/client";
import { relativeTime } from "../lib/format";
import layout from "../layouts/layout.module.css";
import styles from "./pages.module.css";

function downloadLog(jobId: string, stream: "stdout" | "stderr") {
  requestText(`/api/v1/jobs/${jobId}/logs`, { stream, tail_bytes: 1_000_000 })
    .then((content) => {
      const blob = new Blob([content], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `job-${jobId.slice(0, 8)}-${stream}.log`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    })
    .catch((err: Error) => toast.error("Download failed", err.message));
}

export function JobLogsPage() {
  const { jobId = "" } = useParams();
  const job = useJob(jobId);
  const [stream, setStream] = useState<"stdout" | "stderr">("stdout");
  const logs = useJobLogs(jobId, stream);

  return (
    <>
      <PageHeader
        title="Job logs"
        subtitle={
          job.data
            ? `OCR process output · queued ${relativeTime(job.data.queued_at)}`
            : "OCR process output"
        }
        actions={
          <>
            <Link to={`/reviews/${jobId}`}>
              <Button variant="secondary">Back to result</Button>
            </Link>
            <Button variant="secondary" onClick={() => downloadLog(jobId, stream)}>
              <IconDownload size={14} /> Download
            </Button>
          </>
        }
      />

      {job.isLoading ? (
        <Skeleton height={400} />
      ) : job.error ? (
        <ErrorState title="Could not load job" error={job.error} onRetry={() => job.refetch()} />
      ) : (
        <div className={`${layout.stack} ${layout.stackLg}`}>
          <div className={layout.row} style={{ gap: 8 }}>
            <Button
              variant={stream === "stdout" ? "primary" : "secondary"}
              size="small"
              onClick={() => setStream("stdout")}
            >
              stdout
            </Button>
            <Button
              variant={stream === "stderr" ? "primary" : "secondary"}
              size="small"
              onClick={() => setStream("stderr")}
            >
              stderr
            </Button>
            <span className={layout.small} style={{ marginLeft: "auto" }}>
              {logs.data ? (
                <>
                  {logs.data.size.toLocaleString()} bytes
                  {logs.data.truncated ? (
                    <Badge tone="warning" >truncated to last 128 KB</Badge>
                  ) : null}
                </>
              ) : null}
            </span>
          </div>

          {logs.error ? (
            <ErrorState
              title="Could not load logs"
              error={logs.error}
              onRetry={() => logs.refetch()}
            />
          ) : logs.isLoading ? (
            <Skeleton height={420} />
          ) : !logs.data?.text ? (
            <div className={layout.section}>
              <EmptyState
                title={`No ${stream} output`}
                body={
                  stream === "stderr"
                    ? "OCR reported no warnings or errors on this stream."
                    : "OCR has not produced output on this stream yet. The job may still be queued or starting."
                }
              />
            </div>
          ) : (
            <div style={{ position: "relative" }}>
              <div style={{ position: "absolute", top: 8, right: 8, zIndex: 1 }}>
                <CopyButton text={logs.data.text} label="Copy log" />
              </div>
              <pre className={`${styles.logTail}`} style={{ height: 480 }}>
                {logs.data.text}
              </pre>
            </div>
          )}
        </div>
      )}
    </>
  );
}
