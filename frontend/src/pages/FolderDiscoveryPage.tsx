/**
 * Folder discovery (SPEC §5, §33.3): path entry + validation + recently used
 * + scan-depth + scan preview with per-repo exclude checkboxes → register.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  useCreateFolder,
  useRegisterScanned,
  useScanFolder,
} from "../api/hooks";
import { PageHeader } from "../layouts/AppLayout";
import {
  Button,
  ErrorState,
  FolderSelector,
  Input,
  Select,
  StatusDot,
  toast,
} from "../components/ui";
import { IconFolder } from "../components/ui/icons";
import type { FolderScan } from "../types";
import layout from "../layouts/layout.module.css";
import styles from "./pages.module.css";

const RECENT_KEY = "ocrcc.recentFolderPaths";

function loadRecent(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed) ? parsed.filter((p) => typeof p === "string").slice(0, 6) : [];
  } catch {
    return [];
  }
}

function saveRecent(path: string) {
  try {
    const next = [path, ...loadRecent().filter((p) => p !== path)].slice(0, 6);
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
}

export function FolderDiscoveryPage() {
  const navigate = useNavigate();
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [depth, setDepth] = useState("2");
  const [recent] = useState(loadRecent);
  const [scan, setScan] = useState<FolderScan | null>(null);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [error, setError] = useState<unknown>(null);

  const createFolder = useCreateFolder();
  const scanFolder = useScanFolder();
  const register = useRegisterScanned();

  const scanning = createFolder.isPending || scanFolder.isPending;

  async function runScan() {
    setError(null);
    setScan(null);
    const trimmed = path.trim();
    if (!trimmed) {
      setError(new Error("Enter an absolute directory path to scan."));
      return;
    }
    try {
      const folder = await createFolder.mutateAsync({
        display_name: name.trim() || trimmed.split(/[\\/]/).filter(Boolean).pop() || trimmed,
        absolute_path: trimmed,
        scan_depth: Number.parseInt(depth, 10),
      });
      const result = await scanFolder.mutateAsync(folder.id);
      setScan(result);
      setExcluded(new Set());
      saveRecent(trimmed);
    } catch (err) {
      setError(err);
    }
  }

  async function registerSelected() {
    if (!scan) return;
    const paths = scan.repos
      .filter((r) => !r.already_registered && !excluded.has(r.path))
      .map((r) => r.path);
    if (paths.length === 0) {
      toast.info("Nothing to register", "Every discovered repository is excluded or already registered.");
      return;
    }
    try {
      const created = await register.mutateAsync({ folderId: scan.folder_id, paths });
      toast.success(
        `Registered ${created.length} project${created.length === 1 ? "" : "s"}`,
        "Branches are being loaded in the background.",
      );
      navigate("/projects");
    } catch (err) {
      setError(err);
    }
  }

  const newRepos = scan?.repos.filter((r) => !r.already_registered) ?? [];

  return (
    <>
      <PageHeader
        title="Add folder"
        subtitle="Scan a directory for Git repositories and register the ones you want to review."
      />
      <div className={`${layout.stack} ${layout.stackLg}`} style={{ maxWidth: 720 }}>
        <section className={`${layout.section} ${layout.stack}`} aria-label="Folder location">
          <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
            <label style={{ font: "var(--text-label)", color: "var(--text-secondary)", display: "block" }} htmlFor="folder-path">
              Directory path <span style={{ color: "var(--danger)" }}>*</span>
            </label>
            <div className={layout.row} style={{ gap: 8, marginTop: 4 }}>
              <input
                id="folder-path"
                className={styles.input}
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder="C:\code\work or /home/you/projects"
                style={{ flex: 1, font: "var(--text-code)", height: 32, padding: "0 12px", border: "1px solid var(--border-strong)", borderRadius: 8, background: "var(--bg-surface)", color: "var(--text-primary)" }}
                required
              />
              <FolderSelector label="Select folder" onSelect={(p) => setPath(p)} />
            </div>
            <p style={{ font: "var(--text-small)", color: "var(--text-tertiary)" }}>Absolute path to a directory that contains one or more Git repositories.</p>
          </div>
          {recent.length > 0 ? (
            <div>
              <p className={layout.small} style={{ marginBottom: 6 }}>Recently used</p>
              <div className={styles.recentChips}>
                {recent.map((p) => (
                  <button key={p} type="button" className={styles.chip} onClick={() => setPath(p)}>
                    {p}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          <div className={layout.grid2}>
            <Input
              label="Display name (optional)"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Work projects"
            />
            <Select
              label="Scan depth"
              value={depth}
              onChange={(e) => setDepth(e.target.value)}
              help="How many directory levels below the root to search. Default: 2."
            >
              {[0, 1, 2, 3, 4].map((d) => (
                <option key={d} value={d}>
                  {d === 0 ? "0 — this directory only" : `${d} level${d === 1 ? "" : "s"}`}
                </option>
              ))}
            </Select>
          </div>
          <div className={layout.row}>
            <Button variant="primary" onClick={runScan} disabled={scanning || !path.trim()}>
              <IconFolder size={14} />
              {scanning ? "Scanning…" : "Scan for repositories"}
            </Button>
          </div>
          {error ? <ErrorState title="Scan failed" error={error} /> : null}
        </section>

        {scan ? (
          <section className={`${layout.section} ${layout.stack}`} aria-label="Scan results">
            <div className={layout.sectionHeader} style={{ margin: 0 }}>
              <h2 className={layout.sectionTitle} style={{ margin: 0 }}>
                Found {scan.repos.length} repositor{scan.repos.length === 1 ? "y" : "ies"}
              </h2>
              <span className={layout.small}>
                {newRepos.length - excluded.size} selected to register
              </span>
            </div>
            {scan.errors.length > 0 ? (
              <div className={styles.warningBox}>
                <span>
                  {scan.errors.length} location{scan.errors.length === 1 ? "" : "s"} could not be read and were skipped.
                </span>
              </div>
            ) : null}
            {scan.repos.length === 0 ? (
              <p className={layout.muted}>
                No Git repositories found within the scan depth. Try increasing the depth.
              </p>
            ) : (
              <ul className={layout.stack} style={{ gap: 4 }}>
                {scan.repos.map((repo) => {
                  const isExcluded = excluded.has(repo.path);
                  return (
                    <li key={repo.path} className={layout.row} style={{ flexWrap: "nowrap", gap: 12 }}>
                      <input
                        type="checkbox"
                        id={`repo-${repo.path}`}
                        checked={!isExcluded && !repo.already_registered}
                        disabled={repo.already_registered}
                        onChange={(e) => {
                          setExcluded((prev) => {
                            const next = new Set(prev);
                            if (e.target.checked) next.delete(repo.path);
                            else next.add(repo.path);
                            return next;
                          });
                        }}
                        aria-label={`Include ${repo.name}`}
                      />
                      <label htmlFor={`repo-${repo.path}`} style={{ flex: 1, minWidth: 0 }}>
                        <span className={layout.monoPath} style={{ fontSize: 12.5 }}>
                          {repo.path}
                        </span>
                      </label>
                      {repo.already_registered ? (
                        <StatusDot tone="muted" label="registered" />
                      ) : repo.has_git_file ? (
                        <StatusDot tone="accent" label="worktree" />
                      ) : (
                        <StatusDot tone="ok" label="repo" />
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
            <div className={layout.row}>
              <Button
                variant="primary"
                onClick={registerSelected}
                disabled={register.isPending || newRepos.length - excluded.size <= 0}
              >
                {register.isPending ? "Registering…" : "Register selected projects"}
              </Button>
              <Button variant="tertiary" onClick={() => setScan(null)}>
                Discard scan
              </Button>
            </div>
          </section>
        ) : null}
      </div>
    </>
  );
}
