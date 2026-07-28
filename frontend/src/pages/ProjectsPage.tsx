/** Project list (SPEC §20) — folders as collapsible groups, refined table. */

import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  useCreateFolder,
  useCreateProject,
  useDeleteFolder,
  useFolders,
  useProjects,
  useRegisterScanned,
  useScanFolder,
} from "../api/hooks";
import { PageHeader } from "../layouts/AppLayout";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  FolderSelector,
  Input,
  Menu,
  Modal,
  Select,
  Skeleton,
  StatusDot,
  Table,
  TBody,
  Td,
  Th,
  THead,
  Tr,
  toast,
} from "../components/ui";
import {
  IconChevronDown,
  IconChevronRight,
  IconFolder,
  IconMore,
  IconPlus,
} from "../components/ui/icons";
import { relativeTime } from "../lib/format";
import type { Folder, FolderScan, Project } from "../types";
import layout from "../layouts/layout.module.css";
import styles from "./pages.module.css";

// --- Unified Add dialog -----------------------------------------------------

type AddMode = "project" | "scan";

function AddDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const [mode, setMode] = useState<AddMode>("project");
  const [path, setPath] = useState("");
  const [error, setError] = useState<unknown>(null);

  // Single-project state
  const createProject = useCreateProject();

  // Scan-folder state
  const createFolder = useCreateFolder();
  const scanFolder = useScanFolder();
  const register = useRegisterScanned();
  const [depth, setDepth] = useState("2");
  const [scan, setScan] = useState<FolderScan | null>(null);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());

  const scanning = createFolder.isPending || scanFolder.isPending;

  async function addProject() {
    setError(null);
    try {
      const project = await createProject.mutateAsync({
        absolute_path: path.trim(),
        folder_id: null,
      });
      toast.success(`Added ${project.display_name}`);
      onOpenChange(false);
      setPath("");
      setMode("project");
    } catch (err) {
      setError(err);
    }
  }

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
        display_name: trimmed.split(/[\\/]/).filter(Boolean).pop() || trimmed,
        absolute_path: trimmed,
        scan_depth: Number.parseInt(depth, 10),
      });
      const result = await scanFolder.mutateAsync(folder.id);
      setScan(result);
      setExcluded(new Set());
    } catch (err) {
      setError(err);
    }
  }

  async function registerSelected() {
    if (!scan) return;
    const selected = scan.repos.filter(
      (r) => !r.already_registered && !excluded.has(r.path),
    );
    if (selected.length === 0) {
      toast.info("Nothing to register");
      return;
    }
    try {
      const created = await register.mutateAsync({
        folderId: scan.folder_id,
        paths: selected.map((r) => r.path),
      });
      toast.success(`Registered ${created.length} project${created.length === 1 ? "" : "s"}`);
      onOpenChange(false);
      setPath("");
      setMode("project");
      setScan(null);
      navigate("/projects");
    } catch (err) {
      setError(err);
    }
  }

  const newRepos = scan?.repos.filter((r) => !r.already_registered) ?? [];
  const selectedCount = newRepos.filter((r) => !excluded.has(r.path)).length;

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="Add"
      description={
        mode === "project"
          ? "Register a single Git repository by its absolute path."
          : "Scan a directory for Git repositories and register them."
      }
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          {mode === "project" ? (
            <Button
              variant="primary"
              onClick={addProject}
              disabled={createProject.isPending || !path.trim()}
            >
              {createProject.isPending ? "Validating…" : "Add project"}
            </Button>
          ) : scan ? (
            <Button
              variant="primary"
              onClick={registerSelected}
              disabled={register.isPending || selectedCount <= 0}
            >
              {register.isPending ? "Registering…" : `Register ${selectedCount} project${selectedCount === 1 ? "" : "s"}`}
            </Button>
          ) : (
            <Button
              variant="primary"
              onClick={runScan}
              disabled={scanning || !path.trim()}
            >
              {scanning ? "Scanning…" : "Scan for repositories"}
            </Button>
          )}
        </>
      }
    >
      <div className={layout.stack}>
        {/* Mode toggle */}
        <div className={layout.row} style={{ gap: 8 }}>
          <Button
            variant={mode === "project" ? "primary" : "tertiary"}
            size="small"
            onClick={() => { setMode("project"); setScan(null); }}
          >
            <IconPlus size={14} /> Single project
          </Button>
          <Button
            variant={mode === "scan" ? "primary" : "tertiary"}
            size="small"
            onClick={() => { setMode("scan"); setScan(null); }}
          >
            <IconFolder size={14} /> Scan folder
          </Button>
        </div>

        {/* Path input with folder picker */}
        <div className={layout.row} style={{ gap: 8 }}>
          <div style={{ flex: 1 }}>
            <Input
              label="Path"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder={mode === "project" ? "C:\\code\\my-repo" : "C:\\code\\work"}
              mono
              required
              help={mode === "project" ? "Must be a Git working tree — bare repositories are rejected." : "Absolute path to a directory containing Git repositories."}
            />
          </div>
          <div style={{ paddingTop: 28 }}>
            <FolderSelector
              label="Select folder"
              onSelect={(selectedPath) => setPath(selectedPath)}
            />
          </div>
        </div>

        {/* Scan-depth selector (scan mode only) */}
        {mode === "scan" && !scan ? (
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
        ) : null}

        {/* Scan results */}
        {mode === "scan" && scan ? (
          <>
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
              <ul className={layout.stack} style={{ gap: 4, maxHeight: 280, overflowY: "auto" }}>
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
            <Button
              variant="tertiary"
              size="small"
              onClick={() => setScan(null)}
              style={{ alignSelf: "flex-start" }}
            >
              Discard scan
            </Button>
          </>
        ) : null}

        {error ? <ErrorState title={mode === "project" ? "Could not add project" : "Scan failed"} error={error} /> : null}
      </div>
    </Modal>
  );
}

