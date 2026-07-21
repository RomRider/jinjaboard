import { describe, expect, it, vi } from "vitest";

import { renderTemplate } from "./ws";
import type { HomeAssistant } from "./types";

function mockHass(callWS: HomeAssistant["callWS"]): HomeAssistant {
  return { callWS };
}

describe("renderTemplate", () => {
  it("calls hass.callWS with the jinjaboard/render request shape", async () => {
    const callWS = vi.fn().mockResolvedValue({ views: [] });
    const hass = mockHass(callWS);

    await renderTemplate(hass, "home.yaml.j2", { area_id: "kitchen" });

    expect(callWS).toHaveBeenCalledWith({
      type: "jinjaboard/render",
      template: "home.yaml.j2",
      globals: { area_id: "kitchen" },
    });
  });

  it("omits globals when none are given", async () => {
    const callWS = vi.fn().mockResolvedValue({ views: [] });
    const hass = mockHass(callWS);

    await renderTemplate(hass, "home.yaml.j2");

    expect(callWS).toHaveBeenCalledWith({
      type: "jinjaboard/render",
      template: "home.yaml.j2",
      globals: undefined,
    });
  });

  it("resolves with the WS result on success", async () => {
    const result = { views: [{ title: "Home" }] };
    const hass = mockHass(vi.fn().mockResolvedValue(result));

    await expect(renderTemplate(hass, "home.yaml.j2")).resolves.toBe(result);
  });

  it("propagates a WS rejection", async () => {
    const error = { code: "template_error", message: "boom" };
    const hass = mockHass(vi.fn().mockRejectedValue(error));

    await expect(renderTemplate(hass, "home.yaml.j2")).rejects.toBe(error);
  });
});
