/**
 * Native folder picker button (SPEC §33.3).
 *
 * Renders a small button that, when clicked, opens the OS native folder
 * picker via `<input type="file" webkitdirectory>`. When a folder is
 * selected, the callback is invoked with the directory path.
 */

import { useRef } from "react";
import { IconFolder } from "./icons";
import styles from "./ui.module.css";

interface FolderSelectorProps {
  /** Called with the absolute directory path when the user selects a folder. */
  onSelect: (path: string) => void;
  /** ARIA label for accessibility. */
  label?: string;
}

export function FolderSelector({ onSelect, label = "Select folder" }: FolderSelectorProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  function handleClick() {
    const input = inputRef.current;
    if (!input) return;
    // Reset so the same folder can be re-selected.
    input.value = "";
    input.click();
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file?.webkitRelativePath) {
      // webkitRelativePath is "rootDir/..." — strip to root directory.
      const root = file.webkitRelativePath.split("/")[0];
      onSelect(root);
    } else {
      // Fallback: use the file's name as the folder name.
      onSelect(file.name);
    }
  }

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept="*/*"
        webkitdirectory
        directory
        style={{ display: "none" }}
        onChange={handleChange}
      />
      <button
        type="button"
        className={`${styles.button} ${styles.buttonTertiary} ${styles.buttonSm}`}
        onClick={handleClick}
        aria-label={label}
        title={label}
      >
        <IconFolder size={16} />
      </button>
    </>
  );
}
