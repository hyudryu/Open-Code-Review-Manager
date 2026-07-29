/** Status dot for one Providers-table row: probes GET /models on mount.

Auto-on-load (per the design): every enabled provider is probed in
parallel when the page opens. Disabled providers are not probed. The probe
is cached 30s (see useProviderHealth) so revisits don't re-hit dead hosts.
*/

import { StatusDot } from "../../components/ui";
import { useProviderHealth } from "../../api/hooks";
import { providerStatusView } from "./providerStatusHelpers";

export function ProviderStatus({
  providerId,
  enabled,
}: {
  providerId: string;
  enabled: boolean;
}) {
  // Disabled providers have nothing to probe; keep the query dormant.
  const health = useProviderHealth(providerId, { enabled });
  const view = providerStatusView(
    { enabled },
    health.data,
    { isLoading: health.isLoading, isError: health.isError },
  );
  return (
    // Wrap so the sanitized detail surfaces as a native tooltip on the
    // auth_needed/offline states. StatusDot itself has no title prop.
    <span title={view.title}>
      <StatusDot tone={view.tone} label={view.label} pulse={view.pulse} />
    </span>
  );
}
