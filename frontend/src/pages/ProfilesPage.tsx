/**
 * Review profiles (SPEC §8, §20) — master-detail list + full editor with
 * capability-aware planning controls and a live command preview.
 */

import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useForm, Controller } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  useCreateProfile,
  useDeleteProfile,
  useDuplicateProfile,
  useModels,
  useProfile,
  useProfiles,
  useProviders,
  useSystemOcr,
  useUpdateProfile,
  type ProfileInput,
} from "../api/hooks";
import { PageHeader } from "../layouts/AppLayout";
import {
  Badge,
  Button,
  ConfirmDialog,
  ErrorState,
  Input,
  Select,
  Skeleton,
  Textarea,
  toast,
} from "../components/ui";
import { IconPlus } from "../components/ui/icons";
import { parseAdditionalArgs } from "../lib/args";
import { buildCommandPreview } from "../lib/command";
import { CommandPreviewView } from "../features/reviews/CommandPreview";
import layout from "../layouts/layout.module.css";
import styles from "./pages.module.css";

const schema = z.object({
  name: z.string().min(1, "Name is required."),
  description: z.string(),
  provider_profile_id: z.string(),
  model_id: z.string(),
  language: z.string(),
  concurrency: z.string(),
  per_file_timeout_minutes: z.string(),
  llm_http_timeout_seconds: z.string(),
  max_tools: z.string(),
  max_git_processes: z.string(),
  plan_mode: z.enum(["auto", "always", "never"]),
  plan_threshold_lines: z.string(),
  max_tokens: z.string(),
  template_path: z.string(),
  exclude_patterns: z.string(),
  rule_file_path: z.string(),
  tools_file_path: z.string(),
  background_template: z.string(),
  additional_arguments: z.string(),
});

type FormValues = z.infer<typeof schema>;

function toNumber(raw: string): number | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const n = Number.parseInt(trimmed, 10);
  return Number.isNaN(n) ? null : n;
}

function numField(
  label: string,
  error: string | undefined,
  props: React.InputHTMLAttributes<HTMLInputElement>,
  help?: string,
) {
  return (
    <Input
      label={label}
      type="number"
      inputMode="numeric"
      error={error}
      help={help}
      {...props}
    />
  );
}

