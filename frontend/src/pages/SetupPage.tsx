/** First-run setup wizard (SPEC §34) — detect → add project → provider → profile → done. */

import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  useCreateProfile,
  useCreateProject,
  useCreateProvider,
  useModels,
  useProviders,
  useProjects,
  useReprobeOcr,
  useSystemInfo,
  useSystemOcr,
  useTestProvider,
} from "../api/hooks";
import { useUiStore } from "../hooks/store";
import {
  Button,
  ErrorState,
  FolderSelector,
  Input,
  Select,
  StatusDot,
  toast,
} from "../components/ui";
import { IconCheck } from "../components/ui/icons";
import type { ProviderTestResult } from "../types";
import layout from "../layouts/layout.module.css";
import styles from "./pages.module.css";

const STEPS = ["Environment", "Project", "Provider", "Profile", "Done"] as const;

function StepIndicator({ current }: { current: number }) {
  return (
    <ol className={styles.wizardSteps} aria-label="Setup progress">
      {STEPS.map((label, i) => (
        <li
          key={label}
          className={[
            styles.wizardStep,
            i === current ? styles.wizardStepActive : "",
            i < current ? styles.wizardStepDone : "",
          ]
            .filter(Boolean)
            .join(" ")}
          aria-current={i === current ? "step" : undefined}
        >
          <span className={styles.wizardStepDot}>
            {i < current ? <IconCheck size={11} /> : i + 1}
          </span>
          {label}
        </li>
      ))}
    </ol>
  );
}

