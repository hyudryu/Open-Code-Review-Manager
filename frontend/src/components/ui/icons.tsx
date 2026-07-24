/**
 * Single consistent inline-SVG icon set — 16px routine, 18–20px nav,
 * uniform 1.5px stroke, outline only (SPEC §23 Icons).
 */

import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function base({ size = 16, ...props }: IconProps, paths: React.ReactNode) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {paths}
    </svg>
  );
}

export const IconOverview = (p: IconProps) =>
  base(p, <>
    <rect x="3" y="3" width="8" height="10" rx="1.5" />
    <rect x="13" y="3" width="8" height="6" rx="1.5" />
    <rect x="13" y="11" width="8" height="10" rx="1.5" />
    <rect x="3" y="15" width="8" height="6" rx="1.5" />
  </>);

export const IconProjects = (p: IconProps) =>
  base(p, <>
    <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />
  </>);

export const IconQueue = (p: IconProps) =>
  base(p, <>
    <path d="M4 6h16" />
    <path d="M4 12h16" />
    <path d="M4 18h10" />
  </>);

export const IconReviews = (p: IconProps) =>
  base(p, <>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </>);

export const IconProviders = (p: IconProps) =>
  base(p, <>
    <rect x="3" y="4" width="18" height="7" rx="1.5" />
    <rect x="3" y="13" width="18" height="7" rx="1.5" />
    <path d="M7 7.5h.01" />
    <path d="M7 16.5h.01" />
  </>);

export const IconProfiles = (p: IconProps) =>
  base(p, <>
    <path d="M4 6h10" />
    <path d="M18 6h2" />
    <circle cx="16" cy="6" r="2" />
    <path d="M4 12h4" />
    <path d="M12 12h8" />
    <circle cx="10" cy="12" r="2" />
    <path d="M4 18h12" />
    <path d="M20 18h0" />
    <circle cx="18" cy="18" r="2" />
  </>);

export const IconIntegrations = (p: IconProps) =>
  base(p, <>
    <path d="M9 7V5a2 2 0 0 1 4 0v2" />
    <path d="M7 9h10a2 2 0 0 1 2 2v1a2 2 0 0 0 0 4v1a2 2 0 0 1-2 2h-2" />
    <path d="M7 9H5a2 2 0 0 0-2 2v1a2 2 0 0 1 0 4v1a2 2 0 0 0 2 2h2" />
    <path d="M9 19h4" />
  </>);

export const IconMcp = (p: IconProps) =>
  base(p, <>
    <rect x="3" y="3" width="7" height="7" rx="1.5" />
    <rect x="14" y="14" width="7" height="7" rx="1.5" />
    <path d="M10 6.5h5.5a2 2 0 0 1 2 2V14" />
    <path d="M14 17.5H8.5a2 2 0 0 1-2-2V10" />
  </>);

export const IconDocs = (p: IconProps) =>
  base(p, <>
    <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
    <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z" />
  </>);

export const IconSettings = (p: IconProps) =>
  base(p, <>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87 1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1Z" />
  </>);

export const IconPlus = (p: IconProps) =>
  base(p, <path d="M12 5v14M5 12h14" />);

export const IconSearch = (p: IconProps) =>
  base(p, <>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </>);

export const IconRefresh = (p: IconProps) =>
  base(p, <>
    <path d="M21 12a9 9 0 1 1-2.64-6.36" />
    <path d="M21 3v6h-6" />
  </>);

export const IconCopy = (p: IconProps) =>
  base(p, <>
    <rect x="9" y="9" width="12" height="12" rx="2" />
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
  </>);

export const IconCheck = (p: IconProps) =>
  base(p, <path d="m4.5 12.5 5 5 10-11" />);

export const IconChevronDown = (p: IconProps) =>
  base(p, <path d="m6 9 6 6 6-6" />);

export const IconChevronRight = (p: IconProps) =>
  base(p, <path d="m9 6 6 6-6 6" />);

export const IconChevronLeft = (p: IconProps) =>
  base(p, <path d="m15 6-6 6 6 6" />);

export const IconClose = (p: IconProps) =>
  base(p, <path d="M6 6l12 12M18 6L6 18" />);

