/**
 * Expert "additional arguments" parser (SPEC §8).
 *
 * Parses a free-text field into an argv array. Shell metacharacter
 * interpretation is rejected outright; arguments that would conflict with
 * control-plane-owned flags are refused.
 */

export interface ParsedArgs {
  ok: boolean;
  argv: string[];
  error: string | null;
}

/** Flags owned by the control plane — users may not override them here. */
const CONTROL_PLANE_OWNED = new Set([
  "--repo",
  "--from",
  "--to",
  "--commit",
  "--format",
  "--audience",
  "--resume",
  "--preview",
  "--background",
  "--background-file",
  "--exclude",
  "--rule",
  "--tools",
  "--model",
  "--concurrency",
  "--timeout",
  "--max-tools",
  "--max-git-procs",
  "--plan-mode",
  "--plan-threshold",
  "--max-tokens",
  "--template",
]);

/** Characters that would acquire special meaning inside a shell. */
const SHELL_METACHARS = /[;&|`$<>\\*?[\]{}()!#~\n\r]/;

export function parseAdditionalArgs(input: string): ParsedArgs {
  const trimmed = input.trim();
  if (!trimmed) return { ok: true, argv: [], error: null };

  const argv: string[] = [];
  let current = "";
  let quote: "'" | '"' | null = null;
  let tokenStarted = false;

  for (let i = 0; i < trimmed.length; i += 1) {
    const ch = trimmed[i];
    if (quote) {
      if (ch === quote) {
        quote = null;
      } else {
        if (SHELL_METACHARS.test(ch)) {
          return {
            ok: false,
            argv: [],
            error: `The character "${ch}" is not allowed — arguments are passed directly to the process, never through a shell.`,
          };
        }
        current += ch;
      }
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch;
      tokenStarted = true;
      continue;
    }
    if (/\s/.test(ch)) {
      if (tokenStarted || current) {
        argv.push(current);
        current = "";
        tokenStarted = false;
      }
      continue;
    }
    if (SHELL_METACHARS.test(ch)) {
      return {
        ok: false,
        argv: [],
        error: `The character "${ch}" is not allowed — arguments are passed directly to the process, never through a shell.`,
      };
    }
    current += ch;
    tokenStarted = true;
  }

  if (quote) {
    return { ok: false, argv: [], error: "Unterminated quote in additional arguments." };
  }
  if (tokenStarted || current) argv.push(current);

  for (const arg of argv) {
    const flag = arg.startsWith("--") ? arg.split("=")[0] : null;
    if (flag && CONTROL_PLANE_OWNED.has(flag)) {
      return {
        ok: false,
        argv: [],
        error: `"${flag}" is controlled by the control plane and cannot be overridden here.`,
      };
    }
    if (arg.startsWith("-") && !arg.startsWith("--") && arg.length > 2) {
      return {
        ok: false,
        argv: [],
        error: `Short-flag bundles like "${arg}" are not supported; use long flags.`,
      };
    }
  }

  return { ok: true, argv, error: null };
}
