import { render, screen } from "@testing-library/react";
import { ModelBreakdown } from "../src/pages/UsagePage";
import type { Job } from "../src/types";

describe("model usage breakdown", () => {
  it("lays out disjoint token categories as visible horizontal segments", () => {
    const job = {
      configuration_snapshot_json: { model: { model_id: "model-a" } },
      result_summary_json: {
        total_tokens: 1_200,
        input_tokens: 1_000,
        output_tokens: 200,
        cache_read_tokens: 600,
        cache_write_tokens: 100,
      },
    } as unknown as Job;

    render(<ModelBreakdown jobs={[job]} />);

    const track = screen.getByTestId("model-usage-bar");
    expect(getComputedStyle(track).display).toBe("flex");
    expect(track.children).toHaveLength(4);
    const totalWidth = Array.from(track.children).reduce(
      (sum, segment) => sum + Number.parseFloat((segment as HTMLElement).style.width),
      0,
    );
    expect(totalWidth).toBeCloseTo(100);
  });
});
