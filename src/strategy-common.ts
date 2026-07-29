import { renderTemplate } from "./ws";
import type {
  HomeAssistant,
  JinjaboardDebugEnvelope,
  JinjaboardDebugInfo,
  JinjaboardErrorCode,
  JinjaboardWsError,
  StrategyConfig,
} from "./types";

interface ErrorPresentation {
  icon: string;
  title: string;
  /** Only set for codes whose backend message doesn't already spell out the fix. */
  hint?: string;
}

const ERROR_PRESENTATIONS: Record<JinjaboardErrorCode, ErrorPresentation> = {
  path_missing: {
    icon: "🗂️",
    title: "Template File Not Found",
    hint: "Check the `template:` path in your dashboard/view/section config — it's relative to the Home Assistant config directory.",
  },
  path_traversal: {
    icon: "🚫",
    title: "Path Outside Config Directory",
    hint: "Every template and `!include` path must resolve inside the Home Assistant config directory — look for a stray `../` or an incorrect base path.",
  },
  template_not_authorized: {
    icon: "🔒",
    title: "Template Not Authorized",
  },
  include_not_found: {
    icon: "🔗",
    title: "Include Not Found",
    hint: "One of this template's `!include`/`!include_dir_*` targets, a `macros:` entry, or a `globals:` file path couldn't be found on disk.",
  },
  template_error: {
    icon: "🧩",
    title: "Template Error",
    hint: "Dashboard `globals:` are only reachable as `jjb.globals.<name>`, and `!include ... vars:` as `jjb.inc.<name>` — a bare variable name is never populated.",
  },
  yaml_parse_error: {
    icon: "📄",
    title: "Invalid YAML Output",
  },
  globals_error: {
    icon: "🌐",
    title: "Invalid Globals File",
    hint: "A `globals:` file must contain a valid YAML mapping at the top level — it's parsed as plain YAML, not rendered through Jinja.",
  },
  render_timeout: {
    icon: "⏱️",
    title: "Render Timed Out",
    hint: "The template took too long to render — check for expensive loops over `states()`/`areas()`/`devices()`.",
  },
};

const DEFAULT_PRESENTATION: ErrorPresentation = { icon: "⚠️", title: "JinjaBoard Render Error" };

// The card's fenced code block renders with `white-space: pre` (needed to
// keep the message monospaced) and only `overflow-x: auto` for anything
// past the card's width — confirmed live: that scrollbar is easy to miss
// entirely, especially for the long, single-line messages an include-chain
// error produces (`in included file 'x' (included at line N): in included
// file 'y' ...`), silently hiding most of the message instead of wrapping
// it. Soft-wrapping the prose onto multiple lines ourselves, at word
// boundaries, keeps it visible without needing card-level CSS control (a
// markdown card's `content` is plain text; there's no `card_mod`-style
// styling hook available here).
// A default single-column masonry card is ~458px wide in practice (measured
// live) — at the markdown card's 12px monospace code font that's ~63
// characters before the browser's own horizontal scrollbar would kick in.
// 60 leaves a small margin rather than wrapping right at the edge.
const CODE_BLOCK_WRAP_WIDTH = 60;

/**
 * Word-wraps only the message's first line (the prose sentence, e.g.
 * "Rendered template output was not valid YAML. ... Raw output
 * (truncated):"), leaving everything from the first embedded newline
 * onward completely untouched.
 *
 * That second part is verbatim, structured content — currently the
 * yaml_parse_error preview of the actual rendered YAML — not prose:
 * reflowing it at word boundaries destroys the very line breaks/
 * indentation the reader needs to spot the problem (confirmed live: a
 * wrapped continuation line loses the original line's leading indentation
 * entirely, which is exactly the kind of detail a YAML indentation bug
 * report can't afford to lose). Left alone, `overflow-x: auto` on the
 * code block lets a too-long raw-output line scroll horizontally instead.
 */
function formatMessageForCodeBlock(message: string, width = CODE_BLOCK_WRAP_WIDTH): string {
  const newlineIndex = message.indexOf("\n");
  if (newlineIndex === -1) {
    return wrapLine(message, width);
  }
  return wrapLine(message.slice(0, newlineIndex), width) + message.slice(newlineIndex);
}

function wrapLine(line: string, width: number): string {
  if (line.length <= width) {
    return line;
  }
  const words = line.split(" ");
  const wrapped: string[] = [];
  let current = "";
  for (const word of words) {
    if (current && current.length + 1 + word.length > width) {
      wrapped.push(current);
      current = word;
    } else {
      current = current ? `${current} ${word}` : word;
    }
  }
  if (current) {
    wrapped.push(current);
  }
  return wrapped.join("\n");
}

