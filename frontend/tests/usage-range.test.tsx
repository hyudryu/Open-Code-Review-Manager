import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";

vi.mock("../src/api/hooks", () => ({
  useJobs: () => ({ data: { items: [] }, isLoading: false }),
}));

import {
  UsagePage,
  buildBuckets,
  dateBoundsForRange,
  isDateInRange,
} from "../src/pages/UsagePage";

describe("usage date ranges", () => {
  it("offers 7D, 30D, and a custom start/end range", () => {
    render(<UsagePage />);

    expect(screen.queryByRole("button", { name: "1D" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "7D" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "30D" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Custom" }));
    expect(screen.getByLabelText("From")).toHaveAttribute("type", "date");
    expect(screen.getByLabelText("To")).toHaveAttribute("type", "date");
  });

  it("uses both custom start and end dates inclusively", () => {
    const { startDate, endDate } = dateBoundsForRange(
      "custom",
      "2026-07-10",
      "2026-07-12",
      new Date(2026, 6, 29, 12),
    );

    expect([startDate.getFullYear(), startDate.getMonth(), startDate.getDate()]).toEqual([
      2026,
      6,
      10,
    ]);
    expect([endDate.getFullYear(), endDate.getMonth(), endDate.getDate()]).toEqual([
      2026,
      6,
      12,
    ]);
    expect(buildBuckets([], startDate, endDate)).toHaveLength(3);
    expect(
      isDateInRange(new Date(2026, 6, 12, 23, 59, 59).toISOString(), startDate, endDate),
    ).toBe(true);
    expect(
      isDateInRange(new Date(2026, 6, 13, 0, 0, 0).toISOString(), startDate, endDate),
    ).toBe(false);
  });

  it("keeps the preset ranges ending today", () => {
    const now = new Date(2026, 6, 29, 12);
    const sevenDays = dateBoundsForRange("7d", "", "", now);
    const thirtyDays = dateBoundsForRange("30d", "", "", now);

    expect(buildBuckets([], sevenDays.startDate, sevenDays.endDate)).toHaveLength(7);
    expect(buildBuckets([], thirtyDays.startDate, thirtyDays.endDate)).toHaveLength(30);
  });
});
