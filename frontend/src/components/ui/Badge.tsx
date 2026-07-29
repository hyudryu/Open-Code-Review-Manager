import type { ReactNode } from "react";
import styles from "./ui.module.css";

export type BadgeTone = "neutral" | "accent" | "success" | "warning" | "danger" | "yellow";

const TONE_CLASS: Record<BadgeTone, string> = {
  neutral: "",
  accent: styles.badgeAccent,
  success: styles.badgeSuccess,
  warning: styles.badgeWarning,
  danger: styles.badgeDanger,
  yellow: styles.badgeYellow,
};

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: BadgeTone;
  children: ReactNode;
}) {
  return <span className={`${styles.badge} ${TONE_CLASS[tone]}`}>{children}</span>;
}
