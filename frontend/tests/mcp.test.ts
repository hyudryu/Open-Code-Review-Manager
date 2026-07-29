import { describe, expect, it } from "vitest";
import {
  MCP_PROMPTS,
  MCP_RESOURCES,
  MCP_TOOLS,
  buildMcpClientConfig,
  formatProviderTestSuccess,
} from "../src/lib/mcp";

describe("buildMcpClientConfig", () => {
  it("produces parseable JSON with the streamable-http server entry", () => {
    const config = buildMcpClientConfig("http://127.0.0.1:8372/mcp");
    const parsed = JSON.parse(config);
    expect(parsed.mcpServers["ocr-control-center"]).toEqual({
      type: "http",
      url: "http://127.0.0.1:8372/mcp",
    });
  });
});

describe("formatProviderTestSuccess", () => {
  it("shows the reply excerpt with elapsed time", () => {
    expect(formatProviderTestSuccess({ elapsed_ms: 842.4, reply: "hi" })).toBe(
      'Responded in 842 ms: "hi"',
    );
  });

  it("falls back to a generic success line without a reply", () => {
    expect(formatProviderTestSuccess({ elapsed_ms: 120 })).toBe(
      "Connection successful in 120 ms",
    );
    expect(formatProviderTestSuccess({})).toBe("Connection successful");
  });
});

describe("MCP surface metadata", () => {
  it("matches the backend server surface (12 tools, 7 resources, 5 prompts)", () => {
    expect(MCP_TOOLS).toHaveLength(12);
    expect(MCP_RESOURCES).toHaveLength(7);
    expect(MCP_PROMPTS).toHaveLength(5);
  });

  it("every entry has a non-empty description", () => {
    for (const tool of MCP_TOOLS) expect(tool.description.length).toBeGreaterThan(0);
    for (const res of MCP_RESOURCES) expect(res.description.length).toBeGreaterThan(0);
    for (const prompt of MCP_PROMPTS) expect(prompt.description.length).toBeGreaterThan(0);
  });
});
