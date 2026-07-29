import { defineSimpleStrategy } from "./strategy-common";

/**
 * `ll-strategy-section-jinjaboard`: generates a single Lovelace section's
 * content (`cards`, plus any other section-level keys the render returns)
 * by rendering a Jinja2 template file through the `jinjaboard/render` WS
 * command.
 *
 * Lovelace looks this up as `customElements.get("ll-strategy-section-<type>")`
 * for a `sections: [{strategy: {...}, ...}]` entry (inside a `type: sections`
 * view), merging the returned object over any sibling keys (`column_span`,
 * `title`, ...) already on that section.
 */
defineSimpleStrategy("ll-strategy-section-jinjaboard");
