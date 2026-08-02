/**
 * Live generated-command preview (SPEC §36) — mirrors the argv the backend's
 * OCRAdapter builds (backend/app/ocr/adapter.py build_review_command).
 */

import type { JobMode, OCRStatus, ReviewProfile } from "../types";

export interface CommandPreviewInput {
  mode: JobMode;
  repoPath: string;
  baseRef?: string | null;
  targetRef?: string | null;
  commitRef?: string | null;
  baseSha?: string | null;
  targetSha?: string | null;
  commitSha?: string | null;
  profile?: ReviewProfile | null;
  model?: string | null;
  background?: string | null;
  backgroundFile?: string | null;
  excludePatterns?: string[] | null;
  additionalArgs?: string[];
}

export interface CommandPreview {
  executable: string;
  argv: string[];
  env: Record<string, string>;
  cwd: string;
}

export function buildCommandPreview(
  input: CommandPreviewInput,
  ocr: OCRStatus | undefined,
): CommandPreview {
  const executable = ocr?.binary_path ?? "ocr";
  const caps = ocr?.capabilities;
  const profile = input.profile ?? null;

  const isScan = input.mode === "scan";
  const argv: string[] = [executable, isScan ? "scan" : "review", "--repo", input.repoPath];

  if (input.mode === "range" || input.mode === "pr") {
    // PR jobs review PR-head vs PR-base: same argv as a range review over the
    // SHAs captured immutably at queue time.
    argv.push(
      "--from",
      input.baseSha ?? input.baseRef ?? "<base>",
      "--to",
      input.targetSha ?? input.targetRef ?? "<target>",
    );
  } else if (input.mode === "commit") {
    argv.push("--commit", input.commitSha ?? input.commitRef ?? "<commit>");
  }

  if (profile) {
    if (profile.concurrency && caps?.concurrency_flag !== false)
      argv.push("--concurrency", String(profile.concurrency));
    if (profile.per_file_timeout_minutes && caps?.timeout_flag !== false)
      argv.push("--timeout", String(profile.per_file_timeout_minutes));
    if (profile.max_tools && caps?.max_tools_flag !== false)
      argv.push("--max-tools", String(profile.max_tools));
    if (profile.max_git_processes && caps?.max_git_procs_flag !== false)
      argv.push("--max-git-procs", String(profile.max_git_processes));
    if (profile.rule_file_path && caps?.rule_flag !== false)
      argv.push("--rule", profile.rule_file_path);
    if (profile.tools_file_path && caps?.tools_flag !== false)
      argv.push("--tools", profile.tools_file_path);
    if (isScan) {
      if (profile.plan_mode === "never") argv.push("--no-plan");
      if (profile.max_tokens)
        argv.push("--max-tokens-budget", String(profile.max_tokens));
    } else if (caps?.plan_mode) {
      if (profile.plan_mode && profile.plan_mode !== "auto")
        argv.push("--plan-mode", profile.plan_mode);
      if (profile.plan_threshold_lines)
        argv.push("--plan-threshold", String(profile.plan_threshold_lines));
      if (profile.max_tokens) argv.push("--max-tokens", String(profile.max_tokens));
    }
    if (!isScan && caps?.template_override && profile.template_path)
      argv.push("--template", profile.template_path);
  }

  if (input.model) argv.push("--model", input.model);
  if (input.background) argv.push("--background", input.background);
  if (!isScan && input.backgroundFile) argv.push("--background-file", input.backgroundFile);

  const excludes =
    input.excludePatterns?.length
      ? input.excludePatterns
      : profile?.exclude_patterns?.length
        ? profile.exclude_patterns
        : null;
  if (excludes?.length) argv.push("--exclude", excludes.join(","));

  if (input.additionalArgs?.length) argv.push(...input.additionalArgs);

  // Always forced by the runner (SPEC §8).
  argv.push("--format", "json", "--audience", "agent");

  const env: Record<string, string> = {
    "HOME / USERPROFILE": "<job-home>/.opencodereview (isolated per job)",
  };
  if (input.model) env.OCR_LLM_MODEL = input.model;
  env.OCR_LLM_URL = "<provider base URL>";
  env.OCR_LLM_TOKEN = "•••••••• (redacted)";
  env.OCR_LLM_PROTOCOL = "<provider protocol>";

  return { executable, argv, env, cwd: input.repoPath };
}
