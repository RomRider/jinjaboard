import { defineSimpleStrategy } from "./strategy-common";

/**
 * `ll-strategy-view-jinjaboard`: generates a single Lovelace view's
 * content (`cards`, plus any other view-level keys the render returns) by
 * rendering a Jinja2 template file through the `jinjaboard/render` WS
 * command.
 *
 * Lovelace looks this up as `customElements.get("ll-strategy-view-<type>")`
 * for a `views: [{strategy: {...}, ...}]` entry, merging the returned object
 * over any sibling keys (`title`, `path`, `icon`, ...) already on that view.
 */
defineSimpleStrategy("ll-strategy-view-jinjaboard");
