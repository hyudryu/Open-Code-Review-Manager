/** Application settings (SPEC §20, §33.20) — tabbed sections, all wired to /settings. */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  useHealth,
  useOcrUpdateStatus,
  useReprobeOcr,
  useSettings,
  useSystemOcr,
  useUpdateSettings,
} from "../api/hooks";
import { useUiStore, type ThemePreference } from "../hooks/store";
import { PageHeader } from "../layouts/AppLayout";
import {
  Badge,
  Button,
  ErrorState,
  Input,
  Skeleton,
  StatusDot,
  Switch,
  Tabs,
  toast,
} from "../components/ui";
import { IconExternal } from "../components/ui/icons";
import layout from "../layouts/layout.module.css";

function SettingRow({
  label,
  help,
  children,
}: {
  label: string;
  help?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 24,
        padding: "10px 0",
        borderBottom: "1px solid var(--border-subtle)",
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ font: "var(--text-label)", fontSize: 13, color: "var(--text-primary)" }}>
          {label}
        </div>
        {help ? <div className={layout.small}>{help}</div> : null}
      </div>
      <div style={{ flex: "none" }}>{children}</div>
    </div>
  );
}

function NumberSetting({
  label,
  help,
  settingKey,
  min,
  max,
  settings,
  save,
}: {
  label: string;
  help?: string;
  settingKey: string;
  min: number;
  max: number;
  settings: Record<string, unknown> | undefined;
  save: (changes: Record<string, unknown>) => void;
}) {
  const current = Number(settings?.[settingKey] ?? 0);
  const [value, setValue] = useState(String(current));
  useEffect(() => setValue(String(current)), [current]);
  return (
    <SettingRow label={label} help={help}>
      <input
        type="number"
        aria-label={label}
        min={min}
        max={max}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => {
          const n = Number.parseInt(value, 10);
          if (!Number.isNaN(n) && n !== current && n >= min && n <= max) {
            save({ [settingKey]: n });
          } else {
            setValue(String(current));
          }
        }}
        style={{
          width: 90,
          height: 30,
          borderRadius: 6,
          border: "1px solid var(--border-strong)",
          background: "var(--bg-surface)",
          color: "var(--text-primary)",
          padding: "0 10px",
          font: "var(--text-body)",
        }}
      />
    </SettingRow>
  );
}

function BooleanSetting({
  label,
  help,
  settingKey,
  settings,
  save,
}: {
  label: string;
  help?: string;
  settingKey: string;
  settings: Record<string, unknown> | undefined;
  save: (changes: Record<string, unknown>) => void;
}) {
  return (
    <SettingRow label={label} help={help}>
      <Switch
        checked={Boolean(settings?.[settingKey])}
        aria-label={label}
        onCheckedChange={(checked) => save({ [settingKey]: checked })}
      />
    </SettingRow>
  );
}

