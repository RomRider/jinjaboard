import { describe, expect, it, vi } from "vitest";

import { renderDashboard } from "./ws";
import type { HomeAssistant } from "./types";

function mockHass(callWS: HomeAssistant["callWS"]): HomeAssistant {
  return { callWS };
}

describe("renderDashboard", () => {
  it("calls hass.callWS with the jinjaboard/render request shape", async () => {
    const callWS = vi.fn().mockResolvedValue({ views: [] });
    const hass = mockHass(callWS);

    await renderDashboard(hass, "home.yaml.j2", { area_id: "kitchen" });

    expect(callWS).toHaveBeenCalledWith({
      type: "jinjaboard/render",
      template: "home.yaml.j2",
      variables: { area_id: "kitchen" },
    });
  });

  it("omits variables when none are given", async () => {
    const callWS = vi.fn().mockResolvedValue({ views: [] });
    const hass = mockHass(callWS);

    await renderDashboard(hass, "home.yaml.j2");

    expect(callWS).toHaveBeenCalledWith({
      type: "jinjaboard/render",
      template: "home.yaml.j2",
      variables: undefined,
    });
  });

  it("resolves with the WS result on success", async () => {
    const result = { views: [{ title: "Home" }] };
    const hass = mockHass(vi.fn().mockResolvedValue(result));

    await expect(renderDashboard(hass, "home.yaml.j2")).resolves.toBe(result);
  });

  it("propagates a WS rejection", async () => {
    const error = { code: "template_error", message: "boom" };
    const hass = mockHass(vi.fn().mockRejectedValue(error));

    await expect(renderDashboard(hass, "home.yaml.j2")).rejects.toBe(error);
  });
});