function ProfileEditor({ profileId, onDeleted }: { profileId: string | null; onDeleted: () => void }) {
  const profile = useProfile(profileId ?? "");
  const providers = useProviders();
  const ocr = useSystemOcr();
  const createProfile = useCreateProfile();
  const updateProfile = useUpdateProfile();
  const deleteProfile = useDeleteProfile();
  const duplicateProfile = useDuplicateProfile();

  const [submitError, setSubmitError] = useState<unknown>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [argsError, setArgsError] = useState<string | null>(null);
  const [argsPreview, setArgsPreview] = useState<string[]>([]);

  const {
    register,
    control,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isDirty },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: "",
      description: "",
      provider_profile_id: "",
      model_id: "",
      language: "",
      concurrency: "",
      per_file_timeout_minutes: "",
      llm_http_timeout_seconds: "",
      max_tools: "",
      max_git_processes: "",
      plan_mode: "auto",
      plan_threshold_lines: "",
      max_tokens: "",
      template_path: "",
      exclude_patterns: "",
      rule_file_path: "",
      tools_file_path: "",
      background_template: "",
      additional_arguments: "",
    },
  });

  useEffect(() => {
    if (profileId && profile.data) {
      const p = profile.data;
      reset({
        name: p.name,
        description: p.description ?? "",
        provider_profile_id: p.provider_profile_id ?? "",
        model_id: p.model_id ?? "",
        language: p.language ?? "",
        concurrency: p.concurrency?.toString() ?? "",
        per_file_timeout_minutes: p.per_file_timeout_minutes?.toString() ?? "",
        llm_http_timeout_seconds: p.llm_http_timeout_seconds?.toString() ?? "",
        max_tools: p.max_tools?.toString() ?? "",
        max_git_processes: p.max_git_processes?.toString() ?? "",
        plan_mode: p.plan_mode,
        plan_threshold_lines: p.plan_threshold_lines?.toString() ?? "",
        max_tokens: p.max_tokens?.toString() ?? "",
        template_path: p.template_path ?? "",
        exclude_patterns: (p.exclude_patterns ?? []).join("\n"),
        rule_file_path: p.rule_file_path ?? "",
        tools_file_path: p.tools_file_path ?? "",
        background_template: p.background_template ?? "",
        additional_arguments: p.additional_arguments ?? "",
      });
    } else if (!profileId) {
      reset();
    }
  }, [profileId, profile.data, reset]);

  const providerId = watch("provider_profile_id");
  const models = useModels(providerId);

  const caps = ocr.data?.capabilities;
  const planningSupported = Boolean(caps?.plan_mode);
  const templateSupported = Boolean(caps?.template_override);
  const planningReason = planningSupported
    ? null
    : "Planning is automatic — the installed OCR binary controls its plan threshold internally. Install a patched OCR build to unlock these controls.";

  // Validate additional args live.
  const watchedArgs = watch("additional_arguments");
  useEffect(() => {
    const parsed = parseAdditionalArgs(watchedArgs ?? "");
    setArgsError(parsed.error);
    setArgsPreview(parsed.ok ? parsed.argv : []);
  }, [watchedArgs]);

  const watched = watch();
  const livePreview = useMemo(() => {
    const modelObj = (models.data ?? []).find((m) => m.id === watched.model_id);
    return buildCommandPreview(
      {
        mode: "range",
        repoPath: "<data-dir>/worktrees/<project>/<job>",
        baseRef: "main",
        targetRef: "feature/example",
        profile: {
          id: profileId ?? "",
          name: watched.name,
          description: watched.description || null,
          provider_profile_id: watched.provider_profile_id || null,
          model_id: watched.model_id || null,
          language: watched.language || null,
          concurrency: toNumber(watched.concurrency),
          per_file_timeout_minutes: toNumber(watched.per_file_timeout_minutes),
          llm_http_timeout_seconds: toNumber(watched.llm_http_timeout_seconds),
          max_tools: toNumber(watched.max_tools),
          max_git_processes: toNumber(watched.max_git_processes),
          plan_mode: watched.plan_mode,
          plan_threshold_lines: toNumber(watched.plan_threshold_lines),
          max_tokens: toNumber(watched.max_tokens),
          template_path: watched.template_path || null,
          exclude_patterns: watched.exclude_patterns
            .split("\n")
            .map((s) => s.trim())
            .filter(Boolean),
          rule_file_path: watched.rule_file_path || null,
          tools_file_path: watched.tools_file_path || null,
          background_template: watched.background_template || null,
          additional_arguments: watched.additional_arguments || null,
          created_at: "",
        },
        model: modelObj?.model_id ?? null,
        additionalArgs: argsError ? [] : argsPreview,
      },
      ocr.data,
    );
  }, [watched, models.data, ocr.data, argsError, argsPreview, profileId]);

  async function onSubmit(values: FormValues) {
    setSubmitError(null);
    const parsed = parseAdditionalArgs(values.additional_arguments);
    if (!parsed.ok) {
      setArgsError(parsed.error);
      return;
    }
    const payload: ProfileInput = {
      name: values.name.trim(),
      description: values.description.trim() || null,
      provider_profile_id: values.provider_profile_id || null,
      model_id: values.model_id || null,
      language: values.language.trim() || null,
      concurrency: toNumber(values.concurrency),
      per_file_timeout_minutes: toNumber(values.per_file_timeout_minutes),
      llm_http_timeout_seconds: toNumber(values.llm_http_timeout_seconds),
      max_tools: toNumber(values.max_tools),
      max_git_processes: toNumber(values.max_git_processes),
      plan_mode: values.plan_mode,
      plan_threshold_lines: planningSupported ? toNumber(values.plan_threshold_lines) : null,
      max_tokens: planningSupported ? toNumber(values.max_tokens) : null,
      template_path: templateSupported ? values.template_path.trim() || null : null,
      exclude_patterns: values.exclude_patterns
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
      rule_file_path: values.rule_file_path.trim() || null,
      tools_file_path: values.tools_file_path.trim() || null,
      background_template: values.background_template.trim() || null,
      additional_arguments: values.additional_arguments.trim() || null,
    };
    try {
      if (profileId) {
        await updateProfile.mutateAsync({ id: profileId, ...payload });
        toast.success("Profile saved");
      } else {
        const created = await createProfile.mutateAsync(payload);
        toast.success("Profile created");
        window.history.replaceState(null, "", `/profiles/${created.id}`);
      }
    } catch (err) {
      setSubmitError(err);
    }
  }

  if (profileId && profile.isLoading) {
    return (
      <div className={layout.stack}>
        <Skeleton height={32} width={260} />
        <Skeleton height={360} />
      </div>
    );
  }
  if (profileId && profile.error) {
    return <ErrorState title="Could not load profile" error={profile.error} />;
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className={`${layout.stack} ${layout.stackLg}`}>
      <section className={`${layout.section} ${layout.stack}`} aria-label="Profile basics">
        <div className={layout.sectionHeader} style={{ margin: 0 }}>
          <h2 className={layout.sectionTitle} style={{ margin: 0 }}>
            {profileId ? "Edit profile" : "New profile"}
          </h2>
          {profileId ? (
            <div className={layout.row}>
              <Button
                variant="tertiary"
                size="small"
                onClick={() =>
                  duplicateProfile.mutateAsync({ id: profileId }).then(
                    (copy) => toast.success(`Duplicated as “${copy.name}”`),
                    (err: Error) => toast.error("Duplicate failed", err.message),
                  )
                }
              >
                Duplicate
              </Button>
              <Button variant="destructive-quiet" size="small" onClick={() => setDeleteOpen(true)}>
                Delete
              </Button>
            </div>
          ) : null}
        </div>
        <div className={layout.grid2} style={{ gridTemplateColumns: "1fr 1fr" }}>
          <Input label="Name" required error={errors.name?.message} {...register("name")} />
          <Input label="Description" {...register("description")} />
        </div>
        <div className={layout.grid2} style={{ gridTemplateColumns: "1fr 1fr" }}>
          <Controller
            control={control}
            name="provider_profile_id"
            render={({ field }) => (
              <Select label="Provider" value={field.value} onChange={field.onChange}>
                <option value="">None (OCR default config)</option>
                {(providers.data ?? []).map((p) => (
                  <option key={p.id} value={p.id} disabled={!p.enabled}>
                    {p.name}
                    {!p.enabled ? " (disabled)" : ""}
                  </option>
                ))}
              </Select>
            )}
          />
          <Controller
            control={control}
            name="model_id"
            render={({ field }) => (
              <Select
                label="Model"
                value={field.value}
                onChange={field.onChange}
                help={providerId ? undefined : "Select a provider to pick a model."}
              >
                <option value="">Provider default</option>
                {(models.data ?? []).map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.display_name ?? m.model_id}
                    {m.is_manual ? " (manual)" : ""}
                  </option>
                ))}
              </Select>
            )}
          />
        </div>
        <Input
          label="Review language (optional)"
          placeholder="en"
          help="Language for OCR's review output."
          {...register("language")}
        />
      </section>

      <section className={`${layout.section} ${layout.stack}`} aria-label="Execution limits">
        <h2 className={layout.sectionTitle} style={{ margin: 0 }}>Execution limits</h2>
        <div className={layout.grid2} style={{ gridTemplateColumns: "1fr 1fr" }}>
          {numField("Concurrency (files in parallel)", errors.concurrency?.message, register("concurrency"), "1–64; OCR default when empty.")}
          {numField("Per-file timeout (minutes)", errors.per_file_timeout_minutes?.message, register("per_file_timeout_minutes"), "1–240.")}
          {numField("LLM HTTP timeout (seconds)", errors.llm_http_timeout_seconds?.message, register("llm_http_timeout_seconds"))}
          {numField("Max tools", errors.max_tools?.message, register("max_tools"), "1–200.")}
          {numField("Max Git processes", errors.max_git_processes?.message, register("max_git_processes"), "1–64.")}
        </div>
      </section>

      <section className={`${layout.section} ${layout.stack}`} aria-label="Planning">
        <h2 className={layout.sectionTitle} style={{ margin: 0 }}>Planning</h2>
        {planningReason ? (
          <p className={layout.small} role="note">
            {planningReason}
          </p>
        ) : null}
        <div className={layout.grid2} style={{ gridTemplateColumns: "1fr 1fr 1fr" }}>
          <Controller
            control={control}
            name="plan_mode"
            render={({ field }) => (
              <Select
                label="Plan mode"
                value={field.value}
                onChange={field.onChange}
                disabled={!planningSupported}
                help={planningSupported ? "auto uses the changed-lines threshold." : "Automatic (controlled by installed OCR)"}
              >
                <option value="auto">auto</option>
                <option value="always">always</option>
                <option value="never">never</option>
              </Select>
            )}
          />
          <Input
            label="Plan threshold (changed lines)"
            type="number"
            disabled={!planningSupported}
            {...register("plan_threshold_lines")}
          />
          <Input
            label="Max tokens"
            type="number"
            disabled={!planningSupported}
            {...register("max_tokens")}
          />
        </div>
        <Input
          label="Custom task template path (--template)"
          mono
          placeholder="templates/my-task-template.json"
          disabled={!templateSupported}
          help={
            templateSupported
              ? "Complete task template JSON; replaces the embedded template for jobs using this profile."
              : "Requires a patched OCR build that exposes --template."
          }
          {...register("template_path")}
        />
      </section>

      <section className={`${layout.section} ${layout.stack}`} aria-label="Files and rules">
        <h2 className={layout.sectionTitle} style={{ margin: 0 }}>Files, rules, and context</h2>
        <Textarea
          label="Exclude patterns (one per line)"
          rows={3}
          mono
          placeholder={"*.lock\ndist/**"}
          {...register("exclude_patterns")}
        />
        <div className={layout.grid2} style={{ gridTemplateColumns: "1fr 1fr" }}>
          <Input label="Rule file path" mono placeholder="rules/default.md" {...register("rule_file_path")} />
          <Input label="Tools configuration file" mono placeholder="tools.json" {...register("tools_file_path")} />
        </div>
        <Textarea
          label="Background context template (Markdown)"
          rows={4}
          placeholder="Review guidance prepended to every job using this profile…"
          {...register("background_template")}
        />
      </section>

      <section className={`${layout.section} ${layout.stack}`} aria-label="Advanced">
        <h2 className={layout.sectionTitle} style={{ margin: 0 }}>Advanced</h2>
        <div className={layout.grid2} style={{ gridTemplateColumns: "1fr 1fr" }}>
          <div>
            <span className={layout.small}>Output format</span>
            <div>
              <code className={layout.monoPath}>json</code>{" "}
              <Badge>locked</Badge>
            </div>
            <p className={layout.small}>Structured output is required by the runner.</p>
          </div>
          <div>
            <span className={layout.small}>Audience</span>
            <div>
              <code className={layout.monoPath}>agent</code>{" "}
              <Badge>locked</Badge>
            </div>
            <p className={layout.small}>Quiet, machine-readable reviews.</p>
          </div>
        </div>
        <Textarea
          label="Additional OCR arguments (expert)"
          rows={2}
          mono
          placeholder="--some-flag value"
          error={argsError}
          help="Parsed into an argv array. Shell metacharacters and control-plane-owned flags are rejected. Jobs using custom arguments are marked."
          {...register("additional_arguments")}
        />
        {argsPreview.length > 0 ? (
          <div>
            <span className={layout.small}>Parsed arguments</span>
            <pre className={layout.monoPath} style={{ fontSize: 12, background: "var(--code-bg)", borderRadius: 6, padding: 8, margin: "4px 0 0" }}>
              {argsPreview.join("\n")}
            </pre>
          </div>
        ) : null}
      </section>

      <CommandPreviewView preview={livePreview} title="Live command preview (example refs)" />

      {submitError ? <ErrorState title="Could not save profile" error={submitError} /> : null}

      <div className={layout.row} style={{ justifyContent: "flex-end" }}>
        <Button
          variant="primary"
          type="submit"
          disabled={
            createProfile.isPending ||
            updateProfile.isPending ||
            Boolean(argsError) ||
            (Boolean(profileId) && !isDirty)
          }
        >
          {createProfile.isPending || updateProfile.isPending
            ? "Saving…"
            : profileId
              ? "Save profile"
              : "Create profile"}
        </Button>
      </div>

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title="Delete profile"
        description="Delete this review profile? Existing jobs keep their recorded configuration snapshots."
        confirmLabel="Delete profile"
        destructive
        busy={deleteProfile.isPending}
        onConfirm={async () => {
          if (!profileId) return;
          try {
            await deleteProfile.mutateAsync(profileId);
            toast.success("Profile deleted");
            setDeleteOpen(false);
            onDeleted();
          } catch (err) {
            toast.error("Delete failed", err instanceof Error ? err.message : undefined);
          }
        }}
      />
    </form>
  );
}

