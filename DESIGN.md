# DESIGN.md — FFR Vision Studio

Design system for the FFR Vision Studio Windows app (this repository) and its download page. Direction: **the strategy-guide spread** (see `lib/design/DIRECTION.md`). Mode: Operate for the app, Persuade for the download page.

## Visual world

A white glossy page on a warm grey desk. Everything that is a picture of the game sits in a 2 px black frame. Sections open with a saturated colour band in condensed caps. Numbers sit in tabular figures inside boxed tables with zebra rows. One red button per screen changes the game; nothing else is red except a destructive action and an error.

## Colour

| Token | Value | Use |
|---|---|---|
| desk | `#CFCBC2` | Window background behind the page |
| paper | `#FFFFFF` | The page |
| paper2 | `#F4F2ED` | Zebra rows, quiet panels |
| paper3 | `#E9E6DF` | Disabled fills, selected chips |
| ink | `#121212` | Text, frames, bands for neutral sections |
| inkSoft | `#5A5751` | Secondary text |
| inkFaint | `#9A968D` | Hints, disabled text |
| hairline | `#D9D5CC` | Table rules, quiet borders |
| blue | `#1F4FD0` | The game's own content (abilities, stats, "Your visions") |
| gold | `#D9A21B` | Resonance |
| red | `#D42B2B` | GO, remove, errors |
| green | `#178A45` | Done, closed-game check |
| purple | `#6B3FA0` | Passives, custom markers |

Element swatches (small filled squares next to ability names): Fire red, Ice light blue, Wind green, Earth brown, Thunder yellow, Water blue, Light pale gold, Dark purple, non-elemental grey. Same set on the Resonance element chips.

## Type

- **Barlow Condensed** (600–800), caps, for `h1` (34 px), `h2` (20 px), bands (14 px, letter-spacing 0.8), labels (11 px, letter-spacing 1). 
- **Barlow** for everything else: text 14 px, strong 14 px/600, small 12.5 px, numbers 14 px with tabular figures.
- Consolas / Cascadia Mono for the log console (12 px, on ink).

Type scale is deliberately few steps: 11 / 12.5 / 14 / 20 / 34. Download page: 12 / 14 / 17 / 20 / 40.

## Mark (`lib/design/wordmark.dart`)

Rain's Brave Exvius face (56×38 pixels, never smoothed) on FF blue inside the 2 px ink frame, beside two lines: a blue "FFR" tag
with the kicker "Brave Exvius visions for the demo" in condensed caps, and "VISION STUDIO" in Barlow Condensed 800. The face is
also the Windows app icon (`windows/runner/resources/app_icon.ico`, generated from `assets/brand/rain_icon.png`) and the
favicon of the download page. The download page adds a lockup of the two game logos with an "×" between them, on white so the
JPEG logo blends.

## Night edition

`Guide.dark` swaps paper and ink (`_day` / `_night` palettes in `theme.dart`): desk `#14151A`, paper `#1F2126`, paper2 `#272A31`,
paper3 `#323640`, ink `#F1EFE8`, inkSoft `#B9B5AC`, inkFaint `#7E7A72`, hairline `#3C4049`; the bands brighten a step (blue `#3D6CE8`,
gold `#E2B134`, red `#E0463F`, green `#2DAA60`, purple `#8C61CF`). Text on a band or the GO button is always `onBand` white. The
console keeps its own pair (`consoleBg` / `consoleFg`). `ThemeToggle` (two framed cells, sun / moon) sits in the header and on the
setup page; the choice is saved in `settings.json`. Widgets never hard-code a colour: every colour is a `Guide` getter, so no
widget that takes one can be `const`.

## Motion viewer (`lib/design/anim_viewer.dart`)

A framed picture of the game with the unit's Brave Exvius motion (engine-rendered lossless WebP, pixels never smoothed), arrows
on both sides to step through the motions, and the motion's plain name in a paper label at the bottom centre ("Idle", "Attack",
"Magic", "Limit burst", "Victory", "Down" ...). While the sprite pack downloads the frame shows a spinner and "loading the
assets"; a look without a hosted pack says so in the frame. It appears in the add-unit dialog (under the look), on the unit's
left page (replacing the still), and in the Resonance step (starting on the limit burst).

## Parts (`lib/design/widgets.dart`)

- **Band** — the section header strip. Colour names the domain. Optional trailing note in paper3 caps.
- **Frame** — 2 px ink border, no radius. For sprites, icons, previews.
- **Box** — 1.5 px ink border, optional fill. For tables and forms.
- **GoButton** — red, ink frame, condensed caps, 17 px. Only for actions that change the game or take minutes. Stays solid while busy (spinner in paper); fades to paper3 when disabled.
- **GuideButton** — paper with ink frame; `danger` variant in red outline; `small` variant for in-row actions.
- **PageTabs** — the numbered step tabs (1 Abilities … 4 Resonance). Active tab is ink on paper with a 2 px rule.
- **StatRow / StatusCell** — label left, tabular value right; zebra via `paper2`.
- **PixelImage** — network image with nearest-neighbour filtering. Sprites are never smoothed.
- **Paper** — the page with the desk shadow.
- **Tiers / LibraryRow / TierMenu / GrantTools** (`screens/steps/tiers.dart`) — the drag-and-drop grammar: library rows are draggable, tiers are drop targets, "add ▾" is the keyboard-and-mouse alternative, every learned row has "tier n ▾" and ×.

## Layout

- Window 1320×860 by default, minimum 1100×700. Desk padding 22 px. Header strip: title, breadcrumb, save state, game path (capped at 420 px).
- The spread: left page fixed 300 px (unit entry) or flexible (Your visions), 2 px ink gutter, right page flexible.
- Steps: library on the left (flexible), tiers column fixed 380 px on the right. Lists scroll inside their own frame; the page itself does not scroll horizontally.
- Spacing on an 8 px grid with 12/14/16 paddings inside boxes.

## Motion

120 ms (`Guide.fast`) for tab switches, drop-target highlight and status text. No entrance animations. Drag feedback is the row itself with a hard shadow.

## Copy

Plain, specific, second person. Sentence case everywhere except bands, labels and the GO button. No exclamation marks, no em dashes, no "please". Errors say what happened and what to do next ("Point at the folder that contains FFRS.exe."). Times are stated ("Takes about two minutes.").

## Do not

Rounded corners, gradients, drop shadows on controls, icon-only buttons (except the × on a learned row), dark theme, toasts for success (the save state in the header is enough), disabled-looking primary buttons while working.
