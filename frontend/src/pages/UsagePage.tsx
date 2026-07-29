/** Usage (SPEC §20) — analytics dashboard with histograms and time range selector. */

import { useMemo, useState } from "react";
import { useJobs } from "../api/hooks";
import { PageHeader } from "../layouts/AppLayout";
import { Skeleton } from "../components/ui";
import { formatTokens } from "../lib/format";
import { TERMINAL_STATUSES, type Job } from "../types";
import layout from "../layouts/layout.module.css";
import styles from "./pages.module.css";

type RangeKey = "1d" | "7d" | "30d" | "custom";

const RANGE_LABELS: Record<RangeKey, string> = {
  "1d": "1D",
  "7d": "7D",
  "30d": "30D",
  custom: "Custom",
};

interface DayBucket {
  date: Date;
  label: string;
  findings: number;
  tokens: number;
  reviews: number;
}

/** Build daily buckets covering [startDate, today] inclusive. */
function buildBuckets(jobs: Job[], startDate: Date): DayBucket[] {
  const buckets: DayBucket[] = [];
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  for (let d = new Date(startDate); d <= today; d.setDate(d.getDate() + 1)) {
    const dayKey = d.toDateString();
    const dayJobs = jobs.filter(
      (j) => j.completed_at && new Date(j.completed_at).toDateString() === dayKey,
    );
    buckets.push({
      date: new Date(d),
      label: d.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
      findings: dayJobs.reduce(
        (sum, j) => sum + (j.result_summary_json?.comments ?? j.findings_count ?? 0),
        0,
      ),
      tokens: dayJobs.reduce(
        (sum, j) => sum + (j.result_summary_json?.total_tokens ?? 0),
        0,
      ),
      reviews: dayJobs.length,
    });
  }
  return buckets;
}

function startDateForRange(range: RangeKey, customFrom: string): Date {
  if (range === "custom") {
    const d = new Date(customFrom);
    if (!Number.isNaN(d.getTime())) {
      d.setHours(0, 0, 0, 0);
      return d;
    }
  }
  const days = range === "1d" ? 0 : range === "7d" ? 6 : 29;
  const d = new Date();
  d.setDate(d.getDate() - days);
  d.setHours(0, 0, 0, 0);
  return d;
}

/** Reusable histogram chart with hover tooltips. */
function Histogram({
  buckets,
  metric,
  color,
  formatValue,
}: {
  buckets: DayBucket[];
  metric: "findings" | "tokens";
  color: string;
  formatValue: (n: number) => string;
}) {
  const [hovered, setHovered] = useState<number | null>(null);
  const max = Math.max(1, ...buckets.map((b) => b[metric]));

  if (buckets.length === 0) {
    return <p className={layout.small}>No data in this range.</p>;
  }

  return (
    <div className={styles.usageChartArea}>
      <div className={styles.usageChart}>
        {buckets.map((b, i) => {
          const value = b[metric];
          const heightPct = Math.max(2, (value / max) * 100);
          const isHovered = hovered === i;
          return (
            <div
              key={i}
              className={styles.usageBarWrap}
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered(null)}
            >
              {isHovered && value > 0 ? (
                <div className={styles.usageBarTooltip}>
                  <span className={styles.usageBarTooltipDate}>{b.label}</span>
                  <span className={styles.usageBarTooltipValue}>
                    {formatValue(value)}
                  </span>
                </div>
              ) : null}
              <div
                className={`${styles.usageBar} ${value === 0 ? styles.usageBarEmpty : ""}`}
                style={{
                  height: `${heightPct}%`,
                  background: value === 0 ? undefined : color,
                  opacity: isHovered ? 1 : 0.8,
                }}
              />
            </div>
          );
        })}
      </div>
      <div className={styles.usageChartAxis}>
        <span>{buckets[0]?.label}</span>
        <span>{buckets[buckets.length - 1]?.label}</span>
      </div>
    </div>
  );
}

