import styles from "./ui.module.css";

export type StatusTone = "ok" | "warn" | "danger" | "accent" | "muted";

const DOT_CLASS: Record<StatusTone, string> = {
  ok: styles.dotOk,
  warn: styles.dotWarn,
  danger: styles.dotDanger,
  accent: styles.dotAccent,
  muted: styles.dotMuted,
};

export interface StatusDotProps {
  tone: StatusTone;
  label: string;
  pulse?: boolean;
  title?: string;
}

/** Small dot + text — never color alone (SPEC §23). */
export function StatusDot({ tone, label, pulse, title }: StatusDotProps) {
  return (
    <span className={styles.statusDot} title={title}>
      <span
        className={`${styles.dot} ${DOT_CLASS[tone]} ${pulse ? styles.dotPulse : ""}`}
        aria-hidden="true"
      />
      <span>{label}</span>
    </span>
  );
}
