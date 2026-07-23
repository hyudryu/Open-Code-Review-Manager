/** Project list (SPEC §20) — folders as collapsible groups, refined table. */

import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  useCreateProject,
  useDeleteFolder,
  useFolders,
  useProjects,
} from "../api/hooks";
import { PageHeader } from "../layouts/AppLayout";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Input,
  Menu,
  Modal,
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
import type { Folder, Project } from "../types";
import layout from "../layouts/layout.module.css";

function AddProjectDialog({
  open,
  onOpenChange,
  folders,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  folders: Folder[];
}) {
  const [path, setPath] = useState("");
  const [folderId, setFolderId] = useState("");
  const [error, setError] = useState<unknown>(null);
  const create = useCreateProject();

  async function submit() {
    setError(null);
    try {
      const project = await create.mutateAsync({
        absolute_path: path.trim(),
        folder_id: folderId || null,
      });
      toast.success(`Added ${project.display_name}`);
      onOpenChange(false);
      setPath("");
    } catch (err) {
      setError(err);
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="Add project"
      description="Register a single Git repository by its absolute path. The repository is validated with Git before it is added."
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} disabled={create.isPending || !path.trim()}>
            {create.isPending ? "Validating…" : "Add project"}
          </Button>
        </>
      }
    >
      <div className={layout.stack}>
        <Input
          label="Repository path"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder="C:\code\my-repo"
          help="Must be a Git working tree — bare repositories are rejected for review execution."
          mono
          required
        />
        <label className={layout.small}>
          Folder (optional)
          <select
            className=""
            style={{
              width: "100%",
              height: 32,
              marginTop: 4,
              borderRadius: 8,
              border: "1px solid var(--border-strong)",
              background: "var(--bg-surface)",
              color: "var(--text-primary)",
              padding: "0 12px",
            }}
            value={folderId}
            onChange={(e) => setFolderId(e.target.value)}
          >
            <option value="">No folder</option>
            {folders.map((f) => (
              <option key={f.id} value={f.id}>
                {f.display_name}
              </option>
            ))}
          </select>
        </label>
        {error ? <ErrorState title="Could not add project" error={error} /> : null}
      </div>
    </Modal>
  );
}

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

export function ProjectsPage() {
  const navigate = useNavigate();
  const projects = useProjects();
  const folders = useFolders();
  const deleteFolder = useDeleteFolder();
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [addOpen, setAddOpen] = useState(false);
  const [folderToRemove, setFolderToRemove] = useState<Folder | null>(null);

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
          <>
            <Button variant="secondary" onClick={() => setAddOpen(true)}>
              <IconPlus size={14} /> Add project
            </Button>
            <Button variant="primary" onClick={() => navigate("/projects/new-folder")}>
              <IconFolder size={14} /> Add folder
            </Button>
          </>
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
            body="Add a folder to discover multiple repositories at once, or register a single repository directly."
            action={
              <Button variant="primary" onClick={() => navigate("/projects/new-folder")}>
                <IconFolder size={14} /> Add folder
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
                    No projects registered from this folder yet.{" "}
                    <Link to="/projects/new-folder">Rescan</Link>
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

      <AddProjectDialog open={addOpen} onOpenChange={setAddOpen} folders={folders.data ?? []} />
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
