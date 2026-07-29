/**
 * Theme persistence: the user's choice must survive a page reload.
 *
 * Root cause of the original bug: the store wrote localStorage under
 * "ocrcc.theme.pref" but (a) the inline index.html anti-flash script read a
 * different key ("ocrcc.theme"), and (b) nothing on the React side reapplied
 * the theme after hydration. These tests pin both fixes.
 */

import { describe, expect, it, beforeEach, vi } from "vitest";

// jsdom provides localStorage and documentElement; matchMedia is stubbed in
// setup.ts. Force a deterministic OS preference for "system" resolution.
beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  vi.stubGlobal(
    "matchMedia",
    (query: string) => ({
      matches: false, // OS prefers light
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    }),
  );
});

describe("theme persistence across reload", () => {
  it("persists 'dark' under ocrcc.theme.pref and applies data-theme=dark", async () => {
    const { useUiStore } = await import("../src/hooks/store");
    useUiStore.getState().setThemePreference("dark");
    expect(localStorage.getItem("ocrcc.theme.pref")).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("reapplies the persisted theme after a simulated reload", async () => {
    // Seed localStorage as if the user previously chose dark, then load the
    // store fresh (module re-init == page reload).
    localStorage.setItem("ocrcc.theme.pref", "dark");

    vi.resetModules();
    const { useUiStore, syncThemeToDom } = await import("../src/hooks/store");

    // The store hydrates to the persisted value.
    expect(useUiStore.getState().themePreference).toBe("dark");
    // The DOM may not yet reflect it (the inline shim sets first paint); the
    // React mount effect calls syncThemeToDom() to reconcile.
    document.documentElement.setAttribute("data-theme", "light"); // simulate stale first paint
    syncThemeToDom();
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("resolves 'system' to the OS preference (light here)", async () => {
    localStorage.setItem("ocrcc.theme.pref", "system");
    vi.resetModules();
    const { syncThemeToDom } = await import("../src/hooks/store");
    syncThemeToDom();
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
});
