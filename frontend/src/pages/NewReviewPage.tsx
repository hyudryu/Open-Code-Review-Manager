/**
 * New Review (SPEC §7, §33.6): range / commit / workspace modes, profile
 * picker, merged background context, overrides, priority, webhook, expert
 * additional-args validation, live command preview (SPEC §36).
 */

import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useForm, Controller } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  useBranches,
  useCreateJob,
  useProfiles,
  useProject,
  useProjects,
  useSystemOcr,
  useWebhooks,
} from "../api/hooks";
import { PageHeader } from "../layouts/AppLayout";
import {
  Button,
  ErrorState,
  Input,
  Select,
  Textarea,
  toast,
} from "../components/ui";
import { IconTerminal } from "../components/ui/icons";
import { BranchSelector } from "../features/reviews/BranchSelector";
import { CommandPreviewView } from "../features/reviews/CommandPreview";
import { parseAdditionalArgs } from "../lib/args";
import { buildCommandPreview } from "../lib/command";
import type { Branch, JobMode } from "../types";
import layout from "../layouts/layout.module.css";
import styles from "./pages.module.css";

const schema = z.object({
  project_id: z.string().min(1, "Choose a project."),
  mode: z.enum(["range", "commit", "workspace"]),
  profile_id: z.string(),
  background: z.string(),
  background_file: z.string(),
  rule_file: z.string(),
  excludes: z.string(),
  priority: z.coerce.number().int().min(0).max(100),
  webhook_endpoint_id: z.string(),
});

type FormValues = z.infer<typeof schema>;

function FieldLabel({ children, htmlFor }: { children: React.ReactNode; htmlFor?: string }) {
  return (
    <label className="field-label" htmlFor={htmlFor} style={{ font: "var(--text-label)", color: "var(--text-secondary)", display: "block", marginBottom: 4 }}>
      {children}
    </label>
  );
}

