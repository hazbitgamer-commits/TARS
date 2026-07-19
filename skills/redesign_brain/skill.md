# redesign_brain
Redesigns the look of TARS's 3D brain map (dashboard/brain.html): node circle size,
connection line thickness, colour palette (categories + agents + accents together),
and whether the legend is shown. Works by editing the STYLE/COLORS/AGENT_STYLE
block already refactored into brain.html — no restart needed, just refresh the page.

**Say:** "make your brain's circles smaller" / "thinner lines on the brain" /
"change the brain's colours" / "add a legend to the brain"

**Args:**
- `request` — plain English description of the change, e.g. "smaller circles,
  thinner lines, new colours, add a legend"

Repeated calls stack (e.g. asking for "smaller" twice shrinks it twice). Colour
requests rotate to the next palette in a built-in list of three.
