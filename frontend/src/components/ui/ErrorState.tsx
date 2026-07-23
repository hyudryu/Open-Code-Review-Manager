import { ApiError } from "../../api/client";
import { Button } from "./Button";
import styles from "./ui.module.css";

/**
 * Error presentation per SPEC §29: what failed, why, what next, sanitized
 * detail — never raw stack traces.
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
  const message = apiError?.message ?? "An unexpected error occurred.";
  const detail = apiError?.detail ?? null;
  const nextAction = apiError?.nextAction ?? null;

  return (
    <div className={styles.errorState} role="alert">
      <p className={styles.errorTitle}>{title}</p>
      <p className={styles.errorBody}>{message}</p>
      {nextAction ? <p className={styles.errorNext}>{nextAction}</p> : null}
      {detail ? <pre className={styles.errorDetail}>{detail}</pre> : null}
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
