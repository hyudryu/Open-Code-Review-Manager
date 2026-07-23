/** TanStack Query hooks for every backend resource (SPEC §19 routes). */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { api } from "./client";
import type {
  Branch,
  Finding,
  Folder,
  FolderScan,
  Health,
  Job,
  JobCreateInput,
  JobEventRecord,
  JobLog,
  JobPreview,
  OCRStatus,
  Page,
  PreviewFile,
  Project,
  Provider,
  ProviderModel,
  ProviderTestResult,
  QueueState,
  ReviewProfile,
  ScannedRepo,
  SessionOut,
  SettingsMap,
  SystemInfo,
  WebhookDelivery,
  WebhookEndpoint,
} from "../types";

export const qk = {
  health: ["health"] as const,
  systemInfo: ["system", "info"] as const,
  systemOcr: ["system", "ocr"] as const,
  settings: ["settings"] as const,
  folders: ["folders"] as const,
  projects: ["projects"] as const,
  project: (id: string) => ["projects", id] as const,
  branches: (id: string) => ["projects", id, "branches"] as const,
  projectJobs: (id: string) => ["projects", id, "jobs"] as const,
  providers: ["providers"] as const,
  provider: (id: string) => ["providers", id] as const,
  models: (id: string) => ["providers", id, "models"] as const,
  profiles: ["profiles"] as const,
  profile: (id: string) => ["profiles", id] as const,
  jobs: (filters?: Record<string, unknown>) => ["jobs", filters ?? {}] as const,
  job: (id: string) => ["jobs", id] as const,
  queue: ["queue"] as const,
  findings: (jobId: string, filters?: Record<string, unknown>) =>
    ["jobs", jobId, "findings", filters ?? {}] as const,
  warnings: (jobId: string) => ["jobs", jobId, "warnings"] as const,
  logs: (jobId: string, stream: string) => ["jobs", jobId, "logs", stream] as const,
  session: (jobId: string, offset: number, filters?: Record<string, unknown>) =>
    ["jobs", jobId, "session", offset, filters ?? {}] as const,
  eventHistory: (jobId: string) => ["jobs", jobId, "events", "history"] as const,
  webhooks: ["webhooks"] as const,
  deliveries: (endpointId: string) => ["webhooks", endpointId, "deliveries"] as const,
};

// --- system -----------------------------------------------------------------

export function useHealth(options?: Partial<UseQueryOptions<Health>>) {
  return useQuery({
    queryKey: qk.health,
    queryFn: () => api.get<Health>("/api/v1/health"),
    refetchInterval: 30_000,
    ...options,
  });
}

export function useSystemInfo(options?: Partial<UseQueryOptions<SystemInfo>>) {
  return useQuery({
    queryKey: qk.systemInfo,
    queryFn: () => api.get<SystemInfo>("/api/v1/system/info"),
    ...options,
  });
}

export function useSystemOcr(options?: Partial<UseQueryOptions<OCRStatus>>) {
  return useQuery({
    queryKey: qk.systemOcr,
    queryFn: () => api.get<OCRStatus>("/api/v1/system/ocr"),
    staleTime: 60_000,
    ...options,
  });
}

export function useReprobeOcr() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<OCRStatus>("/api/v1/system/ocr/test"),
    onSuccess: (data) => {
      qc.setQueryData(qk.systemOcr, data);
      void qc.invalidateQueries({ queryKey: qk.systemInfo });
      void qc.invalidateQueries({ queryKey: qk.health });
    },
  });
}

export function useSettings() {
  return useQuery({
    queryKey: qk.settings,
    queryFn: () => api.get<SettingsMap>("/api/v1/settings"),
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (changes: Record<string, unknown>) =>
      api.patch<SettingsMap>("/api/v1/settings", { changes }),
    onSuccess: (data) => {
      qc.setQueryData(qk.settings, data);
      void qc.invalidateQueries({ queryKey: qk.systemOcr });
      void qc.invalidateQueries({ queryKey: qk.systemInfo });
      void qc.invalidateQueries({ queryKey: qk.queue });
    },
  });
}

// --- folders ----------------------------------------------------------------

export function useFolders() {
  return useQuery({
    queryKey: qk.folders,
    queryFn: () => api.get<Folder[]>("/api/v1/folders"),
  });
}

