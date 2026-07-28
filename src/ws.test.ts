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

    expect(callWS).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "jinjaboard/render",
        template: "home.yaml.j2",
        globals: { area_id: "kitchen" },
      }),
    );
  });

  it("omits globals when none are given", async () => {
    const callWS = vi.fn().mockResolvedValue({ views: [] });
    const hass = mockHass(callWS);

    await renderTemplate(hass, "home.yaml.j2");

    expect(callWS).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "jinjaboard/render",
        template: "home.yaml.j2",
        globals: undefined,
      }),
    );
  });

  it("forwards a string globals value (a globals: file path) as-is", async () => {
    const callWS = vi.fn().mockResolvedValue({ views: [] });
    const hass = mockHass(callWS);

    await renderTemplate(hass, "home.yaml.j2", "jinjaboard/globals.yaml");

    expect(callWS).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "jinjaboard/render",
        template: "home.yaml.j2",
        globals: "jinjaboard/globals.yaml",
      }),
    );
  });

  it("includes macros when given", async () => {
    const callWS = vi.fn().mockResolvedValue({ views: [] });
    const hass = mockHass(callWS);

    await renderTemplate(hass, "home.yaml.j2", undefined, ["macros/common.yaml.j2"]);

    expect(callWS).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "jinjaboard/render",
        template: "home.yaml.j2",
        globals: undefined,
        macros: ["macros/common.yaml.j2"],
      }),
    );
  });

  it("gathers user_agent and viewport unconditionally, and language/theme/browser_mod_id only when available", async () => {
    const callWS = vi.fn().mockResolvedValue({ views: [] });
    const hass = mockHass(callWS);
    hass.language = "en";
    hass.themes = { darkMode: true };
    localStorage.setItem("browser_mod-browser-id", "kitchen-tablet");

    await renderTemplate(hass, "home.yaml.j2");

    const request = callWS.mock.calls[0][0] as { client: Record<string, unknown> };
    expect(request.client).toEqual({
      user_agent: window.navigator.userAgent,
      viewport: { width: window.innerWidth, height: window.innerHeight },
      browser_mod_id: "kitchen-tablet",
      language: "en",
      is_dark_theme: true,
    });

    localStorage.removeItem("browser_mod-browser-id");
  });

  it("omits language/is_dark_theme/browser_mod_id when hass/localStorage don't provide them", async () => {
    const callWS = vi.fn().mockResolvedValue({ views: [] });
    const hass = mockHass(callWS);

    await renderTemplate(hass, "home.yaml.j2");

    const request = callWS.mock.calls[0][0] as { client: Record<string, unknown> };
    expect(request.client).not.toHaveProperty("browser_mod_id");
    expect(request.client).not.toHaveProperty("language");
    expect(request.client).not.toHaveProperty("is_dark_theme");
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
