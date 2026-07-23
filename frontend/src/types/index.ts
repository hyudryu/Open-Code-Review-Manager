/** API types mirroring backend/app/schemas (SPEC §4, §19). */

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

// --- projects / folders -----------------------------------------------------

export interface Folder {
  id: string;
  display_name: string;
  absolute_path: string;
  scan_depth: number;
  auto_discover: boolean;
  last_scanned_at: string | null;
  created_at: string;
}

export interface ScannedRepo {
  path: string;
  name: string;
  has_git_file: boolean;
  already_registered: boolean;
}

export interface FolderScan {
  folder_id: string;
  root: string;
  repos: ScannedRepo[];
  errors: string[];
}

export interface Project {
  id: string;
  folder_id: string | null;
  display_name: string;
  absolute_path: string;
  default_branch: string | null;
  remote_name: string | null;
  remote_url: string | null;
  current_branch: string | null;
  is_dirty: boolean;
  is_available: boolean;
  last_branch_refresh_at: string | null;
  created_at: string;
}

export type BranchKind = "local" | "remote" | "tag";

export interface Branch {
  id: string;
  name: string;
  full_ref: string;
  kind: BranchKind;
  remote_name: string | null;
  commit_sha: string | null;
  commit_subject: string | null;
  commit_timestamp: string | null;
  is_default: boolean;
  is_current: boolean;
}

// --- providers / models -----------------------------------------------------

export type Protocol = "openai" | "openai-responses" | "anthropic";

export interface Provider {
  id: string;
  name: string;
  provider_type: string;
  protocol: Protocol;
  base_url: string;
  has_credential: boolean;
  auth_header: string | null;
  http_timeout_seconds: number;
  model_discovery_mode: "auto" | "manual" | "adapter";
  enabled: boolean;
  last_discovery_at: string | null;
  last_discovery_error: string | null;
  created_at: string;
}

export interface ProviderModel {
  id: string;
  model_id: string;
  display_name: string | null;
  context_length: number | null;
  supports_tools: boolean | null;
  is_manual: boolean;
  is_enabled: boolean;
  last_discovered_at: string | null;
}

export interface ProviderTestResult {
  ok: boolean;
  status: string;
  exit_code: number | null;
  elapsed_ms: number | null;
  stdout: string;
  stderr: string;
  message: string | null;
}

// --- review profiles --------------------------------------------------------

export type PlanMode = "auto" | "always" | "never";

export interface ReviewProfile {
  id: string;
  name: string;
  description: string | null;
  provider_profile_id: string | null;
  model_id: string | null;
  language: string | null;
  concurrency: number | null;
  per_file_timeout_minutes: number | null;
  llm_http_timeout_seconds: number | null;
  max_tools: number | null;
  max_git_processes: number | null;
  plan_mode: PlanMode;
  plan_threshold_lines: number | null;
  max_tokens: number | null;
  template_path: string | null;
  exclude_patterns: string[] | null;
  rule_file_path: string | null;
  tools_file_path: string | null;
  background_template: string | null;
  additional_arguments: string | null;
  created_at: string;
}

// --- jobs / queue -----------------------------------------------------------

export type JobMode = "range" | "commit" | "workspace";
export type JobStatus =
  | "queued"
  | "preparing"
  | "running"
  | "cancelling"
  | "completed"
  | "completed_with_warnings"
  | "failed"
  | "cancelled"
  | "interrupted";

export const TERMINAL_STATUSES: JobStatus[] = [
  "completed",
  "completed_with_warnings",
  "failed",
  "cancelled",
  "interrupted",
];

export const ACTIVE_STATUSES: JobStatus[] = [
  "queued",
  "preparing",
  "running",
  "cancelling",
];

export interface ResultSummary {
  files_reviewed?: number | null;
  comments?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  cache_read_tokens?: number | null;
  cache_write_tokens?: number | null;
  total_tokens?: number | null;
  elapsed?: string | null;
}

export interface Job {
  id: string;
  project_id: string;
  profile_id: string | null;
  source: string;
  mode: JobMode;
  base_ref: string | null;
  target_ref: string | null;
  commit_ref: string | null;
  priority: number;
  queue_position: number | null;
  status: JobStatus;
  status_message: string | null;
  paused: boolean;
  configuration_snapshot_json: Record<string, unknown> | null;
  generated_command_json: GeneratedCommand | null;
  ocr_version: string | null;
  ocr_session_id: string | null;
  result_summary_json: ResultSummary | null;
  warnings_json: JobWarning[] | null;
  exit_code: number | null;
  retry_of_job_id: string | null;
  resume_from_session_id: string | null;
  queued_at: string;
  started_at: string | null;
  completed_at: string | null;
  findings_count: number;
}

export interface GeneratedCommand {
  argv: string[];
  env: Record<string, string>;
  cwd: string | null;
  executable: string | null;
}

export interface JobWarning {
  file?: string | null;
  message: string;
  type?: string | null;
}

