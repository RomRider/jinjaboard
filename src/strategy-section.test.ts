import { describe, expect, it, vi } from "vitest";

import "./strategy-section";
import { shouldRegenerateJinjaboard } from "./strategy-common";
import type { HomeAssistant, JinjaboardWsError } from "./types";

function mockHass(
  callWS: HomeAssistant["callWS"],
  subscribeMessage: HomeAssistant["connection"]["subscribeMessage"] = vi.fn(),
): HomeAssistant {
  return { callWS, connection: { subscribeMessage } };
}

type Generate = (config: unknown, hass: HomeAssistant) => Promise<any>;

function getGenerate(): Generate {
  const ElementClass = customElements.get("ll-strategy-section-jinjaboard") as
    | { generate: Generate }
    | undefined;
  if (!ElementClass) {
    throw new Error("ll-strategy-section-jinjaboard was not registered");
  }
  return ElementClass.generate;
}

describe("ll-strategy-section-jinjaboard", () => {
  it("registers itself as a custom element", () => {
    expect(customElements.get("ll-strategy-section-jinjaboard")).toBeDefined();
  });

  it("does not register a create-dashboard suggestion", () => {
    expect(window.customStrategies ?? []).not.toContainEqual(
      expect.objectContaining({ strategyType: "section" }),
    );
  });

  it("wires static shouldRegenerate to the shared helper", () => {
    const ElementClass = customElements.get("ll-strategy-section-jinjaboard") as unknown as {
      shouldRegenerate: unknown;
    };
    expect(ElementClass.shouldRegenerate).toBe(shouldRegenerateJinjaboard);
  });

  it("returns a section-shaped error without calling callWS when template is missing", async () => {
    const callWS = vi.fn();
    const generate = getGenerate();

    const result = await generate({}, mockHass(callWS));

    expect(callWS).not.toHaveBeenCalled();
    expect(result.views).toBeUndefined();
    const content = result.cards[0].content as string;
    expect(content).toContain("template_error");
    expect(content).toContain("options.template is required");
  });

  it("passes through a successful WS result unchanged", async () => {
    const wsResult = { cards: [{ type: "markdown", content: "hi" }] };
    const generate = getGenerate();

    const result = await generate(
      { template: "section.yaml.j2" },
      mockHass(vi.fn().mockResolvedValue(wsResult)),
    );

    expect(result).toBe(wsResult);
  });

  it("forwards template and globals to the WS call", async () => {
    const callWS = vi.fn().mockResolvedValue({ cards: [] });
    const generate = getGenerate();

    await generate(
      { template: "section.yaml.j2", globals: { area_id: "kitchen" } },
      mockHass(callWS),
    );

    expect(callWS).toHaveBeenCalledWith({
      type: "jinjaboard/render",
      template: "section.yaml.j2",
      globals: { area_id: "kitchen" },
    });
  });

  it("returns a section-shaped error with the code and message on WS rejection", async () => {
    const error: JinjaboardWsError = { code: "template_error", message: "Line 3: boom" };
    const generate = getGenerate();

    const result = await generate(
      { template: "section.yaml.j2" },
      mockHass(vi.fn().mockRejectedValue(error)),
    );

    expect(result.views).toBeUndefined();
    const content = result.cards[0].content as string;
    expect(content).toContain("template_error");
    expect(content).toContain("Line 3: boom");
  });
});
