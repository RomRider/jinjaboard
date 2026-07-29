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

  it("wraps only the prose before the first newline, leaving verbatim content after it untouched", () => {
    // yaml_parse_error's message is "<prose sentence>\n<raw rendered YAML>"
    // (see websocket.py) — the raw part must survive exactly as sent, long
    // lines and all, so its original indentation stays legible; wrapping it
    // would reflow it and lose that indentation entirely.
    const longRawLine = "    content: \"Second card has bad indentation, breaking the whole parse.\"";
    const rawOutput = `cards:\n  - type: markdown\n${longRawLine}\n  - type: markdown\n`;
    const message = `Rendered template output was not valid YAML. Raw output (truncated):\n${rawOutput}`;
    const card = errorCard({ code: "yaml_parse_error", message });

    const codeBlockContent = card.content.split("```")[1];
    expect(codeBlockContent).toContain(`\n${rawOutput}`);
    expect(codeBlockContent).toContain(longRawLine);
  });
});

describe("errorCard for globals_error", () => {
  it("renders a card for the globals_error code", () => {
    const card = errorCard({
      code: "globals_error",
      message: "Globals file 'globals.yaml' must contain a YAML mapping at the top level, got list",
    });

    expect(card.type).toBe("markdown");
    expect(card.content).toContain("Invalid Globals File");
    expect(card.content).toContain("globals.yaml");
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

    expect(callWS).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "jinjaboard/render",
        template: "home.yaml.j2",
        globals: { area_id: "kitchen" },
      }),
    );
  });

  it("forwards a string globals (a globals: file path) to the WS call", async () => {
    const callWS = vi.fn().mockResolvedValue({ views: [] });
    const generate = createStrategyGenerate(vi.fn());

    await generate(
      { template: "home.yaml.j2", globals: "jinjaboard/globals.yaml" },
      mockHass(callWS),
    );

    expect(callWS).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "jinjaboard/render",
        template: "home.yaml.j2",
        globals: "jinjaboard/globals.yaml",
      }),
    );
  });

  it("forwards macros to the WS call", async () => {
    const callWS = vi.fn().mockResolvedValue({ views: [] });
    const generate = createStrategyGenerate(vi.fn());

    await generate(
      { template: "home.yaml.j2", macros: ["macros/common.yaml.j2"] },
      mockHass(callWS),
    );

    expect(callWS).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "jinjaboard/render",
        template: "home.yaml.j2",
        globals: undefined,
        macros: ["macros/common.yaml.j2"],
      }),
    );
  });

  it("calls the error builder with the rejected error on WS failure", async () => {
    const error: JinjaboardWsError = { code: "template_error", message: "Line 3: boom" };
    const buildErrorResult = vi.fn().mockReturnValue({ cards: [] });
    const generate = createStrategyGenerate(buildErrorResult);

    await generate({ template: "home.yaml.j2" }, mockHass(vi.fn().mockRejectedValue(error)));

    expect(buildErrorResult).toHaveBeenCalledWith(error);
  });

  it("does not console.error on WS rejection when debug is absent", async () => {
    const error: JinjaboardWsError = { code: "template_error", message: "boom" };
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const generate = createStrategyGenerate(vi.fn().mockReturnValue({ cards: [] }));

    await generate({ template: "home.yaml.j2" }, mockHass(vi.fn().mockRejectedValue(error)));

    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });

  describe("debug", () => {
    it("forwards debug to the WS call when set", async () => {
      const callWS = vi.fn().mockResolvedValue({ views: [] });
      const generate = createStrategyGenerate(vi.fn());

      await generate({ template: "home.yaml.j2", debug: true }, mockHass(callWS));

      expect(callWS).toHaveBeenCalledWith(expect.objectContaining({ debug: true }));
    });

    it("unwraps a {config, debug} envelope and returns the config", async () => {
      const config = { views: [] };
      const wsResult = {
        config,
        debug: { duration_ms: 5, root_path: "home.yaml.j2", raw_texts: { "home.yaml.j2": "x" }, origins: {} },
      };
      const generate = createStrategyGenerate(vi.fn());
      vi.spyOn(console, "groupCollapsed").mockImplementation(() => {});
      vi.spyOn(console, "log").mockImplementation(() => {});
      vi.spyOn(console, "groupEnd").mockImplementation(() => {});

      const result = await generate(
        { template: "home.yaml.j2", debug: true },
        mockHass(vi.fn().mockResolvedValue(wsResult)),
      );

      expect(result).toBe(config);
      vi.restoreAllMocks();
    });

    it("with no path filter, logs the result and a nested group per touched file", async () => {
      const config = { views: [] };
      const wsResult = {
        config,
        debug: {
          duration_ms: 5,
          root_path: "home.yaml.j2",
          raw_texts: { "home.yaml.j2": "raw text", "a.yaml.j2": "include text" },
          origins: {},
        },
      };
      const groupCollapsed = vi.spyOn(console, "groupCollapsed").mockImplementation(() => {});
      const log = vi.spyOn(console, "log").mockImplementation(() => {});
      const groupEnd = vi.spyOn(console, "groupEnd").mockImplementation(() => {});
      const generate = createStrategyGenerate(vi.fn());

      await generate({ template: "home.yaml.j2", debug: true }, mockHass(vi.fn().mockResolvedValue(wsResult)));

      expect(groupCollapsed).toHaveBeenCalledWith(expect.stringMatching(/^Jinjaboard: home\.yaml\.j2 \(5ms\)/));
      expect(log).toHaveBeenCalledWith("Result", config);
      expect(groupCollapsed).toHaveBeenCalledWith("Raw template output (root)");
      expect(log).toHaveBeenCalledWith("raw text");
      expect(groupCollapsed).toHaveBeenCalledWith("Raw template output: a.yaml.j2");
      expect(log).toHaveBeenCalledWith("include text");
      expect(groupEnd).toHaveBeenCalled();

      groupCollapsed.mockRestore();
      log.mockRestore();
      groupEnd.mockRestore();
    });

    it("applies the output-path filter when debug is a string", async () => {
      const config = { views: [{ cards: ["a", "b"] }] };
      const wsResult = {
        config,
        debug: { duration_ms: 1, root_path: "home.yaml.j2", raw_texts: {}, origins: {} },
      };
      const log = vi.spyOn(console, "log").mockImplementation(() => {});
      vi.spyOn(console, "groupCollapsed").mockImplementation(() => {});
      vi.spyOn(console, "groupEnd").mockImplementation(() => {});
      const generate = createStrategyGenerate(vi.fn());

      await generate(
        { template: "home.yaml.j2", debug: "views.0.cards.1" },
        mockHass(vi.fn().mockResolvedValue(wsResult)),
      );

      expect(log).toHaveBeenCalledWith("Result (views.0.cards.1)", "b");

      vi.restoreAllMocks();
    });

    it("logs each path in a debug list under its own key", async () => {
      const config = { views: [{ cards: ["a", "b"] }] };
      const wsResult = {
        config,
        debug: { duration_ms: 1, root_path: "home.yaml.j2", raw_texts: {}, origins: {} },
      };
      const log = vi.spyOn(console, "log").mockImplementation(() => {});
      vi.spyOn(console, "groupCollapsed").mockImplementation(() => {});
      vi.spyOn(console, "groupEnd").mockImplementation(() => {});
      const generate = createStrategyGenerate(vi.fn());

      await generate(
        { template: "home.yaml.j2", debug: ["views.0.cards.0", "views.0.cards.1"] },
        mockHass(vi.fn().mockResolvedValue(wsResult)),
      );

      expect(log).toHaveBeenCalledWith("Result (views.0.cards.0, views.0.cards.1)", {
        "views.0.cards.0": "a",
        "views.0.cards.1": "b",
      });

      vi.restoreAllMocks();
    });

    it("a path filter resolving to a nested include's origin logs only that file's raw text", async () => {
      const config = { views: [{ cards: ["a"] }] };
      const wsResult = {
        config,
        debug: {
          duration_ms: 1,
          root_path: "home.yaml.j2",
          raw_texts: { "home.yaml.j2": "root text", "cards/light.yaml.j2": "card text" },
          origins: { "views.0.cards.0": "cards/light.yaml.j2" },
        },
      };
      const groupCollapsed = vi.spyOn(console, "groupCollapsed").mockImplementation(() => {});
      const log = vi.spyOn(console, "log").mockImplementation(() => {});
      vi.spyOn(console, "groupEnd").mockImplementation(() => {});
      const generate = createStrategyGenerate(vi.fn());

      await generate(
        { template: "home.yaml.j2", debug: "views.0.cards.0" },
        mockHass(vi.fn().mockResolvedValue(wsResult)),
      );

      expect(groupCollapsed).toHaveBeenCalledWith("Raw template output: cards/light.yaml.j2");
      expect(log).toHaveBeenCalledWith("card text");
      expect(groupCollapsed).not.toHaveBeenCalledWith("Raw template output (root)");
      expect(log).not.toHaveBeenCalledWith("root text");

      vi.restoreAllMocks();
    });

    it("a path filter with no matching origin falls back to the root's raw text", async () => {
      const config = { views: [{ cards: ["a"] }] };
      const wsResult = {
        config,
        debug: {
          duration_ms: 1,
          root_path: "home.yaml.j2",
          raw_texts: { "home.yaml.j2": "root text" },
          origins: {},
        },
      };
      const groupCollapsed = vi.spyOn(console, "groupCollapsed").mockImplementation(() => {});
      const log = vi.spyOn(console, "log").mockImplementation(() => {});
      vi.spyOn(console, "groupEnd").mockImplementation(() => {});
      const generate = createStrategyGenerate(vi.fn());

      await generate(
        { template: "home.yaml.j2", debug: "views.0.cards.0" },
        mockHass(vi.fn().mockResolvedValue(wsResult)),
      );

      expect(groupCollapsed).toHaveBeenCalledWith("Raw template output (root)");
      expect(log).toHaveBeenCalledWith("root text");

      vi.restoreAllMocks();
    });

    it("a list of paths resolving to two different files logs both, deduped when two paths share a file", async () => {
      const config = { views: [{ cards: ["a", "b", "c"] }] };
      const wsResult = {
        config,
        debug: {
          duration_ms: 1,
          root_path: "home.yaml.j2",
          raw_texts: { "home.yaml.j2": "root text", "cards/light.yaml.j2": "light card text" },
          origins: {
            "views.0.cards.0": "cards/light.yaml.j2",
            "views.0.cards.1": "cards/light.yaml.j2",
          },
        },
      };
      const groupCollapsed = vi.spyOn(console, "groupCollapsed").mockImplementation(() => {});
      vi.spyOn(console, "log").mockImplementation(() => {});
      vi.spyOn(console, "groupEnd").mockImplementation(() => {});
      const generate = createStrategyGenerate(vi.fn());

      // views.0.cards.0 and .1 both resolve to cards/light.yaml.j2 (deduped
      // to one group); views.0.cards.2 has no origin entry, falling back to
      // the root — two distinct groups total, not three.
      await generate(
        { template: "home.yaml.j2", debug: ["views.0.cards.0", "views.0.cards.1", "views.0.cards.2"] },
        mockHass(vi.fn().mockResolvedValue(wsResult)),
      );

      const rawTextGroupCalls = groupCollapsed.mock.calls.filter((call) =>
        String(call[0]).startsWith("Raw template output"),
      );
      expect(rawTextGroupCalls).toHaveLength(2);
      expect(groupCollapsed).toHaveBeenCalledWith("Raw template output: cards/light.yaml.j2");
      expect(groupCollapsed).toHaveBeenCalledWith("Raw template output (root)");

      vi.restoreAllMocks();
    });

    it("does not log to the console when the response is bare (e.g. non-admin request)", async () => {
      const bareResult = { views: [] };
      const groupCollapsed = vi.spyOn(console, "groupCollapsed").mockImplementation(() => {});
      const generate = createStrategyGenerate(vi.fn());

      const result = await generate(
        { template: "home.yaml.j2", debug: true },
        mockHass(vi.fn().mockResolvedValue(bareResult)),
      );

      expect(groupCollapsed).not.toHaveBeenCalled();
      expect(result).toBe(bareResult);
      groupCollapsed.mockRestore();
    });

    it("logs console.error on WS rejection when debug is set", async () => {
      const error: JinjaboardWsError = { code: "template_error", message: "boom" };
      const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
      const buildErrorResult = vi.fn().mockReturnValue({ cards: [] });
      const generate = createStrategyGenerate(buildErrorResult);

      await generate(
        { template: "home.yaml.j2", debug: true },
        mockHass(vi.fn().mockRejectedValue(error)),
      );

      expect(consoleError).toHaveBeenCalledWith(
        expect.stringContaining("Jinjaboard: render failed for home.yaml.j2"),
        error,
      );
      expect(buildErrorResult).toHaveBeenCalledWith(error);
      consoleError.mockRestore();
    });
  });
});
