# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

JinjaBoard is a Home Assistant custom_component (HACS-distributable) that
lets users author Lovelace dashboards as YAML files with embedded Jinja2,
rendered live through HA's own template engine (`homeassistant.helpers.
template.Template`) and displayed via a custom Lovelace dashboard strategy.
Spiritual successor to `hass-lovelace_gen`, but rendered on demand through an
authenticated WebSocket API instead of pre-generated to a static file. See
README.md for the user-facing docs, architecture rationale, and usage
examples — don't duplicate that here.

## Commands

Backend tests (pytest + `pytest-homeassistant-custom-component`, isolated
from the devcontainer's live HA venv):
```bash
uv venv .venv-test && uv pip install -r requirements-test.txt -p .venv-test
.venv-test/bin/python -m pytest
```
`pyproject.toml` pins `pythonpath = ["."]` — `custom_components/jinjaboard`
is imported as a plain `import custom_components` by HA's loader (see
`homeassistant/loader.py`'s `_get_custom_components`), resolved via
`sys.path`, not `hass.config.config_dir` — this is unrelated to which
directory `hass_config_dir` points at. `tests/conftest.py` overrides
`hass_config_dir` to a fresh `tmp_path` per test (via the `hass_tmp_config_dir`
fixture) rather than the shared package directory, since tests write their
own template fixtures into it via the `write_template` fixture.
`requirements-test.txt` pins exact versions matching what's installed in
`/home/vscode/.local/ha-venv` (confirmed via PyPI metadata, not assumed) —
`pytest-homeassistant-custom-component` pins its own `homeassistant` version,
and `home-assistant-frontend` is needed separately because the `frontend`
component (a manifest dependency) fails to set up without it.

Frontend (`src/`):
```bash
cd src
npm install
npm run typecheck   # tsc --noEmit
npm run test         # vitest run
npm run build        # bundles to ../custom_components/jinjaboard/www/jinjaboard-strategy.js
```
Vitest runs in `happy-dom` (see `vitest.config.mts`) since `strategy-
dashboard.ts` calls `customElements.define` and extends `HTMLElement` at
import time. Both suites run in CI on every push/PR via
`.github/workflows/test.yml` — separate from `validate.yml`'s
hassfest/HACS jobs, which stay on their existing weekly schedule.

### Running a real Home Assistant instance to test against

The devcontainer (`romrider/hass-custom-devcontainer`) runs actual HA with
this integration bind-mounted at `/config/custom_components/jinjaboard` and
`.devcontainer/test/` bind-mounted at `/config/test/`. Inside the
devcontainer:

```bash
/home/vscode/.local/ha-venv/bin/hass -c /config
```

HA listens on `:8123` (forwarded per `HA_PORT`, default 8123). After editing
any Python file, HA must be restarted to pick up the change (no hot reload).
After editing `src/*.ts`, run `npm run build` and then either restart HA or
just reload the browser page — the built JS is served from disk on every
request, no restart needed for frontend-only changes.

Two dashboards are pre-configured via `configuration.yaml`'s `lovelace:
dashboards:` block (YAML mode, `.devcontainer/test/dashboards/*.yaml`) —
`/jinjaboard-test` and `/jinjaboard-includes-test` — so manual verification
needs zero setup; no more hand-creating a dashboard through the UI or
scripting `lovelace/config/save` WS calls. **Caveat**: `configuration.yaml`
itself is mounted as a single-*file* bind
(`devcontainer.json`'s `mounts`), which is fragile — an atomic-write
save (rename-over-target, which many editors including this one's own file
tools default to) can silently disconnect it from the host file, after which
further edits stop propagating into the container until it's re-synced
(`cp .devcontainer/test/configuration.yaml /config/configuration.yaml`) or
the container is recreated. The dashboard *content* files under
`.devcontainer/test/dashboards/` don't have this problem — they're covered
by the existing directory-level bind of `.devcontainer/test` → `/config/test`.

Login for the devcontainer's test user: `test` / `test` (see
`.devcontainer/test/.env`).

There is no browser automation tool pre-installed; `npx playwright install
chromium firefox` (plus `sudo apt-get install -y libgtk-3-0t64` for Firefox's
missing deps in this container) works for driving a real page if you need to
verify a frontend change end-to-end. Test **both** Chromium and Firefox for
any change touching frontend resource loading — see the Firefox gotcha
below, which was only caught by cross-browser testing.

## Architecture

### Split between two independently-built halves

- `custom_components/jinjaboard/` — the Python integration. No build step;
  edited files take effect on HA restart.
- `src/` — TypeScript frontend, bundled by esbuild into a single file at
  `custom_components/jinjaboard/www/jinjaboard-strategy.js` (gitignored,
  built by CI at release time — see README's Development section).

The only contract between them is the `jinjaboard/render` WebSocket command
(schema in `custom_components/jinjaboard/websocket.py`, mirrored by hand in
`src/types.ts`). There is no code generation keeping these in sync — if you
change one side's request/response/error-code shape, update the other
manually.

### Render pipeline (`template_engine.py`)

Templates are plain YAML with embedded Jinja (`{{ }}` / `{% %}`) — **not** a
template whose body constructs a JSON structure via `| to_json`. The
pipeline is: render the raw file text through
`Template(source, hass).async_render(variables, parse_result=False, strict=True)`
to get a plain string, then parse *that string* as YAML through
`includes.py`'s private loader (`includes.parse_with_includes` — **not**
`homeassistant.util.yaml.loader.parse_yaml`; see "Includes" below for why).
`strict=True` turns HA's default undefined-variable behavior (log a warning,
render as empty) into a raised `TemplateError`, so a typo'd variable name
surfaces as a `template_error` instead of a silently broken dashboard.
Two more deliberate departures from the obvious approach, both load-bearing:

- `parse_result=False` is required. `Template.async_render`'s own default
  result-parsing uses `ast.literal_eval`, not `json.loads`/YAML — it doesn't
  matter for this project since we don't use it, but don't be tempted to rely
  on `parse_result=True` if refactoring this.
- `Template.async_render` is a `@callback` — synchronous, runs inline on the
  event loop despite the name. It's called directly (not offloaded to an
  executor) to match the pattern HA core's own `render_template` WS command
  uses. Large templates with heavy loops over `states()`/`areas()`/
  `devices()` will block the loop for their render duration; there's no
  timeout guard yet (planned: mirror `Template.async_render_will_timeout`).

### Path resolution (`path_guard.py`)

Every template/include path is relative to `hass.config.config_dir` (the
whole `/config` tree, not a fixed subdirectory) and is resolved + confined to
that directory on **every** render call, not just once at setup — there is
no config-entry-level path validation, because config entries don't carry a
path at all (see below).

### Config entries carry no data

The config flow (`config_flow.py`) is single-instance and field-less —
`single_config_entry: true` in the manifest enforces exactly one entry, and
its only purpose is giving `async_setup_entry` a standard trigger to
register the WS command and the frontend resource. The template path and
`variables` live entirely in the *dashboard's own YAML*
(`strategy.template`, `strategy.variables`), read by the frontend strategy
element and passed straight through in the WS request. This was a deliberate
simplification decided mid-project — earlier design notes (in the project
plan file, not checked into this repo) explored one-config-entry-per-
dashboard with auto-provisioned Lovelace dashboards; that was dropped in
favor of the user hand-pasting a small `strategy:` stub into a dashboard they
create themselves.

### Strategy config shape: flat, not `options`-wrapped

`src/strategy-dashboard.ts` reads `config.template` / `config.variables`
directly off the strategy config — **not** `config.options.template`. This
is not a stylistic choice: home-assistant-frontend's
`cleanLegacyStrategyConfig` (in `strategies/legacy-strategy.ts`) treats any
strategy config shaped as exactly `{type, options}` as a "legacy" config and
silently flattens `options` onto the top level before calling `generate()`.
Since our dashboard YAML is always `{type: custom:jinjaboard, options: {...}}`
when authored the "obvious" way, it always matches that legacy shape.
Writing an `options`-nested reader here is a real bug, not just noise —
it happened once already and produced a confusing "always falls into the
missing-template error path" failure with no exception thrown.

### Frontend resource registration: not `add_extra_js_url`

`frontend.py` registers the built JS bundle as a **Lovelace resource**
(reaching into `hass.data[LOVELACE_DATA].resources`, a
`ResourceStorageCollection`) rather than via the more commonly-documented
`homeassistant.components.frontend.add_extra_js_url`. This was a deliberate,
tested fix, not an oversight: `add_extra_js_url` embeds a classic
`<script>import(url)</script>` tag in server-rendered HTML, and that dynamic
import is **unreliable in Firefox** — reproduced deterministically with
Playwright, root-caused against home-assistant-frontend's actual source
(`strategies/get-strategy.ts`'s `MAX_WAIT_STRATEGY_LOAD = 5000` /
`customElements.whenDefined` race, `common/dom/load_resource.ts`'s
`loadModule()`), and confirmed fixed by switching to the Lovelace-resources
path in both Chrome and Firefox, fresh-tab and same-tab-renavigation. If
`add_extra_js_url` ever looks like a tempting simplification here, it isn't
— see README's "Why not `add_extra_js_url`?" section before changing this.

Reaching into `hass.data[LOVELACE_DATA]` is not a published third-party
integration API (confirmed: no other core component touches it) — this is a
known, accepted risk, wrapped in a broad try/except that logs actionable
manual-fallback instructions rather than crashing `async_setup_entry` if the
internal shape ever changes on a core upgrade. `manifest.json` depends on
`lovelace` specifically so this data structure exists by the time our
`async_setup_entry` runs.

### Includes (`includes.py`)

`!include`/`!include_dir_list`/`!include_dir_named`/`!include_dir_merge_list`/
`!include_dir_merge_named` mirror Home Assistant's own config-splitting tags,
but each included file is its own Jinja template (rendered with `strict=True`
like the root), not static YAML — resolved recursively, not via text
splicing, so each file's own line numbers stay meaningful in error messages.

**Why a private `yaml.SafeLoader` subclass, never
`homeassistant.util.yaml.loader.parse_yaml`:** that function delegates to
`annotatedyaml`, whose real `!include`/`!include_dir_*`/`!secret`/`!env_var`
constructors are registered **globally** on the `FastSafeLoader`/
`PythonSafeLoader` classes it also uses internally for HA's own
`configuration.yaml`. Parsing our *rendered* template output with it — the
obvious thing to do, and what this project did before includes existed — let
a bare `!include ../../../../../../etc/hostname` in a template's rendered
output silently read arbitrary files outside `config_dir` (confirmed live;
`path_guard` never even ran). `includes._JinjaboardYamlLoader` registers its
own five constructors on a standalone subclass instead, so parsing our
rendered output can never trigger HA's real include machinery; any other
stray `!tag` falls through to PyYAML's normal "could not determine a
constructor" error (`yaml_parse_error`) rather than doing something silently
wrong.

**Path resolution**: relative to the *including file's own directory*
(`path_guard.resolve_config_path`'s `base_dir` param), matching real HA's
`!include` — not always relative to `config_dir` root like the top-level
`strategy.template` path is. Still always re-confined to stay under
`config_dir` regardless of `base_dir`.

**Variables**: an included file automatically inherits whatever `variables`
the file that included it had (like Jinja's own `{% include %}` "with
context"), with an optional mapping form —
`!include {path: x.yaml.j2, vars: {area_id: kitchen}}` — to layer on
extra/overriding variables for that one include.

**Cycle/depth guard**: `includes.py` threads a list of resolved absolute
paths through every recursive call; a path already on the list raises
`template_error` with the full chain, as does exceeding `MAX_INCLUDE_DEPTH`
(20) — a coarse backstop, not a resource-limit story, consistent with there
being no render-timeout guard yet either.

**Directory includes are recursive** (`os.walk`, dotfiles/dot-dirs skipped)
and match `*.yaml`/`*.yml`/`*.yaml.j2`/`*.yml.j2` — real HA's directory
includes only match `*.yaml`; the two Jinja-extension patterns were added to
fit this project's convention. `!include_dir_named`'s dict key strips the
*full* recognized template extension (`kitchen.yaml.j2` → `kitchen`), not
just the last `.`-segment like real HA's single `os.path.splitext`.

### Error codes

WS errors use a fixed set of codes (`path_missing`, `path_traversal`,
`include_not_found`, `template_error`, `yaml_parse_error`, and the
not-yet-triggerable `render_timeout`), sent via `connection.send_error`, so
the frontend can branch and show a specific message instead of a blank
dashboard. Keep `websocket.py`'s error-code table and `src/types.ts`'s
`JinjaboardErrorCode` union in sync by hand.
