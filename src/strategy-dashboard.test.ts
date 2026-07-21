import { describe, expect, it, vi } from "vitest";

import "./strategy-dashboard";
import type { HomeAssistant, JinjaboardWsError } from "./types";

function mockHass(callWS: HomeAssistant["callWS"]): HomeAssistant {
  return { callWS };
}

type Generate = (config: unknown, hass: HomeAssistant) => Promise<any>;

function getGenerate(): Generate {
  const ElementClass = customElements.get("ll-strategy-dashboard-jinjaboard") as
    | { generate: Generate }
    | undefined;
  if (!ElementClass) {
    throw new Error("ll-strategy-dashboard-jinjaboard was not registered");
  }
  return ElementClass.generate;
}

describe("ll-strategy-dashboard-jinjaboard", () => {
  it("registers itself as a custom element", () => {
    expect(customElements.get("ll-strategy-dashboard-jinjaboard")).toBeDefined();
  });

  it("registers a create-dashboard suggestion in window.customStrategies", () => {
    expect(window.customStrategies).toContainEqual(
      expect.objectContaining({ type: "jinjaboard", strategyType: "dashboard" }),
    );
  });

  it("returns an error dashboard without calling callWS when template is missing", async () => {
    const callWS = vi.fn();
    const generate = getGenerate();

    const result = await generate({}, mockHass(callWS));

    expect(callWS).not.toHaveBeenCalled();
    const content = result.views[0].cards[0].content as string;
    expect(content).toContain("template_error");
    expect(content).toContain("options.template is required");
  });

  it("passes through a successful WS result unchanged", async () => {
    const wsResult = { views: [{ title: "Home" }] };
    const generate = getGenerate();

    const result = await generate(
      { template: "home.yaml.j2" },
      mockHass(vi.fn().mockResolvedValue(wsResult)),
    );

    expect(result).toBe(wsResult);
  });

  it("forwards template and globals to the WS call", async () => {
    const callWS = vi.fn().mockResolvedValue({ views: [] });
    const generate = getGenerate();

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

  it("returns an error dashboard with the code and message on WS rejection", async () => {
    const error: JinjaboardWsError = { code: "template_error", message: "Line 3: boom" };
    const generate = getGenerate();

    const result = await generate(
      { template: "home.yaml.j2" },
      mockHass(vi.fn().mockRejectedValue(error)),
    );

    const content = result.views[0].cards[0].content as string;
    expect(content).toContain("template_error");
    expect(content).toContain("Line 3: boom");
  });
});