export function SettingsPage() {
  const settings = useSettings();
  const update = useUpdateSettings();
  const health = useHealth();
  const ocr = useSystemOcr();
  const ocrUpdate = useOcrUpdateStatus();
  const reprobe = useReprobeOcr();
  const { themePreference, setThemePreference } = useUiStore();
  const [ocrPath, setOcrPath] = useState("");
  const [gitPath, setGitPath] = useState("");

  function openUpdateCommand() {
    const cmd = ocrUpdate.data?.install_command ?? "npm i -g @alibaba-group/open-code-review";
    const isWin = typeof window !== "undefined" && /win/i.test(navigator.userAgent);
    if (isWin) {
      // Fallback: try to open the command in a new terminal via shell URI.
      window.open(`shell:wt.exe /k ${encodeURIComponent(cmd)}`);
    } else {
      // Try to open a terminal with the command (works on most Linux desktops).
      window.open(`shell:x-terminal-emulator -e ${encodeURIComponent(cmd)}`);
    }
    toast.info("Opening terminal to run:", cmd);
  }

  useEffect(() => {
    if (settings.data) {
      setOcrPath(String(settings.data["ocr.executable"] ?? ""));
      setGitPath(String(settings.data["git.executable"] ?? ""));
    }
  }, [settings.data]);

  function save(changes: Record<string, unknown>) {
    update.mutateAsync(changes).then(
      () => toast.success("Setting saved"),
      (err: Error) => toast.error("Could not save setting", err.message),
    );
  }

  const data = settings.data;

  const generalTab = (
    <section className={layout.section} aria-label="General settings">
      <SettingRow label="Application version" help="Backend build currently running.">
        <Badge>{health.data?.version ?? "…"}</Badge>
      </SettingRow>
      <SettingRow label="Backend health" help="Live status from /api/v1/health.">
        <StatusDot
          tone={health.data?.status === "ok" ? "ok" : "danger"}
          label={health.data?.status ?? "unknown"}
        />
      </SettingRow>
      <SettingRow
        label="Diagnostics"
        help="Versions, paths, worker status, and storage usage."
      >
        <Link to="/diagnostics">
          <Button variant="secondary" size="small">Open diagnostics</Button>
        </Link>
      </SettingRow>
      <SettingRow label="Repository" help="Source code, issues, and releases on GitHub.">
        <a
          href="https://github.com/hyudryu/Open-Code-Review-Manager"
          target="_blank"
          rel="noreferrer"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            color: "var(--accent)",
            font: "var(--text-body)",
            fontSize: 13,
          }}
        >
          hyudryu/Open-Code-Review-Manager
          <IconExternal size={13} />
        </a>
      </SettingRow>
    </section>
  );

  const ocrTab = (
    <section className={`${layout.section} ${layout.stack}`} aria-label="OCR installation">
      <div className={layout.sectionHeader} style={{ margin: 0 }}>
        <h2 className={layout.sectionTitle} style={{ margin: 0 }}>Detected installation</h2>
        <Button
          variant="secondary"
          size="small"
          disabled={reprobe.isPending}
          onClick={() =>
            reprobe.mutateAsync().then(
              (s) =>
                toast.success(
                  s.status === "ok" ? `Detected OCR ${s.version ?? ""}` : "OCR not found",
                ),
              (err: Error) => toast.error("Probe failed", err.message),
            )
          }
        >
          {reprobe.isPending ? "Probing…" : "Re-detect"}
        </Button>
      </div>
      {ocr.data ? (
        <>
          <dl className={layout.dl}>
            <dt>Status</dt>
            <dd>
              <StatusDot
                tone={ocr.data.status === "ok" ? "ok" : "danger"}
                label={ocr.data.status === "ok" ? "available" : ocr.data.status}
              />
            </dd>
            <dt>Binary</dt>
            <dd>
              <code className={layout.monoPath} style={{ fontSize: 12 }}>
                {ocr.data.binary_path ?? "—"}
              </code>
            </dd>
            <dt>Version</dt>
            <dd>
              <span>
                {ocr.data.version ?? "—"}
                {ocr.data.status === "ok" && ocrUpdate.data?.latest_version ? (
                  <>
                    {ocrUpdate.data.update_available ? (
                      <span className={layout.small} style={{ marginLeft: 8, color: "var(--accent)" }}>
                        {ocrUpdate.data.latest_version} available
                      </span>
                    ) : (
                      <Badge tone="success">latest</Badge>
                    )}
                  </>
                ) : null}
              </span>
            </dd>
            {ocr.data.status === "ok" && ocrUpdate.data?.update_available && (
              <>
                <dt>Update available</dt>
                <dd>
                  <div className={layout.row} style={{ gap: 8 }}>
                    <Button
                      variant="primary"
                      size="small"
                      onClick={openUpdateCommand}
                      disabled={ocrUpdate.isFetching}
                    >
                      <IconExternal size={14} /> Update to {ocrUpdate.data.latest_version}
                    </Button>
                    <span className={layout.small}>
                      Runs: {ocrUpdate.data.install_command}
                    </span>
                  </div>
                </dd>
              </>
            )}
            {ocr.data.message ? (
              <>
                <dt>Message</dt>
                <dd className={layout.small}>{ocr.data.message}</dd>
              </>
            ) : null}
          </dl>
          <div>
            <h3 className={layout.sectionTitle} style={{ fontSize: 13.5 }}>Capabilities</h3>
            <div className={layout.row} style={{ gap: 6 }}>
              {Object.entries(ocr.data.capabilities).map(([key, supported]) => (
                <Badge key={key} tone={supported ? "success" : "neutral"}>
                  {key.replaceAll("_", " ")}
                </Badge>
              ))}
            </div>
            <p className={layout.small} style={{ marginTop: 8 }}>
              Planning controls (plan mode, plan threshold, max tokens, template override)
              require the patched OCR build; unsupported controls stay disabled and are
              never silently applied.
            </p>
          </div>
        </>
      ) : (
        <Skeleton height={120} />
      )}
      <Input
        label="Custom OCR executable path"
        value={ocrPath}
        onChange={(e) => setOcrPath(e.target.value)}
        placeholder="/usr/local/bin/ocr or C:\\tools\\ocr.exe"
        mono
        help="Leave empty to use auto-detection. Applied immediately and re-probed."
      />
      <div className={layout.row}>
        <Button
          variant="secondary"
          size="small"
          onClick={() => {
            save({ "ocr.executable": ocrPath.trim() || null });
            window.setTimeout(() => reprobe.mutate(), 400);
          }}
        >
          Apply path
        </Button>
      </div>
    </section>
  );

  const queueTab = (
    <section className={layout.section} aria-label="Queue limits">
      <NumberSetting
        label="Global concurrency"
        help="OCR processes running at once. Keep this conservative — OCR already parallelizes per file."
        settingKey="queue.global_concurrency"
        min={1}
        max={8}
        settings={data}
        save={save}
      />
      <NumberSetting
        label="Per-project concurrency"
        help="Jobs per project running at once. Workspace reviews always take a per-project exclusive lock."
        settingKey="queue.per_project_concurrency"
        min={1}
        max={4}
        settings={data}
        save={save}
      />
      <NumberSetting
        label="Per-provider concurrency"
        help="Default cap per LLM provider to avoid overloading shared endpoints."
        settingKey="queue.per_provider_concurrency"
        min={1}
        max={16}
        settings={data}
        save={save}
      />
    </section>
  );

  const storageTab = (
    <section className={layout.section} aria-label="Storage and retention">
      <NumberSetting
        label="Artifact retention (days)"
        help="Job logs, results, and session traces older than this are cleaned up."
        settingKey="retention.artifact_days"
        min={1}
        max={365}
        settings={data}
        save={save}
      />
      <BooleanSetting
        label="Keep worktrees after jobs"
        help="Off by default — detached worktrees are removed when a job finishes. Enable for debugging only."
        settingKey="retention.keep_worktrees"
        settings={data}
        save={save}
      />
    </section>
  );

  const securityTab = (
    <section className={`${layout.section} ${layout.stack}`} aria-label="Security">
      <BooleanSetting
        label="Require HTTPS for webhooks"
        help="Recommended. Disable only for local development receivers."
        settingKey="webhooks.require_https"
        settings={data}
        save={save}
      />
      <BooleanSetting
        label="Allow private-network webhook targets"
        help="Off by default to reduce SSRF risk. Enable to deliver to loopback or LAN receivers."
        settingKey="webhooks.allow_private_networks"
        settings={data}
        save={save}
      />
      <Input
        label="Custom Git executable path"
        value={gitPath}
        onChange={(e) => setGitPath(e.target.value)}
        mono
        placeholder="Leave empty for auto-detection"
      />
      <div>
        <Button
          variant="secondary"
          size="small"
          onClick={() => save({ "git.executable": gitPath.trim() || null })}
        >
          Apply Git path
        </Button>
      </div>
      <p className={layout.small}>
        The backend binds to 127.0.0.1 and requires an anti-CSRF token for state-changing
        requests. Credentials live in the OS credential store — never in the database.
      </p>
    </section>
  );

  const appearanceTab = (
    <section className={layout.section} aria-label="Appearance">
      <SettingRow
        label="Theme"
        help="System follows your OS preference; the choice is remembered on this device."
      >
        <div className={layout.row} role="radiogroup" aria-label="Theme">
          {(["system", "light", "dark"] as ThemePreference[]).map((pref) => (
            <Button
              key={pref}
              variant={themePreference === pref ? "primary" : "secondary"}
              size="small"
              role="radio"
              aria-checked={themePreference === pref}
              onClick={() => setThemePreference(pref)}
            >
              {pref[0].toUpperCase() + pref.slice(1)}
            </Button>
          ))}
        </div>
      </SettingRow>
    </section>
  );

  return (
    <>
      <PageHeader title="Settings" subtitle="Queue behavior, OCR installation, retention, security, and appearance." />
      {settings.error ? (
        <ErrorState title="Could not load settings" error={settings.error} onRetry={() => settings.refetch()} />
      ) : settings.isLoading ? (
        <Skeleton height={300} />
      ) : (
        <div style={{ maxWidth: 820 }}>
          <Tabs
            aria-label="Settings sections"
            items={[
              { value: "general", label: "General", content: generalTab },
              { value: "ocr", label: "OCR Installation", content: ocrTab },
              { value: "queue", label: "Queue", content: queueTab },
              { value: "storage", label: "Storage & Retention", content: storageTab },
              { value: "security", label: "Security", content: securityTab },
              { value: "appearance", label: "Appearance", content: appearanceTab },
            ]}
          />
        </div>
      )}
    </>
  );
}
