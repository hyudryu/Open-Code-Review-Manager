import { useCallback, useEffect, useRef, useState } from "react";
import { IconCheck, IconCopy } from "./icons";
import styles from "./ui.module.css";

export interface CopyButtonProps {
  text: string | (() => string);
  label?: string;
  copiedLabel?: string;
  disabled?: boolean;
  "aria-label"?: string;
}

/**
 * One-click copy with inline checkmark + "Copied" feedback for ~1.5 s.
 * Never raises a toast (SPEC §16 Clipboard Feedback).
 */
export function CopyButton({
  text,
  label,
  copiedLabel = "Copied",
  disabled,
  ...rest
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  const onCopy = useCallback(async () => {
    const value = typeof text === "function" ? text() : text;
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      // Fallback for environments without async clipboard permission.
      const area = document.createElement("textarea");
      area.value = value;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      document.body.removeChild(area);
    }
    setCopied(true);
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 1500);
  }, [text]);

  return (
    <button
      type="button"
      className={`${styles.copyButton} ${copied ? styles.copyButtonCopied : ""}`}
      onClick={onCopy}
      disabled={disabled}
      aria-label={rest["aria-label"] ?? (label ? undefined : "Copy to clipboard")}
    >
      {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
      {copied ? <span>{copiedLabel}</span> : label ? <span>{label}</span> : null}
    </button>
  );
}