export function UsagePage() {
  const jobsQuery = useJobs({ limit: 200 });

  const [range, setRange] = useState<RangeKey>("7d");
  const today = new Date().toISOString().slice(0, 10);
  const [customFrom, setCustomFrom] = useState(
    new Date(Date.now() - 6 * 86_400_000).toISOString().slice(0, 10),
  );

  const startDate = startDateForRange(range, customFrom);

  const terminalJobs = useMemo(
    () =>
      (jobsQuery.data?.items ?? []).filter(
        (j) =>
          TERMINAL_STATUSES.includes(j.status) &&
          j.completed_at &&
          new Date(j.completed_at) >= startDate,
      ),
    [jobsQuery.data, startDate],
  );

  const buckets = useMemo(
    () => buildBuckets(terminalJobs, startDate),
    [terminalJobs, startDate],
  );

  const totals = useMemo(() => {
    const totalFindings = buckets.reduce((s, b) => s + b.findings, 0);
    const totalTokens = buckets.reduce((s, b) => s + b.tokens, 0);
    const totalReviews = buckets.reduce((s, b) => s + b.reviews, 0);
    return {
      findings: totalFindings,
      tokens: totalTokens,
      reviews: totalReviews,
      avgTokens: totalReviews > 0 ? Math.round(totalTokens / totalReviews) : 0,
    };
  }, [buckets]);

  return (
    <>
      <PageHeader
        title="Usage"
        subtitle="Token consumption and review findings over time."
        actions={
          <div className={styles.usageRangeSelector}>
            {(Object.keys(RANGE_LABELS) as RangeKey[]).map((key) => (
              <button
                key={key}
                type="button"
                className={`${styles.usageRangeBtn} ${range === key ? styles.usageRangeBtnActive : ""}`}
                onClick={() => setRange(key)}
              >
                {RANGE_LABELS[key]}
              </button>
            ))}
          </div>
        }
      />

      {range === "custom" ? (
        <div className={styles.usageCustomRange}>
          <label className={layout.small}>
            From
            <input
              type="date"
              value={customFrom}
              max={today}
              onChange={(e) => setCustomFrom(e.target.value)}
              className={styles.usageDateInput}
            />
          </label>
          <span className={layout.small}>to today</span>
        </div>
      ) : null}

      {/* Summary stat cards */}
      <div className={styles.usageStats}>
        <div className={styles.usageStatCard}>
          <span className={styles.usageStatValue}>{totals.reviews}</span>
          <span className={styles.usageStatLabel}>Reviews</span>
        </div>
        <div className={styles.usageStatCard}>
          <span className={styles.usageStatValue}>{totals.findings}</span>
          <span className={styles.usageStatLabel}>Findings</span>
        </div>
        <div className={styles.usageStatCard}>
          <span className={styles.usageStatValue}>{formatTokens(totals.tokens)}</span>
          <span className={styles.usageStatLabel}>Tokens</span>
        </div>
        <div className={styles.usageStatCard}>
          <span className={styles.usageStatValue}>{formatTokens(totals.avgTokens)}</span>
          <span className={styles.usageStatLabel}>Avg / review</span>
        </div>
      </div>

      {jobsQuery.isLoading ? (
        <div className={styles.usageCharts}>
          <Skeleton height={200} />
          <Skeleton height={200} />
        </div>
      ) : (
        <div className={styles.usageCharts}>
          <div className={styles.usageChartCard}>
            <h3 className={styles.usageChartTitle}>Findings per day</h3>
            <Histogram
              buckets={buckets}
              metric="findings"
              color="var(--accent)"
              formatValue={(n) => `${n} ${n === 1 ? "finding" : "findings"}`}
            />
          </div>
          <div className={styles.usageChartCard}>
            <h3 className={styles.usageChartTitle}>Tokens per day</h3>
            <Histogram
              buckets={buckets}
              metric="tokens"
              color="var(--success)"
              formatValue={(n) => `${formatTokens(n)} tokens`}
            />
          </div>
        </div>
      )}
    </>
  );
}