export function errorCard(error: JinjaboardWsError) {
  const presentation = (error.code && ERROR_PRESENTATIONS[error.code]) || DEFAULT_PRESENTATION;
  const message = error.message ?? String(error);

  const sections = [
    `## ${presentation.icon} ${presentation.title}`,
    "```\n" + formatMessageForCodeBlock(message) + "\n```",
  ];
  if (presentation.hint) {
    sections.push(`💡 ${presentation.hint}`);
  }
  sections.push(`---\nError code: \`${error.code ?? "unknown"}\``);

  return {
    type: "markdown",
    // HA's markdown card auto-detects `{{`/`{%` anywhere in `content` and
    // sends the whole string through core's own `render_template` WS
    // command for live evaluation (`hasTemplate()` in home-assistant-
    // frontend's markdown card). Both the backend's own message (which
    // routinely quotes back a snippet of the user's broken Jinja source)
    // and this file's own static hint text (e.g. the literal `{% for %}`
    // in the yaml_parse_error hint) are near-guaranteed to contain that
    // syntax — without escaping, the card would try to render our error
    // text as a template against a context where none of it is defined,
    // producing a blank card instead of the error. `{% raw %}...{% endraw
    // %}` is Jinja's own literal-text escape, so core's renderer still
    // gets dispatched to (satisfying `hasTemplate()`) but passes the whole
    // thing through unevaluated.
    content: `{% raw %}\n${sections.join("\n\n")}\n{% endraw %}`,
  };
}

/**
 * Narrows `value` to the subtree at dot-separated `path` (e.g.
 * `"views.2.cards.0"`) — a numeric segment indexes into an array the same
 * as any other key, since bracket notation on a JS array accepts a
 * numeric-looking string (`arr["0"] === arr[0]`), so no separate
 * `Number()`/`isNaN` branching is needed. Returns `undefined` if the path
 * doesn't resolve.
 */
function selectByPath(value: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((acc, segment) => {
    if (acc === undefined || acc === null || segment === "") return acc;
    return (acc as Record<string, unknown>)[segment];
  }, value);
}

/**
 * Resolves what to log as the "Result" entry for a given `debug` option:
 * the full config for `true`/`undefined`, one selected subtree for a
 * single path string, or an object keyed by each path (mapped to its own
 * selected subtree) for a list — so a multi-path `debug:` list logs each
 * requested subtree distinctly instead of collapsing them together.
 */
function selectDebugSubtree(fullConfig: unknown, outputPath: boolean | string | string[] | undefined): unknown {
  if (typeof outputPath === "string") return selectByPath(fullConfig, outputPath);
  if (Array.isArray(outputPath)) {
    return Object.fromEntries(outputPath.map((path) => [path, selectByPath(fullConfig, path)]));
  }
  return fullConfig;
}

/**
 * A non-admin's truthy `debug` request is silently downgraded server-side
 * to the bare, unwrapped result — so the frontend must check the actual
 * response shape, never assume the wrapped envelope just because it asked
 * for one.
 */
function isDebugEnvelope(value: unknown): value is JinjaboardDebugEnvelope {
  return (
    typeof value === "object" &&
    value !== null &&
    "config" in value &&
    "debug" in value &&
    typeof (value as { debug: unknown }).debug === "object" &&
    (value as { debug: unknown }).debug !== null
  );
}

/**
 * Finds the most specific file a dot-path's content came from: checks
 * successively shorter prefixes of `path` against `origins`
 * (`"views.2.cards.0"` -> `"views.2.cards"` -> `"views.2"` -> `"views"`,
 * longest/most-specific first), falling back to `rootPath` if nothing
 * matches — meaning that content lives directly in the root file (or
 * came from a scalar `!include` that couldn't be attributed by identity,
 * see `includes.py::_render_included_file`).
 */
function resolveOrigin(path: string, origins: Record<string, string>, rootPath: string): string {
  const segments = path.split(".");
  for (let length = segments.length; length > 0; length--) {
    const prefix = segments.slice(0, length).join(".");
    if (prefix in origins) return origins[prefix];
  }
  return rootPath;
}

