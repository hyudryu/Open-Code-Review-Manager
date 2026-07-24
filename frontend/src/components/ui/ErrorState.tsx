import { ApiError } from "../../api/client";
import { formatApiErrorDetail } from "../../api/errors";
import { Button } from "./Button";
import styles from "./ui.module.css";

/**
 * Error presentation per SPEC §29: what failed, why, what next, sanitized
 * detail — never raw stack traces.
 *
 * The 422 envelope carries `detail` as a LIST of `{loc, msg}` objects, so the
 * detail is ALWAYS passed through `formatApiErrorDetail` — rendering the raw
 * value as a React child would throw and unmount the whole page.
 */
export function ErrorState({
  title = "Something went wrong",
  error,
  onRetry,
}: {
  title?: string;
  error: unknown;
  onRetry?: () => void;
}) {
  const apiError = error instanceof ApiError ? error : null;
  const message =
    apiError?.body?.message ??
    (error instanceof Error ? error.message : null) ??
    (error && typeof error === "object" && "message" in error
      ? String((error as { message: unknown }).message)
      : null) ??
    "An unexpected error occurred.";
  const nextAction = apiError?.nextAction ?? null;
  const rawDetail = apiError?.body?.detail;
  const detailText =
    rawDetail === null || rawDetail === undefined || rawDetail === ""
      ? null
      : formatApiErrorDetail(rawDetail);

  return (
    <div className={styles.errorState} role="alert">
      <p className={styles.errorTitle}>{title}</p>
      <p className={styles.errorBody}>{message}</p>
      {nextAction ? <p className={styles.errorNext}>{nextAction}</p> : null}
      {detailText ? <pre className={styles.errorDetail}>{detailText}</pre> : null}
      {onRetry ? (
        <div>
          <Button variant="secondary" size="small" onClick={onRetry}>
            Retry
          </Button>
        </div>
      ) : null}
    </div>
  );
}