export const IconMore = (p: IconProps) =>
  base(p, <>
    <circle cx="5" cy="12" r="1" fill="currentColor" />
    <circle cx="12" cy="12" r="1" fill="currentColor" />
    <circle cx="19" cy="12" r="1" fill="currentColor" />
  </>);

export const IconPlay = (p: IconProps) =>
  base(p, <path d="M7 5.5v13l11-6.5-11-6.5Z" />);

export const IconPause = (p: IconProps) =>
  base(p, <path d="M8 5v14M16 5v14" />);

export const IconStop = (p: IconProps) =>
  base(p, <rect x="6" y="6" width="12" height="12" rx="1.5" />);

export const IconDownload = (p: IconProps) =>
  base(p, <>
    <path d="M12 3v12" />
    <path d="m7 11 5 5 5-5" />
    <path d="M4 20h16" />
  </>);

export const IconExternal = (p: IconProps) =>
  base(p, <>
    <path d="M14 4h6v6" />
    <path d="M20 4 11 13" />
    <path d="M19 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5" />
  </>);

export const IconBranch = (p: IconProps) =>
  base(p, <>
    <circle cx="6" cy="6" r="2.5" />
    <circle cx="6" cy="18" r="2.5" />
    <circle cx="18" cy="8" r="2.5" />
    <path d="M6 8.5v7" />
    <path d="M18 10.5c0 4.5-6 3-6 7.5" />
  </>);

export const IconTag = (p: IconProps) =>
  base(p, <>
    <path d="m3 12 9-9h9v9l-9 9-9-9Z" />
    <circle cx="16.5" cy="7.5" r="1" fill="currentColor" />
  </>);

export const IconCloud = (p: IconProps) =>
  base(p, <path d="M7 18a4.5 4.5 0 0 1-.42-8.98 6 6 0 0 1 11.58 1.4A3.75 3.75 0 0 1 17.5 18H7Z" />);

export const IconWarning = (p: IconProps) =>
  base(p, <>
    <path d="M12 3 2.5 20h19L12 3Z" />
    <path d="M12 10v4" />
    <path d="M12 17h.01" />
  </>);

export const IconInfo = (p: IconProps) =>
  base(p, <>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5" />
    <path d="M12 8h.01" />
  </>);

export const IconGrip = (p: IconProps) =>
  base(p, <>
    <circle cx="9" cy="6" r="1" fill="currentColor" />
    <circle cx="15" cy="6" r="1" fill="currentColor" />
    <circle cx="9" cy="12" r="1" fill="currentColor" />
    <circle cx="15" cy="12" r="1" fill="currentColor" />
    <circle cx="9" cy="18" r="1" fill="currentColor" />
    <circle cx="15" cy="18" r="1" fill="currentColor" />
  </>);

export const IconFile = (p: IconProps) =>
  base(p, <>
    <path d="M6 2h8l5 5v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Z" />
    <path d="M14 2v6h6" />
  </>);

export const IconFolder = (p: IconProps) =>
  base(p, <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />);

export const IconMenu = (p: IconProps) =>
  base(p, <path d="M4 7h16M4 12h16M4 17h16" />);

export const IconTerminal = (p: IconProps) =>
  base(p, <>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="m7 9 3 3-3 3" />
    <path d="M12.5 15H17" />
  </>);

export const IconClock = (p: IconProps) =>
  base(p, <>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" />
  </>);

export const IconKey = (p: IconProps) =>
  base(p, <>
    <circle cx="8" cy="15" r="4" />
    <path d="m11 12 9-9" />
    <path d="m15 8 2.5 2.5" />
    <path d="m18 5 2 2" />
  </>);

export const IconArrowUp = (p: IconProps) =>
  base(p, <path d="M12 19V5m-6 6 6-6 6 6" />);

export const IconArrowDown = (p: IconProps) =>
  base(p, <path d="M12 5v14m-6-6 6 6 6-6" />);

export const IconArrowTop = (p: IconProps) =>
  base(p, <path d="M12 19V7m-6 4 6-6 6 6M6 3h12" />);

export const IconDuplicate = (p: IconProps) =>
  base(p, <>
    <rect x="8" y="8" width="12" height="12" rx="2" />
    <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" />
  </>);

export const IconRetry = (p: IconProps) =>
  base(p, <>
    <path d="M3 12a9 9 0 1 0 2.64-6.36" />
    <path d="M3 3v6h6" />
  </>);