export function SetupPage() {
  const navigate = useNavigate();
  const dismissSetup = useUiStore((s) => s.dismissSetup);

  const info = useSystemInfo();
  const ocr = useSystemOcr();
  const reprobe = useReprobeOcr();
  const projects = useProjects();
  const providers = useProviders();

  const createProject = useCreateProject();
  const createProvider = useCreateProvider();
  const createProfile = useCreateProfile();
  const testProvider = useTestProvider();

  const [step, setStep] = useState(0);

  // Project step
  const [projectPath, setProjectPath] = useState("");
  const [projectError, setProjectError] = useState<unknown>(null);
  const [addedProjectId, setAddedProjectId] = useState<string | null>(null);

  // Provider step
  const [providerName, setProviderName] = useState("");
  const [providerProtocol, setProviderProtocol] = useState<"openai" | "openai-responses" | "anthropic">("openai");
  const [providerUrl, setProviderUrl] = useState("https://api.openai.com/v1");
  const [credential, setCredential] = useState("");
  const [providerError, setProviderError] = useState<unknown>(null);
  const [addedProviderId, setAddedProviderId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<ProviderTestResult | null>(null);

  // Profile step
  const [profileName, setProfileName] = useState("Default profile");
  const [profileModel, setProfileModel] = useState("");
  const [profileError, setProfileError] = useState<unknown>(null);

  const models = useModels(addedProviderId ?? "");
  const hasProject = Boolean(addedProjectId) || (projects.data?.length ?? 0) > 0;
  const hasProvider = Boolean(addedProviderId) || (providers.data?.length ?? 0) > 0;

  const gitOk = Boolean(info.data?.git_version);
  const ocrOk = ocr.data?.status === "ok";

  const effectiveProviderId = useMemo(
    () => addedProviderId ?? providers.data?.[0]?.id ?? null,
    [addedProviderId, providers.data],
  );

  async function addProject() {
    setProjectError(null);
    try {
      const project = await createProject.mutateAsync({ absolute_path: projectPath.trim() });
      setAddedProjectId(project.id);
      toast.success(`Added ${project.display_name}`);
      setStep(2);
    } catch (err) {
      setProjectError(err);
    }
  }

  async function addProvider() {
    setProviderError(null);
    try {
      const provider = await createProvider.mutateAsync({
        name: providerName.trim() || "Provider",
        protocol: providerProtocol,
        base_url: providerUrl.trim(),
        credential: credential.trim() || undefined,
        model_discovery_mode: providerProtocol === "anthropic" ? "manual" : "auto",
      });
      setAddedProviderId(provider.id);
      toast.success("Provider saved — credential stored securely");
      setStep(3);
    } catch (err) {
      setProviderError(err);
    }
  }

  async function runProviderTest() {
    if (!addedProviderId) return;
    setTestResult(null);
    try {
      const result = await testProvider.mutateAsync({ id: addedProviderId });
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

  async function addProfile() {
    setProfileError(null);
    try {
      await createProfile.mutateAsync({
        name: profileName.trim() || "Default profile",
        provider_profile_id: effectiveProviderId,
        model_id: profileModel || null,
      });
      toast.success("Profile created");
      setStep(4);
    } catch (err) {
      setProfileError(err);
    }
  }

  function finish() {
    dismissSetup();
    navigate("/");
  }

  return (
    <div className={styles.wizard}>
      <h1 className={layout.pageTitle} style={{ marginBottom: 4 }}>
        Welcome to OCR Manager
      </h1>
      <p className={layout.muted} style={{ marginBottom: 24 }}>
        A short guided setup — environment, one project, one provider, one profile.
      </p>
      <StepIndicator current={step} />

      {step === 0 ? (
        <section className={`${layout.section} ${layout.stack}`} aria-label="Environment check">
          <h2 className={layout.sectionTitle} style={{ margin: 0 }}>Environment check</h2>
          <div className={layout.stack} style={{ gap: 8 }}>
            <div className={layout.row} style={{ justifyContent: "space-between" }}>
              <span>Git</span>
              <StatusDot
                tone={gitOk ? "ok" : "danger"}
                label={info.data?.git_version ?? "not detected"}
              />
            </div>
            <div className={layout.row} style={{ justifyContent: "space-between" }}>
              <span>OpenCodeReview</span>
              <StatusDot
                tone={ocrOk ? "ok" : "warn"}
                label={
                  ocr.data
                    ? ocrOk
                      ? `${ocr.data.version ?? "detected"} at ${ocr.data.binary_path}`
                      : "not found — jobs cannot run until installed"
                    : "checking…"
                }
              />
            </div>
          </div>
          {!ocrOk ? (
            <p className={layout.small}>
              You can continue and set the OCR path later in{" "}
              <strong>Settings → OCR Installation</strong>. Review jobs will fail until a
              compatible binary is detected.
            </p>
          ) : null}
          <div className={layout.row} style={{ justifyContent: "space-between" }}>
            <Button
              variant="tertiary"
              size="small"
              disabled={reprobe.isPending}
              onClick={() => reprobe.mutate()}
            >
              Re-detect
            </Button>
            <Button variant="primary" onClick={() => setStep(1)} disabled={!gitOk}>
              Continue
            </Button>
          </div>
          {!gitOk && info.data ? (
            <p className={layout.small} style={{ color: "var(--danger)" }}>
              Git is required — install Git and restart the backend.
            </p>
          ) : null}
        </section>
      ) : null}

      {step === 1 ? (
        <section className={`${layout.section} ${layout.stack}`} aria-label="Add a project">
          <h2 className={layout.sectionTitle} style={{ margin: 0 }}>Add your first project</h2>
          <p className={layout.small}>
            Point at any Git repository. You can add whole folders of repositories later
            from the Projects page.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
            <label style={{ font: "var(--text-label)", color: "var(--text-secondary)", display: "block" }} htmlFor="setup-path">
              Repository path <span style={{ color: "var(--danger)" }}>*</span>
            </label>
            <div className={layout.row} style={{ gap: 8, marginTop: 4 }}>
              <input
                id="setup-path"
                className={styles.input}
                value={projectPath}
                onChange={(e) => setProjectPath(e.target.value)}
                placeholder="C:\code\my-project"
                style={{ flex: 1, font: "var(--text-code)", height: 32, padding: "0 12px", border: "1px solid var(--border-strong)", borderRadius: 8, background: "var(--bg-surface)", color: "var(--text-primary)" }}
                required
              />
              <FolderSelector label="Select folder" onSelect={(p) => setProjectPath(p)} />
            </div>
            <p style={{ font: "var(--text-small)", color: "var(--text-tertiary)" }}>Absolute path to a Git repository.</p>
          </div>
          {projectError ? <ErrorState title="Could not add project" error={projectError} /> : null}
          <div className={layout.row} style={{ justifyContent: "space-between" }}>
            <Button variant="tertiary" onClick={() => setStep(2)}>
              Skip for now
            </Button>
            <Button
              variant="primary"
              onClick={addProject}
              disabled={!projectPath.trim() || createProject.isPending}
            >
              {createProject.isPending ? "Validating…" : "Add project"}
            </Button>
          </div>
        </section>
      ) : null}

      {step === 2 ? (
        <section className={`${layout.section} ${layout.stack}`} aria-label="Configure a provider">
          <h2 className={layout.sectionTitle} style={{ margin: 0 }}>Configure a provider</h2>
          <div className={layout.grid2} style={{ gridTemplateColumns: "1fr 1fr" }}>
            <Input
              label="Name"
              value={providerName}
              onChange={(e) => setProviderName(e.target.value)}
              placeholder="OpenAI"
            />
            <Select
              label="Protocol"
              value={providerProtocol}
              onChange={(e) => {
                const proto = e.target.value as typeof providerProtocol;
                setProviderProtocol(proto);
                if (proto === "anthropic") setProviderUrl("https://api.anthropic.com");
                else setProviderUrl("https://api.openai.com/v1");
              }}
            >
              <option value="openai">openai</option>
              <option value="openai-responses">openai-responses</option>
              <option value="anthropic">anthropic</option>
            </Select>
          </div>
          <Input
            label="Base URL"
            value={providerUrl}
            onChange={(e) => setProviderUrl(e.target.value)}
            mono
          />
          <Input
            label="API key"
            type="password"
            autoComplete="off"
            value={credential}
            onChange={(e) => setCredential(e.target.value)}
            help="Stored in the OS credential store — never in the database."
          />
          {providerError ? <ErrorState title="Could not save provider" error={providerError} /> : null}
          {testResult ? (
            <p className={layout.small} style={{ color: testResult.ok ? "var(--success)" : "var(--danger)" }} role="status">
              {testResult.ok
                ? `Connection successful${testResult.elapsed_ms != null ? ` in ${Math.round(testResult.elapsed_ms)} ms` : ""}.`
                : `Test failed: ${testResult.message ?? "see provider page for details"}`}
            </p>
          ) : null}
          <div className={layout.row} style={{ justifyContent: "space-between" }}>
            <div className={layout.row}>
              <Button variant="tertiary" onClick={() => setStep(3)}>
                Skip for now
              </Button>
              {addedProviderId ? (
                <Button variant="secondary" onClick={runProviderTest} disabled={testProvider.isPending}>
                  {testProvider.isPending ? "Testing…" : "Test connection"}
                </Button>
              ) : null}
            </div>
            {addedProviderId ? (
              <Button variant="primary" onClick={() => setStep(3)}>
                Continue
              </Button>
            ) : (
              <Button
                variant="primary"
                onClick={addProvider}
                disabled={createProvider.isPending}
              >
                {createProvider.isPending ? "Saving…" : "Save provider"}
              </Button>
            )}
          </div>
        </section>
      ) : null}

      {step === 3 ? (
        <section className={`${layout.section} ${layout.stack}`} aria-label="Create a profile">
          <h2 className={layout.sectionTitle} style={{ margin: 0 }}>Create a default profile</h2>
          <Input
            label="Profile name"
            value={profileName}
            onChange={(e) => setProfileName(e.target.value)}
            help="The name of this review profile."
          />
          <details className={layout.stack}>
            <summary
              style={{
                cursor: "pointer",
                font: "var(--text-label)",
                fontSize: 13,
                color: "var(--text-secondary)",
                userSelect: "none",
              }}
            >
              Advanced options
            </summary>
            <Select
              label="Model (optional)"
              value={profileModel}
              onChange={(e) => setProfileModel(e.target.value)}
              help={
                models.data?.length
                  ? undefined
                  : "No models discovered yet — you can discover or add them on the provider page."
              }
            >
              <option value="">Provider default</option>
              {(models.data ?? []).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.display_name ?? m.model_id}
                </option>
              ))}
            </Select>
          </details>
          {profileError ? <ErrorState title="Could not create profile" error={profileError} /> : null}
          <div className={layout.row} style={{ justifyContent: "space-between" }}>
            <Button variant="tertiary" onClick={() => setStep(4)}>
              Skip for now
            </Button>
            <Button variant="primary" onClick={addProfile} disabled={createProfile.isPending}>
              {createProfile.isPending ? "Creating…" : "Create profile"}
            </Button>
          </div>
        </section>
      ) : null}

      {step === 4 ? (
        <section className={`${layout.section} ${layout.stack}`} aria-label="Setup complete">
          <h2 className={layout.sectionTitle} style={{ margin: 0 }}>You're set up</h2>
          <ul className={layout.stack} style={{ gap: 6 }}>
            <li className={layout.row}>
              <StatusDot tone={gitOk ? "ok" : "danger"} label={gitOk ? "Git detected" : "Git missing"} />
            </li>
            <li className={layout.row}>
              <StatusDot
                tone={ocrOk ? "ok" : "warn"}
                label={ocrOk ? `OCR ${ocr.data?.version ?? ""} detected` : "OCR not installed — set the path in Settings"}
              />
            </li>
            <li className={layout.row}>
              <StatusDot tone={hasProject ? "ok" : "muted"} label={hasProject ? "Project registered" : "No project yet — add one from Projects"} />
            </li>
            <li className={layout.row}>
              <StatusDot tone={hasProvider ? "ok" : "muted"} label={hasProvider ? "Provider configured" : "No provider yet — add one from Providers"} />
            </li>
          </ul>
          <div className={layout.row} style={{ justifyContent: "flex-end" }}>
            <Button variant="primary" onClick={finish}>
              Open Overview
            </Button>
          </div>
        </section>
      ) : null}
    </div>
  );
}
