/** Zustand — transient UI state only. Server data stays in TanStack Query. */

import { create } from "zustand";

export type ThemePreference = "system" | "light" | "dark";

export interface HistoryFilters {
  status: string;
  project_id: string;
  source: string;
  provider_id: string;
  mode: string;
  has_findings: boolean;
  has_warnings: boolean;
  search: string;
}

const EMPTY_FILTERS: HistoryFilters = {
  status: "",
  project_id: "",
  source: "",
  provider_id: "",
  mode: "",
  has_findings: false,
  has_warnings: false,
  search: "",
};

function resolveTheme(pref: ThemePreference): "light" | "dark" {
  if (pref !== "system") return pref;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function applyTheme(pref: ThemePreference) {
  document.documentElement.setAttribute("data-theme", resolveTheme(pref));
  try {
    localStorage.setItem("ocrcc.theme.pref", pref);
  } catch {
    /* storage unavailable */
  }
}

function initialPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem("ocrcc.theme.pref");
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
    const legacy = localStorage.getItem("ocrcc.theme");
    if (legacy === "light" || legacy === "dark") return legacy;
  } catch {
    /* ignore */
  }
  return "system";
}

interface UiState {
  themePreference: ThemePreference;
  setThemePreference: (pref: ThemePreference) => void;
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  historyFilters: HistoryFilters;
  setHistoryFilters: (patch: Partial<HistoryFilters>) => void;
  setupDismissed: boolean;
  dismissSetup: () => void;
}

export const useUiStore = create<UiState>((set) => ({
  themePreference: initialPreference(),
  setThemePreference: (pref) => {
    applyTheme(pref);
    set({ themePreference: pref });
  },
  sidebarOpen: false,
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  historyFilters: EMPTY_FILTERS,
  setHistoryFilters: (patch) =>
    set((state) => ({ historyFilters: { ...state.historyFilters, ...patch } })),
  setupDismissed: (() => {
    try {
      return localStorage.getItem("ocrcc.setup.dismissed") === "1";
    } catch {
      return false;
    }
  })(),
  dismissSetup: () => {
    try {
      localStorage.setItem("ocrcc.setup.dismissed", "1");
    } catch {
      /* ignore */
    }
    set({ setupDismissed: true });
  },
}));

// React to OS theme changes while preference is "system".
if (typeof window !== "undefined" && window.matchMedia) {
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", () => {
      if (useUiStore.getState().themePreference === "system") applyTheme("system");
    });
}
