import { describe, expect, it, vi } from "vitest";

import { createStrategyGenerate, errorCard, shouldRegenerateJinjaboard } from "./strategy-common";
import type { HomeAssistant, JinjaboardSubscribeEvent, JinjaboardWsError } from "./types";

function mockHass(
  callWS: HomeAssistant["callWS"],
  subscribeMessage: HomeAssistant["connection"]["subscribeMessage"] = vi.fn(),
): HomeAssistant {
  return { callWS, connection: { subscribeMessage } };
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

  it("never subscribes when auto_update is falsy (regression guard)", async () => {
    const subscribeMessage = vi.fn();
    const callWS = vi.fn().mockResolvedValue({ views: [] });
    const generate = createStrategyGenerate(vi.fn());

    await generate({ template: "home.yaml.j2" }, mockHass(callWS, subscribeMessage));

    expect(subscribeMessage).not.toHaveBeenCalled();
    expect(callWS).toHaveBeenCalled();
  });

  it("auto_update: true subscribes once and resolves with the first pushed value, without calling callWS", async () => {
    let pushed: ((event: JinjaboardSubscribeEvent) => void) | undefined;
    const subscribeMessage = vi.fn((callback) => {
      pushed = callback;
      return Promise.resolve(vi.fn());
    });
    const callWS = vi.fn();
    const generate = createStrategyGenerate(vi.fn());
    const hass = mockHass(callWS, subscribeMessage);

    const resultPromise = generate({ template: "home.yaml.j2", auto_update: true }, hass);
    pushed!({ result: { views: [{ title: "Live" }] } });

    await expect(resultPromise).resolves.toEqual({ views: [{ title: "Live" }] });
    expect(subscribeMessage).toHaveBeenCalledTimes(1);
    expect(callWS).not.toHaveBeenCalled();
  });

  it("auto_update: true returns the cached value on a second generate() call, without re-subscribing", async () => {
    let pushed: ((event: JinjaboardSubscribeEvent) => void) | undefined;
    const subscribeMessage = vi.fn((callback) => {
      pushed = callback;
      return Promise.resolve(vi.fn());
    });
    const generate = createStrategyGenerate(vi.fn());
    const hass = mockHass(vi.fn(), subscribeMessage);
    const config = { template: "home.yaml.j2", auto_update: true };

    const first = generate(config, hass);
    pushed!({ result: { views: [{ title: "Live" }] } });
    await first;

    const second = await generate(config, hass);

    expect(second).toEqual({ views: [{ title: "Live" }] });
    expect(subscribeMessage).toHaveBeenCalledTimes(1);
  });

  it("auto_update: true resolves an {error} push through buildErrorResult, same as the one-shot path", async () => {
    let pushed: ((event: JinjaboardSubscribeEvent) => void) | undefined;
    const subscribeMessage = vi.fn((callback) => {
      pushed = callback;
      return Promise.resolve(vi.fn());
    });
    const error: JinjaboardWsError = { code: "template_error", message: "boom" };
    const buildErrorResult = vi.fn().mockReturnValue({ cards: [] });
    const generate = createStrategyGenerate(buildErrorResult);
    const hass = mockHass(vi.fn(), subscribeMessage);

    const resultPromise = generate({ template: "home.yaml.j2", auto_update: true }, hass);
    pushed!({ error });

    await expect(resultPromise).resolves.toEqual({ cards: [] });
    expect(buildErrorResult).toHaveBeenCalledWith(error);
  });

  it("auto_update: true keeps independent cache entries for two different templates", async () => {
    const pushedByTemplate = new Map<string, (event: JinjaboardSubscribeEvent) => void>();
    const subscribeMessage = vi.fn((callback, message: { template: string }) => {
      pushedByTemplate.set(message.template, callback);
      return Promise.resolve(vi.fn());
    });
    const generate = createStrategyGenerate(vi.fn());
    const hass = mockHass(vi.fn(), subscribeMessage);

    const a = generate({ template: "a.yaml.j2", auto_update: true }, hass);
    const b = generate({ template: "b.yaml.j2", auto_update: true }, hass);
    pushedByTemplate.get("a.yaml.j2")!({ result: { value: "a" } });
    pushedByTemplate.get("b.yaml.j2")!({ result: { value: "b" } });

    await expect(a).resolves.toEqual({ value: "a" });
    await expect(b).resolves.toEqual({ value: "b" });
    expect(subscribeMessage).toHaveBeenCalledTimes(2);
  });
});

describe("shouldRegenerateJinjaboard", () => {
  function hassWithRegistries(overrides: Record<string, unknown>): HomeAssistant {
    return { ...mockHass(vi.fn()), ...overrides } as unknown as HomeAssistant;
  }

  it("auto_update falsy: true iff any default registry reference differs", () => {
    const oldHass = hassWithRegistries({ entities: {}, devices: {}, areas: {}, floors: {} });
    const sameRegistries = hassWithRegistries({
      entities: (oldHass as any).entities,
      devices: (oldHass as any).devices,
      areas: (oldHass as any).areas,
      floors: (oldHass as any).floors,
    });
    const changedEntities = hassWithRegistries({
      entities: {},
      devices: (oldHass as any).devices,
      areas: (oldHass as any).areas,
      floors: (oldHass as any).floors,
    });

    expect(shouldRegenerateJinjaboard({ template: "x" }, oldHass, sameRegistries)).toBe(false);
    expect(shouldRegenerateJinjaboard({ template: "x" }, oldHass, changedEntities)).toBe(true);
  });

  it("auto_update falsy: reads through the legacy {type, options} nested shape", () => {
    const oldHass = hassWithRegistries({ entities: {} });
    const changed = hassWithRegistries({ entities: {} });

    expect(
      shouldRegenerateJinjaboard(
        { type: "custom:jinjaboard", options: { template: "x", auto_update: false } },
        oldHass,
        changed,
      ),
    ).toBe(true);
  });

  it("auto_update: true with no subscription yet returns false", () => {
    const hass = mockHass(vi.fn());
    expect(shouldRegenerateJinjaboard({ template: "never-subscribed.yaml.j2", auto_update: true }, hass, hass)).toBe(
      false,
    );
  });

  it("auto_update: true clears pendingRegenerate on read (true once, then false)", async () => {
    let pushed: ((event: JinjaboardSubscribeEvent) => void) | undefined;
    const subscribeMessage = vi.fn((callback) => {
      pushed = callback;
      return Promise.resolve(vi.fn());
    });
    const generate = createStrategyGenerate(vi.fn());
    const hass = mockHass(vi.fn(), subscribeMessage);
    const config = { template: "home.yaml.j2", auto_update: true };

    const first = generate(config, hass);
    pushed!({ result: { views: [] } }); // resolves `first`, doesn't set the flag
    await first;

    // A *second* push (the backend decided something changed) is what sets
    // pendingRegenerate — the first push only resolved the initial generate().
    pushed!({ result: { views: [{ title: "updated" }] } });

    expect(shouldRegenerateJinjaboard(config, hass, hass)).toBe(true);
    expect(shouldRegenerateJinjaboard(config, hass, hass)).toBe(false);
  });
});
