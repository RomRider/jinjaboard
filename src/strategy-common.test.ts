import { describe, expect, it, vi } from "vitest";

import { createStrategyGenerate, errorCard } from "./strategy-common";
import type { HomeAssistant, JinjaboardWsError } from "./types";

function mockHass(callWS: HomeAssistant["callWS"]): HomeAssistant {
  return { callWS };
}

describe("errorCard", () => {
  it("formats a {code, message} error into a markdown card", () => {
    const card = errorCard({ code: "template_error", message: "Line 3: boom" });

    expect(card.type).toBe("markdown");
    expect(card.content).toContain("template_error");
    expect(card.content).toContain("Line 3: boom");
  });

  it("wraps the whole card in {% raw %} so embedded {{ }}/{% %} isn't re-evaluated as a live template", () => {
    // The markdown card auto-detects `{{`/`{%` anywhere in `content` and
    // sends the whole string through core's `render_template` for live
    // evaluation (confirmed live: without this escape, a message quoting
    // the user's own broken Jinja syntax rendered the whole card blank).
    const card = errorCard({
      code: "template_error",
      message: "Line 3: \"{{ totally_undefined }}\" is undefined",
    });

    expect(card.content.startsWith("{% raw %}")).toBe(true);
    expect(card.content.trimEnd().endsWith("{% endraw %}")).toBe(true);
    expect(card.content).toContain("{{ totally_undefined }}");
  });

  it("soft-wraps a long single-line message instead of letting it overflow", () => {
    const longMessage =
      "in included file 'nested/middle.yaml.j2' (included at line 2): " +
      "in included file 'leaf.yaml.j2' (included at line 2): " +
      "Line 1: UndefinedError: 'totally_undefined' is undefined";
    const card = errorCard({ code: "template_error", message: longMessage });

    const codeBlockLines = card.content
      .split("```")[1]
      .trim()
      .split("\n");
    expect(codeBlockLines.length).toBeGreaterThan(1);
    for (const line of codeBlockLines) {
      expect(line.length).toBeLessThanOrEqual(60);
    }
    expect(codeBlockLines.join(" ")).toBe(longMessage);
  });
});

describe("createStrategyGenerate", () => {
  it("calls the error builder without calling callWS when template is missing", async () => {
    const callWS = vi.fn();
    const buildErrorResult = vi.fn().mockReturnValue({ cards: [] });
    const generate = createStrategyGenerate(buildErrorResult);

    await generate({}, mockHass(callWS));

    expect(callWS).not.toHaveBeenCalled();
    expect(buildErrorResult).toHaveBeenCalledWith(
      expect.objectContaining({
        code: "template_error",
        message: expect.stringContaining("options.template is required"),
      }),
    );
  });

  it("passes through a successful WS result unchanged", async () => {
    const wsResult = { views: [{ title: "Home" }] };
    const generate = createStrategyGenerate(vi.fn());

    const result = await generate(
      { template: "home.yaml.j2" },
      mockHass(vi.fn().mockResolvedValue(wsResult)),
    );

    expect(result).toBe(wsResult);
  });

  it("forwards template and globals to the WS call", async () => {
    const callWS = vi.fn().mockResolvedValue({ views: [] });
    const generate = createStrategyGenerate(vi.fn());

    await generate(
      { template: "home.yaml.j2", globals: { area_id: "kitchen" } },
      mockHass(callWS),
    );

    expect(callWS).toHaveBeenCalledWith({
      type: "jinjaboard/render",
      template: "home.yaml.j2",
      globals: { area_id: "kitchen" },
    });
  });

  it("forwards macros to the WS call", async () => {
    const callWS = vi.fn().mockResolvedValue({ views: [] });
    const generate = createStrategyGenerate(vi.fn());

    await generate(
      { template: "home.yaml.j2", macros: ["macros/common.yaml.j2"] },
      mockHass(callWS),
    );

    expect(callWS).toHaveBeenCalledWith({
      type: "jinjaboard/render",
      template: "home.yaml.j2",
      globals: undefined,
      macros: ["macros/common.yaml.j2"],
    });
  });

  it("calls the error builder with the rejected error on WS failure", async () => {
    const error: JinjaboardWsError = { code: "template_error", message: "Line 3: boom" };
    const buildErrorResult = vi.fn().mockReturnValue({ cards: [] });
    const generate = createStrategyGenerate(buildErrorResult);

    await generate({ template: "home.yaml.j2" }, mockHass(vi.fn().mockRejectedValue(error)));

    expect(buildErrorResult).toHaveBeenCalledWith(error);
  });
});
