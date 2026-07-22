import { renderTemplate } from "./ws";
import type { HomeAssistant, JinjaboardErrorCode, JinjaboardWsError, StrategyConfig } from "./types";

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
    hint: "One of this template's `!include`/`!include_dir_*` targets (or a `macros:` entry) couldn't be found on disk.",
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

    try {
      return await renderTemplate(hass, template, config?.globals, config?.macros);
    } catch (err) {
      return buildErrorResult(err as JinjaboardWsError);
    }
  };
}