export function ProfilesPage() {
  const { profileId } = useParams();
  const navigate = useNavigate();
  const profiles = useProfiles();
  const [selected, setSelected] = useState<string | null>(profileId ?? null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    setSelected(profileId ?? null);
    setCreating(false);
  }, [profileId]);

  const list = profiles.data ?? [];
  const effectiveSelected = creating ? null : (selected ?? list[0]?.id ?? null);

  return (
    <>
      <PageHeader
        title="Review profiles"
        subtitle="Reusable OCR configurations — provider, model, limits, planning, rules."
        actions={
          <Button
            variant="primary"
            onClick={() => {
              setCreating(true);
              setSelected(null);
              navigate("/profiles");
            }}
          >
            <IconPlus size={14} /> New profile
          </Button>
        }
      />

      <div className={styles.masterDetail}>
        <div className={styles.masterList} role="listbox" aria-label="Profiles">
          {list.length === 0 && !creating ? (
            <p className={layout.small} style={{ padding: 16 }}>
              No profiles yet.
            </p>
          ) : null}
          {creating ? (
            <div className={`${styles.masterItem} ${styles.masterItemActive}`} aria-selected="true">
              <span style={{ fontWeight: 500 }}>New profile…</span>
            </div>
          ) : null}
          {list.map((p) => (
            <button
              key={p.id}
              type="button"
              role="option"
              aria-selected={p.id === effectiveSelected}
              className={`${styles.masterItem} ${p.id === effectiveSelected && !creating ? styles.masterItemActive : ""}`}
              onClick={() => {
                setCreating(false);
                setSelected(p.id);
                navigate(`/profiles/${p.id}`);
              }}
            >
              <span style={{ fontWeight: 500 }}>{p.name}</span>
              <span className={layout.small}>
                {p.description ??
                  `plan ${p.plan_mode} · concurrency ${p.concurrency ?? "default"}`}
              </span>
            </button>
          ))}
        </div>
        <div>
          {creating || effectiveSelected ? (
            <ProfileEditor
              profileId={creating ? null : effectiveSelected}
              onDeleted={() => navigate("/profiles")}
            />
          ) : (
            <div className={layout.section}>
              <p className={layout.muted}>
                Create a profile to start configuring review behavior.
              </p>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
