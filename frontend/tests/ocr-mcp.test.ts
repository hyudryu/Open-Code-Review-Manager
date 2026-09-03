import {
  headersToText,
  listToText,
  parseEnvLines,
  parseHeaderLines,
  parseLines,
  parseToolList,
} from "../src/lib/ocr-mcp";

describe("ocr mcp form helpers", () => {
  it("parses trimmed non-empty lines for args", () => {
    expect(parseLines("-y\n@acme/docs\n\n  \n")).toEqual(["-y", "@acme/docs"]);
    expect(parseLines("")).toEqual([]);
    expect(listToText(["-y", "@acme/docs"])).toBe("-y\n@acme/docs");
    expect(listToText(null)).toBe("");
  });

  it("parses Name: value header lines and rejects malformed ones", () => {
    expect(parseHeaderLines("Authorization: Bearer $TOKEN\nX-Region: eu")).toEqual({
      Authorization: "Bearer $TOKEN",
      "X-Region": "eu",
    });
    // A value may be empty; a missing separator may not.
    expect(parseHeaderLines("X-Empty:")).toEqual({ "X-Empty": "" });
    expect(() => parseHeaderLines("no-separator")).toThrow();
    expect(headersToText({ A: "1", B: "2" })).toBe("A: 1\nB: 2");
    expect(headersToText(null)).toBe("");
  });

  it("parses KEY=VALUE env lines and rejects missing keys", () => {
    expect(parseEnvLines("DOCS_TOKEN=secret\nEMPTY=\n")).toEqual([
      "DOCS_TOKEN=secret",
      "EMPTY=",
    ]);
    expect(() => parseEnvLines("BROKEN")).toThrow();
  });

  it("parses comma-separated tool allowlists", () => {
    expect(parseToolList("search_docs, get_page ,,")).toEqual([
      "search_docs",
      "get_page",
    ]);
    expect(parseToolList("")).toEqual([]);
  });
});