export function useCreateFolder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      display_name: string;
      absolute_path: string;
      scan_depth: number;
      auto_discover?: boolean;
    }) => api.post<Folder>("/api/v1/folders", input),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.folders }),
  });
}

export function useUpdateFolder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...patch
    }: {
      id: string;
      display_name?: string;
      scan_depth?: number;
      auto_discover?: boolean;
    }) => api.patch<Folder>(`/api/v1/folders/${id}`, patch),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.folders }),
  });
}

export function useDeleteFolder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/api/v1/folders/${id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.folders });
      void qc.invalidateQueries({ queryKey: qk.projects });
    },
  });
}

export function useScanFolder() {
  return useMutation({
    mutationFn: (folderId: string) =>
      api.post<FolderScan>(`/api/v1/folders/${folderId}/scan`),
  });
}

export function useRegisterScanned() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ folderId, paths }: { folderId: string; paths: string[] }) =>
      api.post<Project[]>(`/api/v1/folders/${folderId}/register`, { paths }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.projects });
      void qc.invalidateQueries({ queryKey: qk.folders });
    },
  });
}

// --- projects ---------------------------------------------------------------

export function useProjects(query?: string) {
  return useQuery({
    queryKey: qk.projects,
    queryFn: () => api.get<Project[]>("/api/v1/projects", { query }),
  });
}

export function useProject(id: string) {
  return useQuery({
    queryKey: qk.project(id),
    queryFn: () => api.get<Project>(`/api/v1/projects/${id}`),
    enabled: Boolean(id),
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      absolute_path: string;
      folder_id?: string | null;
      display_name?: string | null;
    }) => api.post<Project>("/api/v1/projects", input),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.projects }),
  });
}

export function useUpdateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...patch
    }: {
      id: string;
      display_name?: string;
      default_branch?: string;
      remote_name?: string;
      is_available?: boolean;
    }) => api.patch<Project>(`/api/v1/projects/${id}`, patch),
    onSuccess: (data) => {
      qc.setQueryData(qk.project(data.id), data);
      void qc.invalidateQueries({ queryKey: qk.projects });
    },
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/api/v1/projects/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.projects }),
  });
}

export function useBranches(projectId: string) {
  return useQuery({
    queryKey: qk.branches(projectId),
    queryFn: () => api.get<Branch[]>(`/api/v1/projects/${projectId}/branches`),
    enabled: Boolean(projectId),
  });
}

export function useRefreshBranches() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, fetch }: { projectId: string; fetch?: boolean }) =>
      api.post<{ branches: Branch[]; fetch_error: string | null }>(
        fetch
          ? `/api/v1/projects/${projectId}/fetch`
          : `/api/v1/projects/${projectId}/refresh-branches`,
      ),
    onSuccess: (data, vars) => {
      qc.setQueryData(qk.branches(vars.projectId), data.branches);
      void qc.invalidateQueries({ queryKey: qk.project(vars.projectId) });
    },
  });
}

export function useProjectJobs(projectId: string) {
  return useQuery({
    queryKey: qk.projectJobs(projectId),
    queryFn: () => api.get<Job[]>(`/api/v1/projects/${projectId}/jobs`),
    enabled: Boolean(projectId),
  });
}

// --- providers / models -----------------------------------------------------

export interface ProviderInput {
  name: string;
  provider_type?: string;
  protocol: string;
  base_url?: string;
  credential?: string | null;
  auth_header?: string | null;
  http_timeout_seconds?: number;
  extra_headers?: Record<string, string> | null;
  extra_body?: Record<string, unknown> | null;
  model_discovery_mode?: string;
  enabled?: boolean;
}

export function useProviders() {
  return useQuery({
    queryKey: qk.providers,
    queryFn: () => api.get<Provider[]>("/api/v1/providers"),
  });
}

export function useProvider(id: string) {
  return useQuery({
    queryKey: qk.provider(id),
    queryFn: () => api.get<Provider>(`/api/v1/providers/${id}`),
    enabled: Boolean(id),
  });
}

export function useCreateProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: ProviderInput) => api.post<Provider>("/api/v1/providers", input),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.providers }),
  });
}

export function useUpdateProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...patch }: ProviderInput & { id: string }) =>
      api.patch<Provider>(`/api/v1/providers/${id}`, patch),
    onSuccess: (data) => {
      qc.setQueryData(qk.provider(data.id), data);
      void qc.invalidateQueries({ queryKey: qk.providers });
    },
  });
}

