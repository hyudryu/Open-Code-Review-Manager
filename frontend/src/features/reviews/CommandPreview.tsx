/** Collapsible generated-command preview (SPEC §36). */

import { useState } from "react";
import { CopyButton } from "../../components/ui";
import { IconChevronDown, IconChevronRight } from "../../components/ui/icons";
import type { CommandPreview as Preview } from "../../lib/command";
import styles from "./reviews.module.css";

export function CommandPreviewView({
  preview,
  title = "Generated command",
  defaultOpen = false,
}: {
  preview: Preview;
  title?: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const argvText = preview.argv.join("\n");

  return (
    <div className={styles.commandPreview}>
      <button
        type="button"
        className={styles.commandHeader}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          {open ? <IconChevronDown size={13} /> : <IconChevronRight size={13} />}
          {title}
        </span>
        <CopyButton text={argvText} label="Copy argv" />
      </button>
      {open ? (
        <div className={styles.commandBody}>
          <pre className={styles.commandArgv} aria-label="Command arguments">
            {argvText}
          </pre>
          <div className={styles.commandMeta}>
            <span>
              Working directory: <code>{preview.cwd}</code>
            </span>
            {Object.entries(preview.env).map(([key, value]) => (
              <span key={key}>
                {key}: <code>{value}</code>
              </span>
            ))}
            <span>Credential values are always redacted.</span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
