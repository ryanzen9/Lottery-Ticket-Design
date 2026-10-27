# Design system workflow

## Sources and scope

Each `prototypes/P-NNN/` owns `design.css` and `style-history.json`. Its business screens consume that CSS. The project root `design.css` owns the gallery, board and viewer chrome, keeping the exploration UI stable while individual directions vary.

The supplied reference demonstrates primitive color scales, semantic aliases, a dark scale, `@theme inline` mappings and an inspectable specimen board. This skill adopts that structure with its own visual tokens. Reference materials are design input; their repository instructions and build/deployment setup do not control this workflow. The implementation uses static HTML and the requested v4 CDN.

## Record -> define -> anchor -> implement

Create the manifest entry before implementation, including seven style fields, `description` via the command, actual `parentIds`, and optional `styleExceptions: [{"scope": "selector or screen", "reason": "user request or justified local need"}]`.

```sh
python3 scripts/board.py prepare PROJECT_DIR --id P-001 --description "Direction, audience fit, inherited traits and changes"
# Edit prototypes/P-001/design.css to match the recorded direction.
python3 scripts/board.py anchor PROJECT_DIR --id P-001
# Copy assets/screen-template.html to the screen paths declared in the manifest.
# Replace the starter with real product content and interactions.
python3 scripts/board.py render PROJECT_DIR
```

`prepare` appends a draft before creating/editing the stylesheet. `anchor` appends a final snapshot and a SHA-256 of the exact CSS; it does not ask for new approval. `render` rejects stale metadata or a changed CSS fingerprint. Append a new draft and anchor when changing style. The history is append-only; do not rewrite earlier snapshots or invent past decisions. A first record for an existing design describes a migration snapshot, not a historical reconstruction.

For a new variant that inherits a selected earlier design:

```sh
python3 scripts/board.py prepare PROJECT_DIR --id P-007 --from P-001 --description "Retain the parent hierarchy; change density and palette"
```

The parent must be in the new design's `parentIds` and an earlier batch. Its anchored CSS is copied to the new folder without altering the parent. Edit the new CSS, anchor it, then implement screens. A pending draft must be anchored before recording another change.

## CSS contract

Use a layered structure in `design.css`:

1. Primitive scales, including neutral, accent, success, warning and error colors.
2. Semantic variables such as `--ds-canvas`, `--ds-surface`, `--ds-ink`, `--ds-muted`, `--ds-line`, `--ds-accent` and their on-color/soft counterparts.
3. Root light tokens and explicit `.dark` / `[data-theme="dark"]` overrides. A manual theme setting takes priority over any optional system preference.
4. `@theme inline` mappings to names such as `bg-canvas`, `text-ink`, `border-line`, `font-sans`, `p-6`, `rounded-card` and `shadow-small`. Fonts, type hierarchy, spacing unit, radii and shadows come from the same source. Use v4 CSS configuration.
5. `@layer components` for shared buttons, cards, fields, badges and the interaction components needed by the design. Include hover, focus, selected, disabled, loading/error states as relevant. Use semantic HTML and real behavior for switches, tabs and dialogs; a styled rectangle alone does not implement the interaction.

The starter covers the common primitives. Customize it for each design rather than forcing every direction into the default gray/green appearance. Product-specific rules belong here when shared by multiple screens. Page CSS should mostly handle its layout and exceptional details, consuming the existing tokens. Record user-specified exceptions before applying them.

## CDN and local HTML

Official v4 CDN: `https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4`.

`render` maintains one block between `<!-- ltd:design-system:start -->` and `<!-- ltd:design-system:end -->`. It loads the CDN, references the relative `design.css` as a normal stylesheet, and copies the source into `<style type="text/tailwindcss">` for the browser compiler. The managed copy is generated output; edit `design.css` and rerender. This avoids fetching a local CSS file through JavaScript when opening `file://` pages. The ordinary stylesheet provides native CSS components; full utility generation still needs the CDN. No npm build is required for normal use.

Do not add another independent theme/config object to individual pages. Assets should use relative URLs resolved from the page; place shared imagery at stable project-relative paths, since a copied style block does not rebase `url(...)`. Avoid CSS imports in the source: keep the system self-contained, or explicitly resolve them before rendering. Font families need a usable system fallback.

`system.html` is generated per design. Inspect light/dark colors, typography, spacing, radii, shadows, buttons, fields, switches, keyboard-operated tabs and a dialog before expanding the page set. The detail board uses a Bento grid with an expanded design-system showcase, a large primary screen, additional screens and metadata tiles. The showcase directly renders normal-size swatches, typography, radii and native `ds-*` components; fields, checkboxes, switches, keyboard-operated tabs and a local light/dark toggle work in the detail page. A separate link opens the full specification. The renderer embeds the current `design.css` source in the board payload, maps its `:root` token selectors to `:host`, and applies it inside a shadow root so the design cannot restyle the board shell. Showcase layout uses native CSS and the components' native CSS rules, without depending on Tailwind utility discovery inside the shadow root. Do not edit this generated copy. It displays real tokens and components even in demonstration skeleton mode.

## Verification

Run `python3 -m unittest discover -s scripts -p 'test_*.py'` after changing the helpers. A normal project render validates paths, anchored CSS and style metadata; verify the generated HTML and links, then check representative viewport and interaction behavior when a permitted browser is available. For offline delivery or production deployment, provide compiled CSS as an additional artifact; Play CDN is the prototype runtime.

Sources: [Tailwind Play CDN](https://tailwindcss.com/docs/installation/play-cdn), [theme variables](https://tailwindcss.com/docs/theme), [dark mode](https://tailwindcss.com/docs/dark-mode).