export function useDeleteProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/api/v1/providers/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.providers }),
  });
}

export function useTestProvider() {
  return useMutation({
    mutationFn: ({ id, modelId }: { id: string; modelId?: string }) =>
      api.post<ProviderTestResult>(
        `/api/v1/providers/${id}/test`,
        undefined,
        modelId ? { model_id: modelId } : undefined,
      ),
  });
}

export function useDiscoverModels() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.post<ProviderModel[]>(`/api/v1/providers/${id}/discover-models`),
    onSuccess: (_data, id) => {
      void qc.invalidateQueries({ queryKey: qk.models(id) });
      void qc.invalidateQueries({ queryKey: qk.provider(id) });
    },
  });
}

export function useModels(providerId: string) {
  return useQuery({
    queryKey: qk.models(providerId),
    queryFn: () => api.get<ProviderModel[]>(`/api/v1/providers/${providerId}/models`),
    enabled: Boolean(providerId),
  });
}

export function useAddModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      providerId,
      ...input
    }: {
      providerId: string;
      model_id: string;
      display_name?: string;
      context_length?: number | null;
    }) => api.post<ProviderModel>(`/api/v1/providers/${providerId}/models`, input),
    onSuccess: (_d, vars) =>
      void qc.invalidateQueries({ queryKey: qk.models(vars.providerId) }),
  });
}

export function useRemoveModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ providerId, modelPk }: { providerId: string; modelPk: string }) =>
      api.delete(`/api/v1/providers/${providerId}/models/${modelPk}`),
    onSuccess: (_d, vars) =>
      void qc.invalidateQueries({ queryKey: qk.models(vars.providerId) }),
  });
}

// --- review profiles --------------------------------------------------------

export interface ProfileInput {
  name: string;
  description?: string | null;
  provider_profile_id?: string | null;
  model_id?: string | null;
  language?: string | null;
  concurrency?: number | null;
  per_file_timeout_minutes?: number | null;
  llm_http_timeout_seconds?: number | null;
  max_tools?: number | null;
  max_git_processes?: number | null;
  plan_mode?: string;
  plan_threshold_lines?: number | null;
  max_tokens?: number | null;
  exclude_patterns?: string[] | null;
  rule_file_path?: string | null;
  tools_file_path?: string | null;
  background_template?: string | null;
  additional_arguments?: string | null;
}

export function useProfiles() {
  return useQuery({
    queryKey: qk.profiles,
    queryFn: () => api.get<ReviewProfile[]>("/api/v1/review-profiles"),
  });
}

export function useProfile(id: string) {
  return useQuery({
    queryKey: qk.profile(id),
    queryFn: () => api.get<ReviewProfile>(`/api/v1/review-profiles/${id}`),
    enabled: Boolean(id),
  });
}

export function useCreateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: ProfileInput) =>
      api.post<ReviewProfile>("/api/v1/review-profiles", input),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.profiles }),
  });
}

export function useUpdateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...patch }: ProfileInput & { id: string }) =>
      api.patch<ReviewProfile>(`/api/v1/review-profiles/${id}`, patch),
    onSuccess: (data) => {
      qc.setQueryData(qk.profile(data.id), data);
      void qc.invalidateQueries({ queryKey: qk.profiles });
    },
  });
}

export function useDeleteProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/api/v1/review-profiles/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.profiles }),
  });
}

export function useDuplicateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, newName }: { id: string; newName?: string }) =>
      api.post<ReviewProfile>(
        `/api/v1/review-profiles/${id}/duplicate`,
        undefined,
        newName ? { new_name: newName } : undefined,
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.profiles }),
  });
}

// --- jobs -------------------------------------------------------------------

export interface JobFilters {
  status?: string;
  project_id?: string;
  source?: string;
  provider_id?: string;
  limit?: number;
  offset?: number;
}

export function useJobs(filters: JobFilters = {}) {
  return useQuery({
    queryKey: qk.jobs(filters as Record<string, unknown>),
    queryFn: () =>
      api.get<Page<Job>>("/api/v1/jobs", { ...filters }),
    placeholderData: (prev) => prev,
  });
}