function logRawText(path: string, text: string, rootPath: string, vars: Record<string, unknown> | undefined): void {
  // eslint-disable-next-line no-console
  console.groupCollapsed(path === rootPath ? "Raw template output (root)" : `Raw template output: ${path}`);
  console.log(text);
  // Root is never included in `include_vars` (it never has `inc_vars`),
  // and a file `!include`d without a `vars:` mapping has no entry either
  // — only shown when there's actually something to show.
  if (vars) console.log("Vars:", vars);
  console.groupEnd();
}

/**
 * Partitions a non-`true`/`undefined` `debug` value into **file
 * selectors** — entries that exactly match a key in `rawTexts`, i.e. a
 * touched file's own display path, the same string already shown as the
 * label on its `Raw template output: <path>` console group — and **path
 * selectors**, everything else, resolved as a dot-path into the parsed
 * result like before. Lets an author debug a specific `!include` directly
 * by name (e.g. copy-pasted from a prior `debug: true` run) without first
 * having to find its dot-path in the output.
 */
function splitDebugOption(
  entries: string[],
  rawTexts: Record<string, string>,
): { pathSelectors: string[]; fileSelectors: string[] } {
  return {
    fileSelectors: entries.filter((entry) => entry in rawTexts),
    pathSelectors: entries.filter((entry) => !(entry in rawTexts)),
  };
}

function logDebugToConsole(
  template: string,
  info: JinjaboardDebugInfo,
  outputPath: boolean | string | string[] | undefined,
  fullConfig: unknown,
): void {
  const isFullDump = outputPath === true || outputPath === undefined;
  const debugEntries: string[] =
    typeof outputPath === "string" ? [outputPath] : Array.isArray(outputPath) ? outputPath : [];
  const { pathSelectors, fileSelectors } = splitDebugOption(debugEntries, info.raw_texts);

  // A debug value made entirely of file selectors doesn't correspond to
  // one unambiguous subtree of the parsed result (a file's content might
  // appear more than once, or be unidentifiable at all past an
  // !include_dir_merge_* boundary) — Result is shown in full, same as
  // `debug: true`, whenever there's no path selector to narrow it by.
  const narrowResult = pathSelectors.length > 0;
  const resultLabel = narrowResult ? `Result (${pathSelectors.join(", ")})` : "Result";
  const resultValue = narrowResult
    ? selectDebugSubtree(fullConfig, pathSelectors.length === 1 ? pathSelectors[0] : pathSelectors)
    : fullConfig;

  // eslint-disable-next-line no-console
  console.groupCollapsed(`Jinjaboard: ${template} (${info.duration_ms}ms)`);
  console.log(resultLabel, resultValue);

  // No filter at all: show every touched file, since there's no specific
  // subtree to narrow to. Otherwise show the union of explicit file
  // selectors and origin-resolved files from any path selectors, deduped
  // — e.g. two cards from the same include, or a file selector and a path
  // selector pointing at the same file, only log that file once.
  const filePaths = isFullDump
    ? Object.keys(info.raw_texts)
    : Array.from(
        new Set([
          ...fileSelectors,
          ...pathSelectors.map((path) => resolveOrigin(path, info.origins, info.root_path)),
        ]),
      );
  for (const path of filePaths) {
    if (path in info.raw_texts) logRawText(path, info.raw_texts[path], info.root_path, info.include_vars[path]);
  }

  console.groupEnd();
}

/**
 * Builds the static `generate(config, hass)` HA looks up on a strategy
 * custom element — shared across the dashboard/view/section strategies,
 * which differ only in the registered tag and the error-result shape
 * `buildErrorResult` returns (a full dashboard vs a bare `{cards: [...]}`).
 */
export function createStrategyGenerate(buildErrorResult: (error: JinjaboardWsError) => unknown) {
  return async function generate(config: StrategyConfig, hass: HomeAssistant): Promise<unknown> {
    const template = config?.template;
    if (!template) {
      return buildErrorResult({
        code: "template_error",
        message:
          "jinjaboard strategy: options.template is required (a path to the " +
          "template file, relative to the Home Assistant config directory).",
      });
    }

    const debugOption = config?.debug;
    try {
      const result = await renderTemplate(hass, template, config?.globals, config?.macros, debugOption);
      if (isDebugEnvelope(result)) {
        logDebugToConsole(template, result.debug, debugOption, result.config);
        return result.config;
      }
      return result;
    } catch (err) {
      if (debugOption) {
        // eslint-disable-next-line no-console
        console.error(`Jinjaboard: render failed for ${template}`, err);
      }
      return buildErrorResult(err as JinjaboardWsError);
    }
  };
}