export interface QueueState {
  paused: boolean;
  jobs: Job[];
}

export interface JobCreateInput {
  project_id: string;
  mode: JobMode;
  base_ref?: string | null;
  target_ref?: string | null;
  commit_ref?: string | null;
  profile_id?: string | null;
  background?: string | null;
  background_file?: string | null;
  exclude_patterns?: string[] | null;
  priority?: number;
  webhook_endpoint_id?: string | null;
}

export interface PreviewFile {
  path: string;
  status: string | null;
  insertions: number | null;
  deletions: number | null;
  will_review: boolean;
  exclude_reason: string | null;
}

export interface JobPreview {
  files: PreviewFile[];
  total_files: number | null;
  reviewable_count: number | null;
  excluded_count: number | null;
  total_insertions: number | null;
  total_deletions: number | null;
}

// --- findings ---------------------------------------------------------------

export type FindingState =
  | "unreviewed"
  | "accepted"
  | "dismissed"
  | "needs_followup";

export interface Finding {
  id: string;
  job_id: string;
  path: string;
  content: string;
  start_line: number | null;
  end_line: number | null;
  existing_code: string | null;
  suggestion_code: string | null;
  category: string | null;
  severity: string | null;
  user_state: FindingState;
  user_note: string | null;
  created_at: string;
  /** Only present when explicitly requested with include_reasoning=true. */
  thinking?: string | null;
}

export interface JobLog {
  stream: string;
  text: string;
  size: number;
  truncated: boolean;
}

export interface SessionRecord {
  seq?: number;
  record_type?: string;
  timestamp?: string | null;
  session_id?: string | null;
  file_path?: string | null;
  task_type?: string | null;
  request_no?: number | null;
  tool_name?: string | null;
  error?: string | null;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  duration_ms?: number | null;
  comments_count?: number | null;
  raw?: Record<string, unknown> | null;
  [key: string]: unknown;
}

export interface SessionOut {
  records: SessionRecord[];
  total: number;
  session_file: string | null;
  session_id: string | null;
}

export interface JobEventRecord {
  id: number;
  event_type: string;
  payload: Record<string, unknown> | null;
  created_at: string | null;
}

// --- webhooks ---------------------------------------------------------------

export const WEBHOOK_EVENTS = [
  "review.queued",
  "review.started",
  "review.completed",
  "review.completed_with_warnings",
  "review.failed",
  "review.cancelled",
] as const;

export interface WebhookEndpoint {
  id: string;
  name: string;
  url: string;
  allowed_events: string[];
  enabled: boolean;
  has_secret: boolean;
  last_delivery_at: string | null;
  created_at: string;
}

export interface WebhookDelivery {
  id: string;
  endpoint_id: string;
  job_id: string | null;
  event_type: string;
  delivery_id: string;
  attempt: number;
  status: string;
  http_status: number | null;
  response_excerpt: string | null;
  next_attempt_at: string | null;
  created_at: string;
  completed_at: string | null;
}

// --- system -----------------------------------------------------------------

export interface OCRCapabilities {
  json_output: boolean;
  agent_audience: boolean;
  resume: boolean;
  background: boolean;
  background_file: boolean;
  exclude_flag: boolean;
  preview: boolean;
  model_override: boolean;
  rule_flag: boolean;
  tools_flag: boolean;
  concurrency_flag: boolean;
  timeout_flag: boolean;
  max_tools_flag: boolean;
  max_git_procs_flag: boolean;
  plan_mode: boolean;
  plan_threshold: boolean;
  max_tokens: boolean;
  template_override: boolean;
  llm_test: boolean;
  llm_providers: boolean;
  scan: boolean;
  rules_check: boolean;
  viewer: boolean;
  config_set: boolean;
}

export interface OCRStatus {
  status: "ok" | "ocr_not_found" | "probe_failed";
  binary_path: string | null;
  version: string | null;
  capabilities: OCRCapabilities;
  honored_env_overrides: string[];
  message: string | null;
}

export interface Health {
  status: string;
  version: string;
  ocr_status: string;
}

export interface SystemInfo {
  app_version: string;
  python_version: string;
  platform: string;
  database_path: string;
  database_status: string;
  data_dir: string;
  ocr: OCRStatus;
  git_version: string | null;
  mcp: { mounted: boolean; endpoint: string };
  queue_worker: { running: boolean; active_jobs: number };
  webhook_worker: { running: boolean };
  active_process_count: number;
  job_count: number;
  worktree_count: number;
  session_storage_bytes: number;
}

export type SettingsMap = Record<string, unknown> & {
  "queue.global_concurrency"?: number;
  "queue.per_project_concurrency"?: number;
  "queue.per_provider_concurrency"?: number;
  "queue.paused"?: boolean;
  "retention.artifact_days"?: number;
  "retention.keep_worktrees"?: boolean;
  "webhooks.require_https"?: boolean;
  "webhooks.allow_private_networks"?: boolean;
  "ocr.executable"?: string | null;
  "git.executable"?: string | null;
};
