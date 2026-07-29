import { describe, expect, it, vi } from "vitest";

import type { HomeAssistant, JinjaboardWsError } from "../types";

function mockHass(callWS: HomeAssistant["callWS"]): HomeAssistant {
  return { callWS };
}

type Generate = (config: unknown, hass: HomeAssistant) => Promise<any>;

function getGenerate(tagName: string): Generate {
  const ElementClass = customElements.get(tagName) as { generate: Generate } | undefined;
  if (!ElementClass) {
    throw new Error(`${tagName} was not registered`);
  }
  return ElementClass.generate;
}

/**
 * Shared assertions for the view/section strategies (`strategy-view.ts` /
 * `strategy-section.ts`), which only differ in their registered tag name
 * and the template file used in fixtures — the `dashboard` strategy is
 * genuinely different (dashboard-shaped error, `customStrategies` entry)
 * and isn't covered by this helper.
 */
export function testSimpleStrategy(
  tagName: string,
  strategyType: string,
  templateFile: string,
): void {
  describe(tagName, () => {
    it("registers itself as a custom element", () => {
      expect(customElements.get(tagName)).toBeDefined();
    });

    it("does not register a create-dashboard suggestion", () => {
      expect(window.customStrategies ?? []).not.toContainEqual(
        expect.objectContaining({ strategyType }),
      );
    });

    it(`returns a ${strategyType}-shaped error without calling callWS when template is missing`, async () => {
      const callWS = vi.fn();
      const generate = getGenerate(tagName);

      const result = await generate({}, mockHass(callWS));

      expect(callWS).not.toHaveBeenCalled();
      expect(result.views).toBeUndefined();
      const content = result.cards[0].content as string;
      expect(content).toContain("template_error");
      expect(content).toContain("options.template is required");
    });

    it("passes through a successful WS result unchanged", async () => {
      const wsResult = { cards: [{ type: "markdown", content: "hi" }] };
      const generate = getGenerate(tagName);

      const result = await generate(
        { template: templateFile },
        mockHass(vi.fn().mockResolvedValue(wsResult)),
      );

      expect(result).toBe(wsResult);
    });

    it("forwards template and globals to the WS call", async () => {
      const callWS = vi.fn().mockResolvedValue({ cards: [] });
      const generate = getGenerate(tagName);

      await generate({ template: templateFile, globals: { area_id: "kitchen" } }, mockHass(callWS));

      expect(callWS).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "jinjaboard/render",
          template: templateFile,
          globals: { area_id: "kitchen" },
        }),
      );
    });

    it(`returns a ${strategyType}-shaped error with the code and message on WS rejection`, async () => {
      const error: JinjaboardWsError = { code: "template_error", message: "Line 3: boom" };
      const generate = getGenerate(tagName);

      const result = await generate(
        { template: templateFile },
        mockHass(vi.fn().mockRejectedValue(error)),
      );

      expect(result.views).toBeUndefined();
      const content = result.cards[0].content as string;
      expect(content).toContain("template_error");
      expect(content).toContain("Line 3: boom");
    });
  });
}
