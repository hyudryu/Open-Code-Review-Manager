import { describe, expect, it } from "vitest";
import {
  healthStatusView,
  providerStatusView,
} from "../src/features/providers/providerStatusHelpers";
import type { ProviderHealth } from "../src/types";

describe("providerStatusView", () => {
  it("disabled providers are muted 'disabled' regardless of health", () => {
    const view = providerStatusView(
      { enabled: false },
      undefined,
      { isLoading: false, isError: false },
    );
    expect(view).toEqual({ tone: "muted", label: "disabled" });
  });

  it("shows a pulsing 'checking…' accent dot while the probe loads", () => {
    const view = providerStatusView(
      { enabled: true },
      undefined,
      { isLoading: true, isError: false },
    );
    expect(view.tone).toBe("accent");
    expect(view.label).toBe("checking…");
    expect(view.pulse).toBe(true);
  });

  it("falls back to non-pulsing 'checking…' on a probe error", () => {
    const view = providerStatusView(
      { enabled: true },
      undefined,
      { isLoading: false, isError: true },
    );
    expect(view.tone).toBe("accent");
    expect(view.label).toBe("checking…");
    expect(view.pulse).toBe(false);
  });

  it("maps online (keyless 2xx) to green — the headline behaviour", () => {
    const health: ProviderHealth = {
      ok: true,
      status: "online",
      reachable: true,
      authed: false, // keyless, but still online
      elapsed_ms: 12,
      http_status: 200,
      detail: null,
      checked_at: "2026-07-28T00:00:00Z",
    };
    const view = providerStatusView(
      { enabled: true },
      health,
      { isLoading: false, isError: false },
    );
    expect(view).toEqual({ tone: "ok", label: "online" });
  });

  it("maps auth_needed (401/403) to yellow with the detail as a tooltip", () => {
    const health: ProviderHealth = {
      ok: false,
      status: "auth_needed",
      reachable: true,
      authed: false,
      elapsed_ms: 9,
      http_status: 401,
      detail: "HTTP 401",
      checked_at: "2026-07-28T00:00:00Z",
    };
    const view = providerStatusView(
      { enabled: true },
      health,
      { isLoading: false, isError: false },
    );
    expect(view.tone).toBe("warn");
    expect(view.label).toBe("auth needed");
    expect(view.title).toBe("HTTP 401");
  });

  it("maps offline to red", () => {
    const health: ProviderHealth = {
      ok: false,
      status: "offline",
      reachable: false,
      authed: false,
      elapsed_ms: 5000,
      http_status: null,
      detail: "ConnectError: refused",
      checked_at: "2026-07-28T00:00:00Z",
    };
    const view = providerStatusView(
      { enabled: true },
      health,
      { isLoading: false, isError: false },
    );
    expect(view.tone).toBe("danger");
    expect(view.label).toBe("offline");
    expect(view.title).toBe("ConnectError: refused");
  });
});

describe("healthStatusView", () => {
  it.each(["online", "auth_needed", "offline", "unauthorized"] as const)(
    "returns a defined tone+label for status %s",
    (status) => {
      const view = healthStatusView(status);
      expect(view.tone).toBeTruthy();
      expect(view.label.length).toBeGreaterThan(0);
    },
  );
});
