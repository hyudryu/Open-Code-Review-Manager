/**
 * Provider editor (SPEC §9, §33.14) — preset picker + full custom provider,
 * credential entry into SecretStore, extra headers/body JSON, structured
 * connection test, model discovery + manual models.
 */

import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useForm, Controller } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  useAddModel,
  useCreateProvider,
  useDeleteProvider,
  useDiscoverModels,
  useModels,
  useProvider,
  useRemoveModel,
  useTestProvider,
  useUpdateProvider,
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
  Switch,
  Textarea,
  toast,
} from "../components/ui";
import type { ProviderTestResult } from "../types";
import { formatProviderTestSuccess } from "../lib/mcp";
import layout from "../layouts/layout.module.css";

interface Preset {
  key: string;
  label: string;
  provider_type: string;
  protocol: "openai" | "openai-responses" | "anthropic";
  base_url: string;
  discovery: "auto" | "manual";
}

const PRESETS: Preset[] = [
  { key: "anthropic", label: "Anthropic", provider_type: "anthropic", protocol: "anthropic", base_url: "https://api.anthropic.com", discovery: "manual" },
  { key: "openai", label: "OpenAI", provider_type: "openai", protocol: "openai", base_url: "https://api.openai.com/v1", discovery: "auto" },
  { key: "dashscope", label: "DashScope", provider_type: "dashscope", protocol: "openai", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", discovery: "auto" },
  { key: "deepseek", label: "DeepSeek", provider_type: "deepseek", protocol: "openai", base_url: "https://api.deepseek.com/v1", discovery: "auto" },
  { key: "kimi", label: "Kimi", provider_type: "kimi", protocol: "openai", base_url: "https://api.moonshot.cn/v1", discovery: "auto" },
  { key: "minimax", label: "MiniMax", provider_type: "minimax", protocol: "openai", base_url: "https://api.minimax.chat/v1", discovery: "auto" },
  { key: "zai", label: "Z.ai", provider_type: "zai", protocol: "openai", base_url: "https://api.z.ai/api/paas/v4", discovery: "auto" },
  { key: "volcengine", label: "Volcengine", provider_type: "volcengine", protocol: "openai", base_url: "https://ark.cn-beijing.volces.com/api/v3", discovery: "auto" },
  { key: "tencent", label: "Tencent", provider_type: "tencent", protocol: "openai", base_url: "https://api.hunyuan.cloud.tencent.com/v1", discovery: "auto" },
  { key: "qianfan", label: "Baidu Qianfan", provider_type: "qianfan", protocol: "openai", base_url: "https://qianfan.baidubce.com/v2", discovery: "auto" },
  { key: "local-openai", label: "Local OpenAI-compatible", provider_type: "local", protocol: "openai", base_url: "http://127.0.0.1:8000/v1", discovery: "auto" },
  { key: "custom-anthropic", label: "Custom Anthropic-compatible", provider_type: "custom", protocol: "anthropic", base_url: "", discovery: "manual" },
  { key: "custom-responses", label: "Custom OpenAI Responses-compatible", provider_type: "custom", protocol: "openai-responses", base_url: "", discovery: "auto" },
];

const schema = z.object({
  name: z.string().min(1, "Name is required."),
  protocol: z.enum(["openai", "openai-responses", "anthropic"]),
  base_url: z.string(),
  credential: z.string(),
  auth_header: z.string(),
  http_timeout_seconds: z.coerce.number().int().min(1).max(3600),
  extra_headers: z.string(),
  extra_body: z.string(),
  model_discovery_mode: z.enum(["auto", "manual", "adapter"]),
  enabled: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

function parseJsonField(
  raw: string,
  label: string,
): { value: Record<string, unknown> | null; error: string | null } {
  if (!raw.trim()) return { value: null, error: null };
  try {
    const parsed: unknown = JSON.parse(raw);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { value: null, error: `${label} must be a JSON object.` };
    }
    return { value: parsed as Record<string, unknown>, error: null };
  } catch {
    return { value: null, error: `${label} is not valid JSON.` };
  }
}

export function ProviderEditorPage() {
  const { providerId } = useParams();
  const isNew = !providerId;
  const navigate = useNavigate();

  const existing = useProvider(providerId ?? "");
  const models = useModels(providerId ?? "");
  const createProvider = useCreateProvider();
  const updateProvider = useUpdateProvider();
  const deleteProvider = useDeleteProvider();
  const testProvider = useTestProvider();
  const discover = useDiscoverModels();
  const addModel = useAddModel();
  const removeModel = useRemoveModel();

  const [presetKey, setPresetKey] = useState("openai");
  const [testResult, setTestResult] = useState<ProviderTestResult | null>(null);
  const [testModel, setTestModel] = useState("");
  const [submitError, setSubmitError] = useState<unknown>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [newModelId, setNewModelId] = useState("");
  const [newModelName, setNewModelName] = useState("");
  const [jsonErrors, setJsonErrors] = useState<{ headers: string | null; body: string | null }>({
    headers: null,
    body: null,
  });

  const {
    register,
    control,
    handleSubmit,
    reset,
    setValue,
    watch,
    formState: { errors, isDirty },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: "",
      protocol: "openai",
      base_url: "",
      credential: "",
      auth_header: "",
      http_timeout_seconds: 600,
      extra_headers: "",
      extra_body: "",
      model_discovery_mode: "auto",
      enabled: true,
    },
  });

  useEffect(() => {
    if (existing.data) {
      const p = existing.data;
      reset({
        name: p.name,
        protocol: p.protocol,
        base_url: p.base_url,
        credential: "",
        auth_header: p.auth_header ?? "",
        http_timeout_seconds: p.http_timeout_seconds,
        extra_headers: "",
        extra_body: "",
        model_discovery_mode: p.model_discovery_mode,
        enabled: p.enabled,
      });
    }
  }, [existing.data, reset]);

  function applyPreset(key: string) {
    setPresetKey(key);
    const preset = PRESETS.find((p) => p.key === key);
    if (!preset) return;
    setValue("name", preset.label, { shouldDirty: true });
    setValue("protocol", preset.protocol, { shouldDirty: true });
    setValue("base_url", preset.base_url, { shouldDirty: true });
    setValue("model_discovery_mode", preset.discovery, { shouldDirty: true });
  }

  const hasCredential = existing.data?.has_credential ?? false;
  const watchProtocol = watch("protocol");

  async function onSubmit(values: FormValues) {
    setSubmitError(null);
    const headers = parseJsonField(values.extra_headers, "Extra headers");
    const body = parseJsonField(values.extra_body, "Extra body");
    setJsonErrors({ headers: headers.error, body: body.error });
    if (headers.error || body.error) return;

    const preset = PRESETS.find((p) => p.key === presetKey);
    const payload = {
      name: values.name.trim(),
      provider_type: isNew ? (preset?.provider_type ?? "custom") : undefined,
      protocol: values.protocol,
      base_url: values.base_url.trim(),
      credential: values.credential.trim() ? values.credential.trim() : undefined,
      auth_header: values.auth_header.trim() || null,
      http_timeout_seconds: values.http_timeout_seconds,
      extra_headers: headers.value as Record<string, string> | null,
      extra_body: body.value,
      model_discovery_mode: values.model_discovery_mode,
      enabled: values.enabled,
    };

    try {
      if (isNew) {
        const created = await createProvider.mutateAsync(payload);
        toast.success("Provider saved", "Credential stored in the OS credential store.");
        navigate(`/providers/${created.id}`, { replace: true });
      } else if (providerId) {
        await updateProvider.mutateAsync({ id: providerId, ...payload });
        toast.success("Provider updated");
      }
    } catch (err) {
      setSubmitError(err);
    }
  }

  async function runTest() {
    if (!providerId) return;
    setTestResult(null);
    try {
      const result = await testProvider.mutateAsync({
        id: providerId,
        modelId: testModel || undefined,
      });
      setTestResult(result);
    } catch (err) {
      setTestResult({
        ok: false,
        status: "failed",
        exit_code: null,
        elapsed_ms: null,
        stdout: "",
        stderr: "",
        message: err instanceof Error ? err.message : "Test failed",
      });
    }
  }

  if (!isNew && existing.isLoading) {
    return (
      <div className={layout.stack}>
        <Skeleton height={36} width={320} />
        <Skeleton height={300} />
      </div>
    );
  }

  if (!isNew && existing.error) {
    return <ErrorState title="Could not load provider" error={existing.error} />;
  }

  const modelList = models.data ?? [];

  return (
    <>
      <PageHeader
        title={isNew ? "Add provider" : (existing.data?.name ?? "Provider")}
        subtitle={
          isNew
            ? "Pick a preset or configure a fully custom endpoint."
            : "Endpoint, credential, and model configuration."
        }
        actions={
          !isNew ? (
            <Button variant="destructive-quiet" onClick={() => setDeleteOpen(true)}>
              Delete provider
            </Button>
          ) : undefined
        }
      />

      <form onSubmit={handleSubmit(onSubmit)} className={`${layout.stack} ${layout.stackLg}`} style={{ maxWidth: 760 }}>
        {isNew ? (
          <section className={`${layout.section} ${layout.stack}`} aria-label="Preset">
            <Select
              label="Start from a preset"
              value={presetKey}
              onChange={(e) => applyPreset(e.target.value)}
              help="Presets fill in the protocol and endpoint — everything stays editable."
            >
              {PRESETS.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label}
                </option>
              ))}
            </Select>
          </section>
        ) : null}

        <section className={`${layout.section} ${layout.stack}`} aria-label="Connection">
          <div className={layout.grid2} style={{ gridTemplateColumns: "1fr 1fr" }}>
            <Input
              label="Name"
              required
              error={errors.name?.message}
              {...register("name")}
            />
            <Controller
              control={control}
              name="protocol"
              render={({ field }) => (
                <Select label="Protocol" value={field.value} onChange={field.onChange} required>
                  <option value="openai">openai (chat completions)</option>
                  <option value="openai-responses">openai-responses</option>
                  <option value="anthropic">anthropic</option>
                </Select>
              )}
            />
          </div>
          <Input
            label="Base URL"
            placeholder="https://api.example.com/v1"
            mono
            help="The endpoint OCR sends requests to."
            {...register("base_url")}
          />
          <Input
            label={hasCredential ? "API key (saved — enter a new one to rotate)" : "API key / token"}
            type="password"
            autoComplete="off"
            placeholder={hasCredential ? "••••••••••••••••" : "sk-…"}
            help="Written to the OS credential store (Windows Credential Manager / Keychain / Secret Service). It is never stored in the database or shown again."
            {...register("credential")}
          />
          <div className={layout.grid2} style={{ gridTemplateColumns: "1fr 1fr" }}>
            <Input
              label="Auth header override (optional)"
              placeholder="Authorization"
              mono
              help="Defaults to the protocol's standard header."
              {...register("auth_header")}
            />
            <Input
              label="HTTP timeout (seconds)"
              type="number"
              min={1}
              max={3600}
              error={errors.http_timeout_seconds?.message}
              {...register("http_timeout_seconds")}
            />
          </div>
          <Textarea
            label="Extra headers (JSON object, optional)"
            rows={2}
            mono
            placeholder='{"X-Custom-Header": "value"}'
            error={jsonErrors.headers}
            {...register("extra_headers")}
          />
          <Textarea
            label="Extra request body fields (JSON object, optional)"
            rows={2}
            mono
            placeholder='{"organization": "…"}'
            error={jsonErrors.body}
            {...register("extra_body")}
          />
          <div className={layout.grid2} style={{ gridTemplateColumns: "1fr 1fr", alignItems: "center" }}>
            <Controller
              control={control}
              name="model_discovery_mode"
              render={({ field }) => (
                <Select
                  label="Model discovery"
                  value={field.value}
                  onChange={field.onChange}
                  help={
                    watchProtocol === "anthropic"
                      ? "Anthropic has no /models endpoint — add models manually."
                      : "Auto uses GET {base_url}/models."
                  }
                >
                  <option value="auto">Auto (GET /models)</option>
                  <option value="manual">Manual entry</option>
                  <option value="adapter">Provider adapter</option>
                </Select>
              )}
            />
            <Controller
              control={control}
              name="enabled"
              render={({ field }) => (
                <div className={layout.row} style={{ justifyContent: "space-between", paddingTop: 18 }}>
                  <span style={{ font: "var(--text-label)", color: "var(--text-secondary)" }}>
                    Enabled
                  </span>
                  <Switch checked={field.value} onCheckedChange={field.onChange} aria-label="Provider enabled" />
                </div>
              )}
            />
          </div>
          {submitError ? <ErrorState title="Could not save provider" error={submitError} /> : null}
          <div className={layout.row} style={{ justifyContent: "flex-end" }}>
            <Button
              variant="primary"
              type="submit"
              disabled={createProvider.isPending || updateProvider.isPending || (!isNew && !isDirty)}
            >
              {createProvider.isPending || updateProvider.isPending
                ? "Saving…"
                : isNew
                  ? "Create provider"
                  : "Save changes"}
            </Button>
          </div>
        </section>
      </form>

      {!isNew && providerId ? (
        <div className={`${layout.stack} ${layout.stackLg}`} style={{ maxWidth: 760, marginTop: 24 }}>
          {/* Connection test */}
          <section className={`${layout.section} ${layout.stack}`} aria-label="Connection test">
            <h2 className={layout.sectionTitle} style={{ margin: 0 }}>Connection test</h2>
            <p className={layout.small}>
              Sends a real minimal request to the configured endpoint asking the model to
              reply. No LLM config is written; your key is never logged or displayed.
            </p>
            <div className={layout.row} style={{ alignItems: "center" }}>
              <Select
                aria-label="Model to test with"
                value={testModel}
                onChange={(e) => setTestModel(e.target.value)}
              >
                <option value="">Select a model…</option>
                {modelList.map((m) => (
                  <option key={m.id} value={m.model_id}>
                    {m.display_name ?? m.model_id}
                  </option>
                ))}
              </Select>
              <Button
                variant="secondary"
                onClick={runTest}
                disabled={testProvider.isPending || !testModel}
              >
                {testProvider.isPending ? "Testing…" : "Test connection"}
              </Button>
            </div>
            {modelList.length === 0 ? (
              <p className={layout.small} style={{ margin: 0 }}>
                Add or discover a model first — the test sends a real request with the
                selected model.
              </p>
            ) : null}
            {testResult ? (
              <div
                className={layout.stack}
                style={{
                  gap: 6,
                  border: `1px solid ${testResult.ok ? "var(--success)" : "var(--danger)"}`,
                  borderRadius: 8,
                  padding: 12,
                }}
                role="status"
              >
                <span style={{ font: "var(--text-label)", fontSize: 13, color: testResult.ok ? "var(--success)" : "var(--danger)" }}>
                  {testResult.ok
                    ? formatProviderTestSuccess(testResult)
                    : (testResult.message ?? "Connection failed")}
                </span>
                {testResult.detail ? (
                  <span className={layout.small}>{testResult.detail}</span>
                ) : null}
                {testResult.next_action ? (
                  <span className={layout.small}>Next: {testResult.next_action}</span>
                ) : null}
                {testResult.exit_code != null ? (
                  <span className={layout.small}>exit code {testResult.exit_code}</span>
                ) : null}
                {testResult.stderr ? (
                  <details>
                    <summary className={layout.small} style={{ cursor: "pointer" }}>stderr</summary>
                    <pre className={layout.monoPath} style={{ fontSize: 11.5, whiteSpace: "pre-wrap", marginTop: 4 }}>
                      {testResult.stderr}
                    </pre>
                  </details>
                ) : null}
              </div>
            ) : null}
          </section>

          {/* Models */}
          <section className={`${layout.section} ${layout.stack}`} aria-label="Models">
            <div className={layout.sectionHeader} style={{ margin: 0 }}>
              <h2 className={layout.sectionTitle} style={{ margin: 0 }}>
                Models ({modelList.length})
              </h2>
              <Button
                variant="secondary"
                size="small"
                disabled={discover.isPending}
                onClick={() =>
                  discover.mutateAsync(providerId).then(
                    (list) => toast.success(`Discovered ${list.length} models`),
                    (err: Error) => toast.error("Discovery failed", err.message),
                  )
                }
              >
                {discover.isPending ? "Discovering…" : "Discover models"}
              </Button>
            </div>
            {existing.data?.last_discovery_error ? (
              <p className={layout.small} style={{ color: "var(--danger)" }}>
                Last discovery failed: {existing.data.last_discovery_error}
              </p>
            ) : null}
            {modelList.length === 0 ? (
              <p className={layout.small}>No models yet — discover or add one manually.</p>
            ) : (
              <ul className={layout.stack} style={{ gap: 2 }}>
                {modelList.map((m) => (
                  <li key={m.id} className={layout.row} style={{ justifyContent: "space-between" }}>
                    <span className={layout.row} style={{ gap: 8 }}>
                      <code className={layout.monoPath} style={{ fontSize: 12.5 }}>
                        {m.display_name ?? m.model_id}
                      </code>
                      {m.is_manual ? <Badge>manual</Badge> : null}
                      {m.context_length ? (
                        <span className={layout.small}>{Math.round(m.context_length / 1000)}k ctx</span>
                      ) : null}
                    </span>
                    <Button
                      variant="tertiary"
                      size="small"
                      onClick={() =>
                        removeModel.mutateAsync({ providerId, modelPk: m.id }).catch((err: Error) =>
                          toast.error("Remove failed", err.message),
                        )
                      }
                    >
                      Remove
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            <div className={layout.row} style={{ borderTop: "1px solid var(--border-subtle)", paddingTop: 12 }}>
              <Input
                label="Add model manually"
                placeholder="model-id"
                value={newModelId}
                onChange={(e) => setNewModelId(e.target.value)}
              />
              <Input
                label="Display name (optional)"
                value={newModelName}
                onChange={(e) => setNewModelName(e.target.value)}
              />
              <Button
                variant="secondary"
                style={{ marginTop: 20 }}
                disabled={!newModelId.trim() || addModel.isPending}
                onClick={() =>
                  addModel
                    .mutateAsync({
                      providerId,
                      model_id: newModelId.trim(),
                      display_name: newModelName.trim() || undefined,
                    })
                    .then(() => {
                      setNewModelId("");
                      setNewModelName("");
                    })
                    .catch((err: Error) => toast.error("Could not add model", err.message))
                }
              >
                Add model
              </Button>
            </div>
          </section>
        </div>
      ) : null}

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title="Delete provider"
        description="Delete this provider and its credential reference? Profiles that reference it keep their settings but will need a new provider."
        confirmLabel="Delete provider"
        destructive
        busy={deleteProvider.isPending}
        onConfirm={async () => {
          if (!providerId) return;
          try {
            await deleteProvider.mutateAsync(providerId);
            toast.success("Provider deleted");
            navigate("/providers");
          } catch (err) {
            toast.error("Delete failed", err instanceof Error ? err.message : undefined);
          }
        }}
      />
    </>
  );
}