export function useJob(id: string, options?: Partial<UseQueryOptions<Job>>) {
  return useQuery({
    queryKey: qk.job(id),
    queryFn: () => api.get<Job>(`/api/v1/jobs/${id}`),
    enabled: Boolean(id),
    ...options,
  });
}

export function useCreateJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: JobCreateInput) => api.post<Job>("/api/v1/jobs", input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.jobs() });
      void qc.invalidateQueries({ queryKey: qk.queue });
    },
  });
}

export function usePreviewJob() {
  return useMutation({
    mutationFn: (input: {
      project_id: string;
      mode: string;
      base_ref?: string | null;
      target_ref?: string | null;
      commit_ref?: string | null;
      profile_id?: string | null;
      exclude_patterns?: string[] | null;
    }) => api.post<JobPreview>("/api/v1/jobs/preview", input),
  });
}

function useJobAction<TBody = undefined>(
  action: (id: string, body: TBody) => Promise<Job>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body?: TBody }) =>
      action(id, body as TBody),
    onSuccess: (data) => {
      qc.setQueryData(qk.job(data.id), data);
      void qc.invalidateQueries({ queryKey: qk.jobs() });
      void qc.invalidateQueries({ queryKey: qk.queue });
    },
  });
}

export function useCancelJob() {
  return useJobAction((id) => api.post<Job>(`/api/v1/jobs/${id}/cancel`));
}

export function useRetryJob() {
  return useJobAction<{ priority?: number; background?: string }>((id, body) =>
    api.post<Job>(`/api/v1/jobs/${id}/retry`, body),
  );
}

export function useResumeJob() {
  return useJobAction((id) => api.post<Job>(`/api/v1/jobs/${id}/resume`));
}

export function useDuplicateJob() {
  return useJobAction((id) => api.post<Job>(`/api/v1/jobs/${id}/duplicate`));
}

export function useMoveJob() {
  return useJobAction<{ action: "top" | "up" | "down" }>((id, body) =>
    api.post<Job>(`/api/v1/jobs/${id}/move`, body),
  );
}

export function usePauseJob() {
  return useJobAction((id) => api.post<Job>(`/api/v1/jobs/${id}/pause`));
}

export function useResumePausedJob() {
  return useJobAction((id) => api.post<Job>(`/api/v1/jobs/${id}/resume-paused`));
}

export function useUpdateJobPriority() {
  return useJobAction<{ priority: number }>((id, body) =>
    api.patch<Job>(`/api/v1/jobs/${id}`, body),
  );
}

export function useDeleteJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/api/v1/jobs/${id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.jobs() });
      void qc.invalidateQueries({ queryKey: qk.queue });
    },
  });
}

// --- queue ------------------------------------------------------------------

export function useQueue(options?: { refetchInterval?: number | false }) {
  return useQuery({
    queryKey: qk.queue,
    queryFn: () => api.get<QueueState>("/api/v1/queue"),
    refetchInterval: options?.refetchInterval ?? 10_000,
  });
}

export function usePauseQueue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<QueueState>("/api/v1/queue/pause"),
    onSuccess: (data) => {
      qc.setQueryData(qk.queue, data);
      void qc.invalidateQueries({ queryKey: qk.settings });
    },
  });
}

export function useResumeQueue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<QueueState>("/api/v1/queue/resume"),
    onSuccess: (data) => {
      qc.setQueryData(qk.queue, data);
      void qc.invalidateQueries({ queryKey: qk.settings });
    },
  });
}

export function useReorderQueue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobIds: string[]) =>
      api.post<Job[]>("/api/v1/queue/reorder", { job_ids: jobIds }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.queue }),
  });
}

export function useClearCompleted() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ removed: number }>("/api/v1/queue/clear-completed"),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.queue });
      void qc.invalidateQueries({ queryKey: qk.jobs() });
    },
  });
}

// --- findings / logs / session ----------------------------------------------

export function useFindings(
  jobId: string,
  filters: { user_state?: string; path?: string; limit?: number; offset?: number } = {},
) {
  return useQuery({
    queryKey: qk.findings(jobId, filters as Record<string, unknown>),
    queryFn: () =>
      api.get<Page<Finding>>(`/api/v1/jobs/${jobId}/findings`, { ...filters }),
    enabled: Boolean(jobId),
    placeholderData: (prev) => prev,
  });
}

