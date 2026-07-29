/** Pure status mapping for the Providers table status dot.

Extracted from the component so it is trivially unit-testable. The dot is
"never color alone" — every tone carries a text label (SPEC §23).
*/

import type { StatusTone } from "../../components/ui/StatusDot";
import type {
  Provider,
  ProviderHealth,
  ProviderHealthStatus,
} from "../../types";

export interface ProviderStatusView {
  tone: StatusTone;
  label: string;
  /** Pulse while the probe is still in flight. */
  pulse?: boolean;
  /** Title tooltip with sanitized detail (e.g. the HTTP error). */
  title?: string;
}

/**
 * Map provider state + health probe result to a status-dot view.
 *
 * - Disabled providers are grey ("disabled"); we never probe them.
 * - While the probe is loading (or errored), show "checking…".
 * - A 2xx (keyless or authed) is green "online".
 * - 401/403 is yellow "auth needed" — reachable but no/invalid key.
 * - Anything else is red "offline".
 */
export function providerStatusView(
  provider: Pick<Provider, "enabled">,
  health: ProviderHealth | undefined,
  options: { isLoading: boolean; isError: boolean },
): ProviderStatusView {
  if (!provider.enabled) {
    return { tone: "muted", label: "disabled" };
  }

  // Not probed yet (or the request errored) — show a neutral checking state
  // rather than a stale/inaccurate color.
  if (options.isLoading || options.isError || !health) {
    return { tone: "accent", label: "checking…", pulse: options.isLoading };
  }

  return healthStatusView(health.status, health.detail);
}

/** Map a raw health-status bucket to a dot view. Exposed for tests. */
export function healthStatusView(
  status: ProviderHealthStatus,
  detail?: string | null,
): ProviderStatusView {
  switch (status) {
    case "online":
      return { tone: "ok", label: "online" };
    case "auth_needed":
      return {
        tone: "warn",
        label: "auth needed",
        title: detail ?? undefined,
      };
    case "offline":
      return { tone: "danger", label: "offline", title: detail ?? undefined };
    case "unauthorized":
      return {
        tone: "warn",
        label: "auth needed",
        title: detail ?? undefined,
      };
  }
}
