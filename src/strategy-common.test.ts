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