export function useUpdateFinding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      jobId,
      findingId,
      ...patch
    }: {
      jobId: string;
      findingId: string;
      user_state?: string;
      user_note?: string | null;
    }) =>
      api.patch<Finding>(`/api/v1/jobs/${jobId}/findings/${findingId}`, patch),
    onSuccess: (_d, vars) => {
      void qc.invalidateQueries({ queryKey: ["jobs", vars.jobId, "findings"] });
      void qc.invalidateQueries({ queryKey: qk.job(vars.jobId) });
    },
  });
}

/**
 * Lazily fetch a single finding's reasoning. Reasoning is opt-in on the API
 * (SPEC §38.15) — only request it when the user opens the disclosure.
 */
export function useFindingReasoning(
  jobId: string,
  findingId: string,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ["jobs", jobId, "findings", findingId, "reasoning"] as const,
    queryFn: () =>
      api.get<Finding>(`/api/v1/jobs/${jobId}/findings/${findingId}`, {
        include_reasoning: true,
      }),
    enabled: enabled && Boolean(jobId) && Boolean(findingId),
    staleTime: Infinity,
  });
}

export function useWarnings(jobId: string) {
  return useQuery({
    queryKey: qk.warnings(jobId),
    queryFn: () => api.get<unknown[]>(`/api/v1/jobs/${jobId}/warnings`),
    enabled: Boolean(jobId),
  });
}

export function useJobLogs(jobId: string, stream: "stdout" | "stderr") {
  return useQuery({
    queryKey: qk.logs(jobId, stream),
    queryFn: () =>
      api.get<JobLog>(`/api/v1/jobs/${jobId}/logs`, { stream, tail_bytes: 128_000 }),
    enabled: Boolean(jobId),
  });
}

export interface SessionFilters {
  q?: string;
  task_type?: string;
  file?: string;
}

export function useJobSession(
  jobId: string,
  offset: number,
  limit = 200,
  filters: SessionFilters = {},
) {
  return useQuery({
    queryKey: qk.session(jobId, offset, filters as Record<string, unknown>),
    queryFn: () =>
      api.get<SessionOut>(`/api/v1/jobs/${jobId}/session`, {
        limit,
        offset,
        ...filters,
      }),
    enabled: Boolean(jobId),
    placeholderData: (prev) => prev,
  });
}

export function useJobEventHistory(jobId: string) {
  return useQuery({
    queryKey: qk.eventHistory(jobId),
    queryFn: () =>
      api.get<JobEventRecord[]>(`/api/v1/jobs/${jobId}/events/history`, {
        limit: 500,
      }),
    enabled: Boolean(jobId),
  });
}

// --- webhooks ---------------------------------------------------------------

export interface WebhookInput {
  name: string;
  url: string;
  secret?: string | null;
  allowed_events?: string[];
  enabled?: boolean;
  rotate_secret?: boolean;
}

export function useWebhooks() {
  return useQuery({
    queryKey: qk.webhooks,
    queryFn: () => api.get<WebhookEndpoint[]>("/api/v1/webhooks"),
  });
}

export function useCreateWebhook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: WebhookInput) => api.post<WebhookEndpoint>("/api/v1/webhooks", input),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.webhooks }),
  });
}

export function useUpdateWebhook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...patch }: Partial<WebhookInput> & { id: string }) =>
      api.patch<WebhookEndpoint>(`/api/v1/webhooks/${id}`, patch),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.webhooks }),
  });
}

export function useDeleteWebhook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/api/v1/webhooks/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.webhooks }),
  });
}

export function useTestWebhook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.post<WebhookDelivery>(`/api/v1/webhooks/${id}/test`),
    onSuccess: (_d, id) =>
      void qc.invalidateQueries({ queryKey: qk.deliveries(id) }),
  });
}

export function useDeliveries(endpointId: string) {
  return useQuery({
    queryKey: qk.deliveries(endpointId),
    queryFn: () =>
      api.get<WebhookDelivery[]>(`/api/v1/webhooks/${endpointId}/deliveries`, {
        limit: 100,
      }),
    enabled: Boolean(endpointId),
  });
}

export function useReplayDelivery() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (deliveryId: string) =>
      api.post<WebhookDelivery>(`/api/v1/webhook-deliveries/${deliveryId}/replay`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.webhooks }),
  });
}

export type { PreviewFile, ScannedRepo };