export function NewReviewPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const preselectedProject = params.get("project") ?? "";

  const projects = useProjects();
  const profiles = useProfiles();
  const webhooks = useWebhooks();
  const ocr = useSystemOcr();
  const createJob = useCreateJob();

  const {
    register,
    control,
    watch,
    setValue,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      project_id: preselectedProject,
      mode: "range",
      profile_id: "",
      background: "",
      background_file: "",
      rule_file: "",
      excludes: "",
      priority: 50,
      webhook_endpoint_id: "",
    },
  });

  const projectId = watch("project_id");
  const mode = watch("mode") as JobMode;
  const profileId = watch("profile_id");
  const background = watch("background");
  const backgroundFile = watch("background_file");
  const excludesRaw = watch("excludes");
  const ruleFile = watch("rule_file");

  const project = useProject(projectId);
  const branches = useBranches(projectId);

  const [baseRef, setBaseRef] = useState<string | null>(null);
  const [targetRef, setTargetRef] = useState<string | null>(null);
  const [commitRef, setCommitRef] = useState<string | null>(null);
  const [baseBranch, setBaseBranch] = useState<Branch | null>(null);
  const [targetBranch, setTargetBranch] = useState<Branch | null>(null);
  const [submitError, setSubmitError] = useState<unknown>(null);
  const [expertOpen, setExpertOpen] = useState(false);

  // Sensible defaults once a project's branches arrive.
  useEffect(() => {
    const list = branches.data ?? [];
    if (list.length === 0) return;
    const current = list.find((b) => b.is_current && b.kind === "local");
    const def = list.find((b) => b.is_default);
    if (!targetRef) {
      setTargetRef(current?.name ?? list.find((b) => b.kind === "local")?.name ?? null);
      setTargetBranch(current ?? null);
    }
    if (!baseRef) {
      setBaseRef(def?.name ?? null);
      setBaseBranch(def ?? null);
    }
  }, [branches.data, baseRef, targetRef]);

  const profile = useMemo(
    () => (profiles.data ?? []).find((p) => p.id === profileId) ?? null,
    [profiles.data, profileId],
  );

  // Default to the first profile once loaded.
  useEffect(() => {
    if (!profileId && profiles.data?.length) {
      setValue("profile_id", profiles.data[0].id);
    }
  }, [profiles.data, profileId, setValue]);

  const parsedArgs = useMemo(
    () => parseAdditionalArgs(profile?.additional_arguments ?? ""),
    [profile],
  );

  const excludePatterns = useMemo(
    () =>
      excludesRaw
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean),
    [excludesRaw],
  );

  const preview = useMemo(
    () =>
      buildCommandPreview(
        {
          mode,
          repoPath:
            mode === "workspace"
              ? project.data?.absolute_path ?? "<project path>"
              : `<data-dir>/worktrees/${projectId || "<project>"}/<job>`,
          baseRef,
          targetRef,
          commitRef,
          baseSha: baseBranch?.commit_sha,
          targetSha: targetBranch?.commit_sha,
          profile,
          background: background || null,
          backgroundFile: backgroundFile || null,
          excludePatterns: excludePatterns.length ? excludePatterns : null,
          additionalArgs: parsedArgs.ok ? parsedArgs.argv : [],
        },
        ocr.data,
      ),
    [
      mode, project.data, projectId, baseRef, targetRef, commitRef,
      baseBranch, targetBranch, profile, background, backgroundFile,
      excludePatterns, parsedArgs, ocr.data,
    ],
  );

  const [overrideSummary, setOverrideSummary] = useState<string | null>(null);
  useEffect(() => {
    const parts: string[] = [];
    if (ruleFile.trim()) parts.push("rule file override");
    if (excludePatterns.length) parts.push(`${excludePatterns.length} exclude override${excludePatterns.length === 1 ? "" : "s"}`);
    setOverrideSummary(parts.length ? parts.join(" · ") : null);
  }, [ruleFile, excludePatterns]);

  const ocrMissing = ocr.data && ocr.data.status !== "ok";

  async function onSubmit(values: FormValues) {
    setSubmitError(null);
    if (values.mode === "range" && (!baseRef || !targetRef)) {
      setSubmitError(new Error("Select both a base and a target ref for a range review."));
      return;
    }
    if (values.mode === "commit" && !commitRef) {
      setSubmitError(new Error("Select a commit or ref to review."));
      return;
    }
    try {
      const job = await createJob.mutateAsync({
        project_id: values.project_id,
        mode: values.mode,
        base_ref: values.mode === "range" ? baseRef : null,
        target_ref: values.mode === "range" ? targetRef : null,
        commit_ref: values.mode === "commit" ? commitRef : null,
        profile_id: values.profile_id || null,
        background: values.background.trim() || null,
        background_file: values.background_file.trim() || null,
        exclude_patterns: excludePatterns.length ? excludePatterns : null,
        priority: values.priority,
        webhook_endpoint_id: values.webhook_endpoint_id || null,
      });
      toast.success("Review queued", "Refs are resolved to immutable SHAs at queue time.");
      navigate(`/jobs/${job.id}`);
    } catch (err) {
      setSubmitError(err);
    }
  }

  const localAndTags: ("local" | "remote" | "tag")[] = ["local", "remote", "tag"];

  return (
    <>
      <PageHeader
        title="New review"
        subtitle="Queue a workspace, branch-range, or single-commit review."
      />

      {ocrMissing ? (
        <div style={{ marginBottom: 16 }}>
          <ErrorState
            title="OpenCodeReview is not available"
            error={{
              message:
                "The ocr executable was not detected. Jobs can be configured but will fail until OCR is installed.",
            }}
          />
          <p className={layout.small} style={{ marginTop: 8 }}>
            <Link to="/settings">Configure the OCR path in Settings</Link>
          </p>
        </div>
      ) : null}

      <form onSubmit={handleSubmit(onSubmit)} className={`${layout.stack} ${layout.stackLg}`} style={{ maxWidth: 860 }}>
        {/* Mode */}
        <section className={`${layout.section} ${layout.stack}`} aria-label="Review target">
          <div className={layout.grid2} style={{ gridTemplateColumns: "1fr 1fr" }}>
            <Controller
              control={control}
              name="project_id"
              render={({ field }) => (
                <Select
                  label="Project"
                  required
                  error={errors.project_id?.message}
                  value={field.value}
                  onChange={(e) => {
                    field.onChange(e);
                    setBaseRef(null);
                    setTargetRef(null);
                    setCommitRef(null);
                    setBaseBranch(null);
                    setTargetBranch(null);
                  }}
                >
                  <option value="">Choose a project…</option>
                  {(projects.data ?? []).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.display_name}
                    </option>
                  ))}
                </Select>
              )}
            />
            <Controller
              control={control}
              name="mode"
              render={({ field }) => (
                <Select label="Review mode" required value={field.value} onChange={field.onChange}>
                  <option value="range">Range — compare two refs</option>
                  <option value="commit">Commit — review one commit</option>
                  <option value="workspace">Workspace — uncommitted changes</option>
                </Select>
              )}
            />
          </div>

          {mode === "range" ? (
            <div className={layout.grid2} style={{ gridTemplateColumns: "1fr 1fr" }}>
              <div>
                <FieldLabel htmlFor="base-ref">Base ref</FieldLabel>
                <BranchSelector
                  id="base-ref"
                  ariaLabel="Base ref"
                  branches={branches.data ?? []}
                  kinds={localAndTags}
                  value={baseRef}
                  onChange={(name, branch) => {
                    setBaseRef(name);
                    setBaseBranch(branch);
                  }}
                  placeholder={projectId ? "Select base…" : "Choose a project first"}
                  disabled={!projectId}
                />
              </div>
              <div>
                <FieldLabel htmlFor="target-ref">Target ref</FieldLabel>
                <BranchSelector
                  id="target-ref"
                  ariaLabel="Target ref"
                  branches={branches.data ?? []}
                  kinds={localAndTags}
                  value={targetRef}
                  onChange={(name, branch) => {
                    setTargetRef(name);
                    setTargetBranch(branch);
                  }}
                  placeholder={projectId ? "Select target…" : "Choose a project first"}
                  disabled={!projectId}
                />
              </div>
            </div>
          ) : null}

          {mode === "commit" ? (
            <div>
              <FieldLabel htmlFor="commit-ref">Commit / ref</FieldLabel>
              <BranchSelector
                id="commit-ref"
                ariaLabel="Commit or ref"
                branches={branches.data ?? []}
                kinds={localAndTags}
                value={commitRef}
                onChange={(name) => setCommitRef(name)}
                placeholder={projectId ? "Select a ref…" : "Choose a project first"}
                disabled={!projectId}
              />
              <p className={layout.help} style={{ marginTop: 4 }}>
                Any ref resolving to a commit works — a full SHA can be pasted via the branch search.
              </p>
            </div>
          ) : null}

          {mode === "workspace" ? (
            <div className={styles.warningBox} role="note">
              <span>
                Workspace reviews run against the real project path (not an isolated
                worktree) so uncommitted changes are included. Results reflect the
                working state at execution time — if the tree changes before the job
                starts, you will see a warning in the job events.
              </span>
            </div>
          ) : null}

          {projectId && branches.data && branches.data.length === 0 ? (
            <p className={layout.small}>
              No branches cached for this project.{" "}
              <Link to={`/projects/${projectId}`}>Refresh branches</Link> on the project page.
            </p>
          ) : null}
        </section>

        {/* Profile */}
        <section className={`${layout.section} ${layout.stack}`} aria-label="Review profile">
          <Controller
            control={control}
            name="profile_id"
            render={({ field }) => (
              <Select
                label="Review profile"
                value={field.value}
                onChange={field.onChange}
                help={
                  profiles.data?.length
                    ? "Provider, model, and OCR options come from the profile."
                    : "No profiles yet — create one to choose a provider and model."
                }
              >
                <option value="">No profile (OCR defaults)</option>
                {(profiles.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            )}
          />
          {profile ? (
            <p className={layout.small}>
              {profile.description ??
                `Concurrency ${profile.concurrency ?? "default"} · timeout ${profile.per_file_timeout_minutes ?? "default"} min · plan ${profile.plan_mode}`}
            </p>
          ) : null}
        </section>

        {/* Background context */}
        <section className={`${layout.section} ${layout.stack}`} aria-label="Background context">
          <Textarea
            label="Background context (Markdown, optional)"
            rows={4}
            placeholder="Focus on the authentication changes; ignore generated code style."
            {...register("background")}
          />
          <Input
            label="Background file path (optional)"
            placeholder="docs/review-context.md"
            mono
            {...register("background_file")}
          />
          {(profile?.background_template || background.trim() || backgroundFile.trim()) ? (
            <details>
              <summary className={layout.small} style={{ cursor: "pointer" }}>
                Merged context preview
              </summary>
              <div className={styles.codeBlock} style={{ marginTop: 8, whiteSpace: "pre-wrap" }}>
                {profile?.background_template ? (
                  <>
                    <span style={{ color: "var(--text-tertiary)" }}>
                      # From profile “{profile.name}”{"\n"}
                    </span>
                    {profile.background_template}
                    {"\n\n"}
                  </>
                ) : null}
                {backgroundFile.trim() ? (
                  <span style={{ color: "var(--text-tertiary)" }}>
                    # From file: {backgroundFile.trim()}{"\n\n"}
                  </span>
                ) : null}
                {background.trim() || <span style={{ color: "var(--text-tertiary)" }}>(no inline context)</span>}
              </div>
            </details>
          ) : null}
        </section>

        {/* Overrides + delivery */}
        <section className={`${layout.section} ${layout.stack}`} aria-label="Overrides and delivery">
          <div className={layout.grid2} style={{ gridTemplateColumns: "1fr 1fr" }}>
            <Input
              label="Rule file override (optional)"
              placeholder="rules/strict.md"
              mono
              {...register("rule_file")}
            />
            <Input
              label={`Priority (0–100)${errors.priority ? " — invalid" : ""}`}
              type="number"
              min={0}
              max={100}
              error={errors.priority?.message}
              {...register("priority")}
            />
          </div>
          <Textarea
            label="Exclude pattern overrides (one per line)"
            rows={3}
            placeholder={"*.generated.ts\nvendor/**"}
            mono
            help="Replaces the profile's exclude patterns for this job only."
            {...register("excludes")}
          />
          <Controller
            control={control}
            name="webhook_endpoint_id"
            render={({ field }) => (
              <Select
                label="Webhook endpoint (optional)"
                value={field.value}
                onChange={field.onChange}
                help="A signed callback is delivered when this review reaches a terminal state."
              >
                <option value="">No webhook</option>
                {(webhooks.data ?? [])
                  .filter((w) => w.enabled)
                  .map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name}
                    </option>
                  ))}
              </Select>
            )}
          />
          {overrideSummary ? (
            <p className={layout.small}>Active overrides: {overrideSummary}</p>
          ) : null}
        </section>

        {/* Expert */}
        <section className={`${layout.section} ${layout.stack}`} aria-label="Expert options">
          <button
            type="button"
            className={layout.row}
            style={{ background: "none", border: "none", cursor: "pointer", padding: 0, font: "var(--text-label)", fontSize: 13, color: "var(--text-secondary)" }}
            onClick={() => setExpertOpen((v) => !v)}
            aria-expanded={expertOpen}
          >
            <IconTerminal size={14} />
            Expert options
          </button>
          {expertOpen ? (
            <>
              {parsedArgs.ok && parsedArgs.argv.length > 0 ? (
                <div>
                  <p className={layout.small} style={{ marginBottom: 6 }}>
                    Additional arguments from profile “{profile?.name}” (jobs using custom arguments are marked):
                  </p>
                  <div className={styles.codeBlock} style={{ whiteSpace: "pre-wrap" }}>
                    {parsedArgs.argv.map((arg, i) => (
                      <div key={i}>{arg}</div>
                    ))}
                  </div>
                  <p className={layout.small} style={{ marginTop: 6 }}>
                    Edit them on the <Link to={`/profiles/${profile?.id ?? ""}`}>profile</Link>.
                  </p>
                </div>
              ) : parsedArgs.error ? (
                <ErrorState
                  title="Invalid additional arguments on the selected profile"
                  error={{ message: parsedArgs.error }}
                />
              ) : (
                <p className={layout.small}>
                  The selected profile has no additional arguments. Add them in the{" "}
                  <Link to={profile ? `/profiles/${profile.id}` : "/profiles"}>profile editor</Link>{" "}
                  — they are parsed into an argv array, shell metacharacters are rejected,
                  and control-plane-owned flags cannot be overridden.
                </p>
              )}
              <div className={layout.grid2} style={{ gridTemplateColumns: "1fr 1fr" }}>
                <div className={layout.stack} style={{ gap: 4 }}>
                  <span className={layout.small}>Output format</span>
                  <code className={layout.monoPath}>json (locked — required by the runner)</code>
                </div>
                <div className={layout.stack} style={{ gap: 4 }}>
                  <span className={layout.small}>Audience</span>
                  <code className={layout.monoPath}>agent (locked — required by the runner)</code>
                </div>
              </div>
            </>
          ) : null}
        </section>

        {/* Command preview */}
        <CommandPreviewView preview={preview} />

        {submitError ? (
          <ErrorState title="Could not queue the review" error={submitError} />
        ) : null}

        <div className={layout.row} style={{ justifyContent: "flex-end" }}>
          <Button
            variant="secondary"
            disabled={!projectId || createJob.isPending}
            onClick={() => {
              const qs = new URLSearchParams({
                project: projectId,
                mode,
                base: baseRef ?? "",
                target: targetRef ?? "",
                commit: commitRef ?? "",
                profile: profileId,
                excludes: excludePatterns.join(","),
              });
              navigate(`/reviews/preview?${qs.toString()}`);
            }}
          >
            Preview files
          </Button>
          <Button
            variant="primary"
            type="submit"
            disabled={createJob.isPending || !projectId || (parsedArgs.error !== null)}
          >
            {createJob.isPending ? "Queueing…" : "Queue review"}
          </Button>
        </div>
      </form>
    </>
  );
}
