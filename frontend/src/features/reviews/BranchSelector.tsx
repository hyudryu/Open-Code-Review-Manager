/**
 * Branch selector (SPEC §6): grouped Local / Remote / Tags, search, commit
 * subject + relative time, current/default markers, full keyboard support.
 */

import * as Popover from "@radix-ui/react-popover";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import type { Branch, BranchKind } from "../../types";
import { relativeTime, shortSha } from "../../lib/format";
import { Badge } from "../../components/ui";
import {
  IconBranch,
  IconChevronDown,
  IconCloud,
  IconTag,
} from "../../components/ui/icons";
import styles from "./reviews.module.css";
import popoverStyles from "../../components/ui/ui.module.css";

const GROUP_ORDER: { kind: BranchKind; label: string; icon: React.ReactNode }[] = [
  { kind: "local", label: "Local", icon: <IconBranch size={12} /> },
  { kind: "remote", label: "Remote", icon: <IconCloud size={12} /> },
  { kind: "tag", label: "Tags", icon: <IconTag size={12} /> },
];

export function groupBranches(branches: Branch[], query: string) {
  const q = query.trim().toLowerCase();
  const filtered = q
    ? branches.filter(
        (b) =>
          b.name.toLowerCase().includes(q) ||
          b.full_ref.toLowerCase().includes(q) ||
          (b.commit_subject ?? "").toLowerCase().includes(q),
      )
    : branches;
  return GROUP_ORDER.map((group) => ({
    ...group,
    items: filtered.filter((b) => b.kind === group.kind),
  })).filter((group) => group.items.length > 0);
}

export interface BranchSelectorProps {
  branches: Branch[];
  value: string | null;
  onChange: (branchName: string, branch: Branch | null) => void;
  placeholder?: string;
  disabled?: boolean;
  kinds?: BranchKind[];
  id?: string;
  ariaLabel?: string;
}

export function BranchSelector({
  branches,
  value,
  onChange,
  placeholder = "Select a branch",
  disabled,
  kinds,
  id,
  ariaLabel,
}: BranchSelectorProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const listRef = useRef<HTMLDivElement | null>(null);

  const available = useMemo(
    () => (kinds ? branches.filter((b) => kinds.includes(b.kind)) : branches),
    [branches, kinds],
  );
  const groups = useMemo(() => groupBranches(available, query), [available, query]);
  const flat = useMemo(() => groups.flatMap((g) => g.items), [groups]);

  const selected = useMemo(
    () => branches.find((b) => b.name === value) ?? null,
    [branches, value],
  );

  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIndex(0);
    }
  }, [open]);

  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>('[data-active="true"]');
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  function select(branch: Branch) {
    onChange(branch.name, branch);
    setOpen(false);
  }

  function onKeyDown(event: ReactKeyboardEvent) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, flat.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const branch = flat[activeIndex];
      if (branch) select(branch);
    } else if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
    }
  }

  let optionIndex = -1;

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild disabled={disabled}>
        <button
          type="button"
          id={id}
          className={styles.trigger}
          aria-label={ariaLabel ?? placeholder}
          aria-haspopup="listbox"
          aria-expanded={open}
          disabled={disabled}
        >
          <span
            className={`${styles.triggerValue} ${selected ? "" : styles.triggerPlaceholder}`}
          >
            {selected ? selected.name : placeholder}
          </span>
          <IconChevronDown size={14} />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          className={`${popoverStyles.popoverContent} ${styles.popover}`}
          align="start"
          sideOffset={4}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            listRef.current
              ?.querySelector<HTMLInputElement>("input")
              ?.focus();
          }}
        >
          <div className={styles.searchRow}>
            <input
              className={styles.searchInput}
              placeholder="Search branches…"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setActiveIndex(0);
              }}
              onKeyDown={onKeyDown}
              aria-label="Search branches"
              role="combobox"
              aria-expanded="true"
              aria-controls={id ? `${id}-list` : undefined}
              aria-activedescendant={
                flat[activeIndex] ? `branch-option-${flat[activeIndex].id}` : undefined
              }
            />
          </div>
          <div className={styles.list} role="listbox" ref={listRef} aria-label="Branches">
            {flat.length === 0 ? (
              <p className={styles.optionEmpty}>
                {available.length === 0
                  ? "No branches cached — refresh branches first."
                  : "No branches match the search."}
              </p>
            ) : (
              groups.map((group) => (
                <div key={group.kind} role="group" aria-label={group.label}>
                  <div className={styles.groupLabel}>
                    {group.icon}
                    <span>{group.label}</span>
                    <span>({group.items.length})</span>
                  </div>
                  {group.items.map((branch) => {
                    optionIndex += 1;
                    const idx = optionIndex;
                    return (
                      <button
                        key={branch.id}
                        id={`branch-option-${branch.id}`}
                        type="button"
                        role="option"
                        aria-selected={branch.name === value}
                        data-active={idx === activeIndex}
                        className={[
                          styles.option,
                          idx === activeIndex ? styles.optionActive : "",
                          branch.name === value ? styles.optionSelected : "",
                        ]
                          .filter(Boolean)
                          .join(" ")}
                        onClick={() => select(branch)}
                        onMouseEnter={() => setActiveIndex(idx)}
                      >
                        <span className={styles.optionTop}>
                          <span className={styles.optionName}>
                            {branch.kind === "remote" && branch.remote_name
                              ? `${branch.remote_name}/${branch.name}`
                              : branch.name}
                          </span>
                          {branch.is_current ? <Badge tone="accent">current</Badge> : null}
                          {branch.is_default ? <Badge>default</Badge> : null}
                          {branch.commit_sha ? (
                            <span className={styles.optionMeta}>
                              {shortSha(branch.commit_sha)}
                            </span>
                          ) : null}
                        </span>
                        <span className={styles.optionMeta}>
                          <span className={styles.optionSubject}>
                            {branch.commit_subject ?? branch.full_ref}
                          </span>
                          <span>{relativeTime(branch.commit_timestamp)}</span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              ))
            )}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
