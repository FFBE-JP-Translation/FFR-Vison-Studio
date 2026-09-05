# Direction: the strategy-guide spread

Chosen 2026-09-05 (impeccable seed roll `faddaf33`, assigned index 6 of 7 grounded candidates; the user picked it from four).

**Thesis.** The app is a strategy guide opened to your own unit's page. It refuses the dark card grid with a blue accent that every mod tool ships.

**The world.** A glossy white page on a warm grey desk. Two pages side by side. Thick black frames around anything that is a picture of the game (sprites, icons). Saturated colour bands as section headers: FF blue for the game's own content, gold for Resonance, red for the one button that changes the game, green for done, purple for passives. Barlow Condensed in caps for headings and bands, Barlow for the page, tabular figures in stat boxes with tinted zebra rows.

**The story.** Open the guide. The left page is the character entry: framed sprite, type and roles, level 1 stats, Resonance. The right page walks four numbered steps: Abilities, Bonuses, Stats, Resonance. Back on the spread, the red GO puts it in the game.

**First viewport.** Left page "Your visions": black-framed face icons in a grid. Right page "Install": the game and mod status box, the red GO, the build notes below it.

**What is not this.** No rounded cards, no drop shadows on controls, no gradients, no icons standing in for words, no dark mode. Motion is short (120 ms) and only for state changes.

The tokens live in `theme.dart` (class `Guide`); the parts in `widgets.dart` (Band, Frame, Box, GoButton, GuideButton, ElementSwatch, StatRow, PageTabs, StatusCell, PixelImage, Paper).
