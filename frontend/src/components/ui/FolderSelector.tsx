/**
 * Native folder picker button (SPEC §33.3).
 *
 * Opens a server-backed directory browser modal. A browser cannot read the
 * absolute filesystem path of a folder chosen via `<input type="file"
 * webkitdirectory>` — that input only enumerates the folder and yields a bare
 * folder name. The picker instead browses the backend host's filesystem and
 * pastes the chosen absolute directory path into the form.
 *
 * The public API (`onSelect(path)`, `label`) is unchanged from the old
 * implementation so existing call sites need no edits.
 */

import { useEffect, useState } from "react";
import { useBrowseDir } from "../../api/hooks";
import { ApiError } from "../../api/client";
import { formatApiErrorDetail } from "../../api/errors";
import { Button } from "./Button";
import { Modal } from "./Modal";
import { IconFolder } from "./icons";
import styles from "./ui.module.css";

interface FolderSelectorProps {
  /** Called with the absolute directory path when the user selects a folder. */
  onSelect: (path: string) => void;
  /** ARIA label for accessibility. */
  label?: string;
}

export function FolderSelector({ onSelect, label = "Select folder" }: FolderSelectorProps) {
  const [open, setOpen] = useState(false);
  // Empty string => backend returns the home directory.
  const [currentPath, setCurrentPath] = useState("");

  return (
    <>
      <button
        type="button"
        className={`${styles.button} ${styles.buttonTertiary} ${styles.buttonSm}`}
        onClick={() => setOpen(true)}
        aria-label={label}
        title={label}
      >
        <IconFolder size={16} />
      </button>

      <FolderBrowserModal
        open={open}
        onOpenChange={setOpen}
        currentPath={currentPath}
        onNavigate={setCurrentPath}
        onSelect={(path) => {
          onSelect(path);
          setOpen(false);
        }}
      />
    </>
  );
}

interface FolderBrowserModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  currentPath: string;
  onNavigate: (path: string) => void;
  onSelect: (path: string) => void;
}

function FolderBrowserModal({
  open,
  onOpenChange,
  currentPath,
  onNavigate,
  onSelect,
}: FolderBrowserModalProps) {
  const { data, isLoading, error } = useBrowseDir(currentPath, { enabled: open });

  // Reset to home whenever the modal is (re)opened so each session starts fresh.
  useEffect(() => {
    if (open) onNavigate("");
    // We intentionally only react to `open`; reacting to onNavigate/currentPath
    // would reset navigation on every step.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const parent = data?.parent ?? null;
  const entries = data?.entries ?? [];
  const displayPath = data?.path ?? currentPath;

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="Select folder"
      description="Browse this computer's directories and choose a folder."
      width={560}
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)} autoFocus>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => onSelect(displayPath)}
            disabled={!data || !!error}
          >
            Select this folder
          </Button>
        </>
      }
    >
      {/* Current path + Up navigation */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <Button
          variant="tertiary"
          size="small"
          disabled={!parent}
          onClick={() => parent && onNavigate(parent)}
          title={parent ? `Up to ${parent}` : "Already at a root"}
        >
          ↑ Up
        </Button>
        <div
          style={{
            flex: 1,
            minWidth: 0,
            fontFamily: "var(--font-mono, monospace)",
            fontSize: 12.5,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            userSelect: "all",
          }}
          title={displayPath}
        >
          {displayPath || "Home"}
        </div>
      </div>

      {isLoading ? (
        <p style={{ padding: "12px 0", opacity: 0.7 }}>Loading directories…</p>
      ) : error ? (
        <BrowseError error={error} />
      ) : entries.length === 0 ? (
        <p style={{ padding: "12px 0", opacity: 0.7 }}>No subdirectories here.</p>
      ) : (
        <ul
          style={{
            listStyle: "none",
            margin: 0,
            padding: 0,
            maxHeight: 320,
            overflowY: "auto",
            border: "1px solid var(--border, #333)",
            borderRadius: 6,
          }}
        >
          {entries.map((entry) => (
            <li key={entry.path}>
              <button
                type="button"
                onClick={() => onNavigate(entry.path)}
                onDoubleClick={() => onSelect(entry.path)}
                style={{
                  width: "100%",
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "6px 10px",
                  background: "transparent",
                  border: "none",
                  color: "inherit",
                  textAlign: "left",
                  cursor: "pointer",
                  fontFamily: "var(--font-mono, monospace)",
                  fontSize: 13,
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "var(--hover, rgba(255,255,255,0.06))")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                title={`Open ${entry.path}`}
              >
                <IconFolder size={15} />
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {entry.name}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {data?.truncated ? (
        <p style={{ marginTop: 6, fontSize: 11.5, opacity: 0.7 }}>
          Showing the first 500 directories; navigate closer to see more.
        </p>
      ) : null}
    </Modal>
  );
}

function BrowseError({ error }: { error: unknown }) {
  const detail =
    error instanceof ApiError ? formatApiErrorDetail(error.body?.detail) : null;
  const message =
    error instanceof ApiError
      ? error.body?.message ?? "Could not list this directory."
      : "Could not list this directory.";
  return (
    <div style={{ padding: "10px 0", color: "var(--danger, #e06c75)" }}>
      <p style={{ margin: 0, fontWeight: 600 }}>{message}</p>
      {detail ? (
        <p style={{ margin: "4px 0 0", fontSize: 12, opacity: 0.85 }}>{detail}</p>
      ) : null}
    </div>
  );
}