// --- Project row/table ------------------------------------------------------

function ProjectRow({ project }: { project: Project }) {
  const navigate = useNavigate();
  return (
    <Tr onClick={() => navigate(`/projects/${project.id}`)}>
      <Td>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <span style={{ fontWeight: 500 }}>{project.display_name}</span>
          <span className={layout.small} style={{ fontSize: 11.5 }}>
            {project.absolute_path}
          </span>
        </div>
      </Td>
      <Td><span className={layout.monoPath} style={{ fontSize: 12.5 }}>{project.current_branch ?? "—"}</span></Td>
      <Td><span className={layout.monoPath} style={{ fontSize: 12.5 }}>{project.default_branch ?? "—"}</span></Td>
      <Td className={layout.small}>{project.remote_name ?? "—"}</Td>
      <Td>
        <StatusDot
          tone={!project.is_available ? "danger" : project.is_dirty ? "warn" : "ok"}
          label={!project.is_available ? "unavailable" : project.is_dirty ? "dirty" : "clean"}
        />
      </Td>
      <Td className={layout.small}>
        {relativeTime(project.last_branch_refresh_at)}
      </Td>
    </Tr>
  );
}

// --- Page -------------------------------------------------------------------

export function ProjectsPage() {
  const projects = useProjects();
  const folders = useFolders();
  const deleteFolder = useDeleteFolder();
  const [addOpen, setAddOpen] = useState(false);
  const [folderToRemove, setFolderToRemove] = useState<Folder | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const grouped = useMemo(() => {
    const byFolder = new Map<string | null, Project[]>();
    for (const project of projects.data ?? []) {
      const key = project.folder_id;
      const list = byFolder.get(key) ?? [];
      list.push(project);
      byFolder.set(key, list);
    }
    const folderList = (folders.data ?? []).map((folder) => ({
      folder,
      projects: byFolder.get(folder.id) ?? [],
    }));
    const orphan = byFolder.get(null) ?? [];
    return { folderList, orphan };
  }, [projects.data, folders.data]);

  function toggle(id: string) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const error = projects.error ?? folders.error;

  return (
    <>
      <PageHeader
        title="Projects"
        subtitle="Git repositories registered for review, grouped by folder."
        actions={
          <Button variant="primary" onClick={() => setAddOpen(true)}>
            <IconPlus size={14} /> Add
          </Button>
        }
      />

      {error ? (
        <ErrorState title="Could not load projects" error={error} onRetry={() => projects.refetch()} />
      ) : projects.isLoading ? (
        <div className={layout.stack}>
          <Skeleton height={42} />
          <Skeleton height={42} />
          <Skeleton height={42} />
        </div>
      ) : (projects.data ?? []).length === 0 ? (
        <div className={layout.section}>
          <EmptyState
            icon={<IconFolder size={32} />}
            title="No projects yet"
            body="Add a single project or scan a folder to discover repositories."
            action={
              <Button variant="primary" onClick={() => setAddOpen(true)}>
                <IconPlus size={14} /> Add
              </Button>
            }
          />
        </div>
      ) : (
        <div className={layout.stack}>
          {grouped.folderList.map(({ folder, projects: list }) => (
            <section key={folder.id} aria-label={folder.display_name}>
              <div className={layout.row} style={{ justifyContent: "space-between", marginBottom: 6 }}>
                <button
                  type="button"
                  className={layout.row}
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    font: "var(--text-label)",
                    fontSize: 13,
                    color: "var(--text-primary)",
                    padding: 0,
                  }}
                  onClick={() => toggle(folder.id)}
                  aria-expanded={!collapsed.has(folder.id)}
                >
                  {collapsed.has(folder.id) ? (
                    <IconChevronRight size={14} />
                  ) : (
                    <IconChevronDown size={14} />
                  )}
                  <IconFolder size={15} />
                  {folder.display_name}
                  <span className={layout.small}>
                    {list.length} project{list.length === 1 ? "" : "s"} · scanned{" "}
                    {relativeTime(folder.last_scanned_at)}
                  </span>
                </button>
                <Menu
                  ariaLabel={`Folder actions for ${folder.display_name}`}
                  trigger={
                    <Button variant="tertiary" size="small" aria-label="Folder actions">
                      <IconMore size={16} />
                    </Button>
                  }
                  items={[
                    {
                      key: "remove",
                      label: "Remove folder",
                      danger: true,
                      onSelect: () => setFolderToRemove(folder),
                    },
                  ]}
                />
              </div>
              {!collapsed.has(folder.id) ? (
                list.length === 0 ? (
                  <p className={layout.small} style={{ padding: "4px 0 12px 24px" }}>
                    No projects registered from this folder yet.
                  </p>
                ) : (
                  <ProjectTable projects={list} />
                )
              ) : null}
            </section>
          ))}
          {grouped.orphan.length > 0 ? (
            <section aria-label="Individual projects">
              <p className={layout.small} style={{ marginBottom: 6 }}>
                Individual projects
              </p>
              <ProjectTable projects={grouped.orphan} />
            </section>
          ) : null}
        </div>
      )}

      <AddDialog open={addOpen} onOpenChange={setAddOpen} />
      <ConfirmDialog
        open={folderToRemove !== null}
        onOpenChange={(open) => {
          if (!open) setFolderToRemove(null);
        }}
        title="Remove folder"
        description={`Remove "${folderToRemove?.display_name}" and unregister its projects? The Git repositories on disk are never touched.`}
        confirmLabel="Remove folder"
        destructive
        busy={deleteFolder.isPending}
        onConfirm={async () => {
          if (!folderToRemove) return;
          try {
            await deleteFolder.mutateAsync(folderToRemove.id);
            toast.success("Folder removed");
            setFolderToRemove(null);
          } catch (err) {
            toast.error("Could not remove folder", err instanceof Error ? err.message : undefined);
          }
        }}
      />
    </>
  );
}

function ProjectTable({ projects }: { projects: Project[] }) {
  return (
    <Table>
      <THead>
        <tr>
          <Th>Project</Th>
          <Th>Current branch</Th>
          <Th>Default branch</Th>
          <Th>Remote</Th>
          <Th>Working tree</Th>
          <Th>Last refresh</Th>
        </tr>
      </THead>
      <TBody>
        {projects.map((project) => (
          <ProjectRow key={project.id} project={project} />
        ))}
      </TBody>
    </Table>
  );
}
