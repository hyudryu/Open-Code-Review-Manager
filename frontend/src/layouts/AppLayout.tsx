import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useQueue, useSystemOcr } from "../api/hooks";
import { useUiStore, syncThemeToDom } from "../hooks/store";
import { Button, StatusDot } from "../components/ui";
import {
  IconDocs,
  IconIntegrations,
  IconMcp,
  IconMenu,
  IconOverview,
  IconProfiles,
  IconProjects,
  IconProviders,
  IconQueue,
  IconReviews,
  IconSettings,
} from "../components/ui/icons";
import styles from "./layout.module.css";

const NAV = [
  { to: "/", label: "Overview", icon: <IconOverview size={19} />, end: true },
  { to: "/projects", label: "Projects", icon: <IconProjects size={19} /> },
  { to: "/queue", label: "Queue", icon: <IconQueue size={19} /> },
  { to: "/reviews", label: "Reviews", icon: <IconReviews size={19} /> },
  { to: "/providers", label: "Providers", icon: <IconProviders size={19} /> },
  { to: "/profiles", label: "Profiles", icon: <IconProfiles size={19} /> },
  { to: "/integrations", label: "Integrations", icon: <IconIntegrations size={19} /> },
  { to: "/mcp", label: "MCP", icon: <IconMcp size={19} /> },
  { to: "/docs", label: "Docs", icon: <IconDocs size={19} /> },
  { to: "/settings", label: "Settings", icon: <IconSettings size={19} /> },
];

function Sidebar() {
  const { sidebarOpen, setSidebarOpen } = useUiStore();
  const queue = useQueue({ refetchInterval: 15_000 });
  const ocr = useSystemOcr();
  const location = useLocation();

  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname, setSidebarOpen]);

  const queuedCount =
    queue.data?.jobs.filter((j) => j.status === "queued").length ?? 0;

  return (
    <>
      {sidebarOpen ? (
        <div
          className={styles.scrim}
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      ) : null}
      <nav
        className={`${styles.sidebar} ${sidebarOpen ? styles.sidebarOpen : ""}`}
        aria-label="Primary"
      >
        <div className={styles.brand}>
          <span className={styles.brandMark}>OC</span>
          <span>OCR Manager</span>
        </div>
        <div className={styles.nav}>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `${styles.navLink} ${isActive ? styles.navLinkActive : ""}`
              }
            >
              {item.icon}
              <span>{item.label}</span>
              {item.to === "/queue" && queuedCount > 0 ? (
                <span className={styles.navBadge} aria-label={`${queuedCount} queued jobs`}>
                  {queuedCount}
                </span>
              ) : null}
            </NavLink>
          ))}
        </div>
        <div className={styles.sidebarFooter}>
          {ocr.data ? (
            <StatusDot
              tone={ocr.data.status === "ok" ? "ok" : "warn"}
              label={
                ocr.data.status === "ok"
                  ? `OCR ${ocr.data.version ?? "detected"}`
                  : "OCR not found"
              }
            />
          ) : (
            <StatusDot tone="muted" label="Checking OCR…" />
          )}
        </div>
      </nav>
    </>
  );
}

/** Prime the CSRF cookie on mount so mutations don't get a stale 403. */
function useCsrfPrime() {
  return useQuery({
    queryKey: ["csrf-prime"],
    queryFn: () => api.get("/api/v1/health"),
    staleTime: Infinity, // prime once per session
  });
}

export function AppLayout() {
  useCsrfPrime();
  const { sidebarOpen, setSidebarOpen } = useUiStore();
  // Reconcile the DOM theme with the (hydrated) store value on mount and
  // whenever the preference changes. The inline index.html shim only sets the
  // first paint; without this, refreshes could render the wrong theme even
  // though the selector showed the right one.
  const themePreference = useUiStore((s) => s.themePreference);
  useEffect(() => {
    syncThemeToDom();
  }, [themePreference]);
  return (
    <div className={styles.shell}>
      <Sidebar />
      <div className={styles.main}>
        <div className={styles.topbar}>
          <Button
            variant="tertiary"
            className=""
            onClick={() => setSidebarOpen(!sidebarOpen)}
            aria-label="Toggle navigation"
          >
            <IconMenu size={20} />
          </Button>
          <span className={styles.brand}>
            <span className={styles.brandMark}>OC</span>
            <span>OCR Manager</span>
          </span>
        </div>
        <main className={styles.content} id="main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <header className={styles.pageHeader}>
      <div className={styles.pageTitleGroup}>
        <h1 className={styles.pageTitle}>{title}</h1>
        {subtitle ? <p className={styles.pageSubtitle}>{subtitle}</p> : null}
      </div>
      {actions ? <div className={styles.pageActions}>{actions}</div> : null}
    </header>
  );
}
