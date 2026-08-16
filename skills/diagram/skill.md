# diagram
Draws a flowchart/system diagram/mind map styled like TARS's own dashboard —
same dark HUD colours (--bg, --panel, --cyan...) as dashboard/index.html, glowing
nodes, animated dashed connector lines, and mouse wheel-zoom + drag-pan — so it
looks like part of the Jarvis system rather than a plain picture. Opens as its
own chromeless window (like the brain page does). The actual box-and-arrow
layout is done by Mermaid.js, vendored locally as mermaid.min.js so it works
with no internet needed. Saves each diagram as an HTML file in
workshop/diagrams/ so it can be reopened by name later.

**Say:** "draw a diagram of my morning routine" / "design a system diagram
showing how my skills talk to the brain" / "what diagrams do I have" /
"open my morning routine diagram"

**Args:**
- `spec` — the diagram as a simple chain: "Wake up -> Check phone -> Coffee ->
  Work". Several chains separated by `;` or a newline branch off each other,
  and reused names share the same box, e.g. "TARS -> Skills; Skills -> Brain;
  Skills -> Vault". `list` hears back saved diagrams; a saved title reopens it.
- `title` — short title for a new diagram (optional — guessed from the spec).

NOT for 3D objects (design/cad) and NOT for the brain page's own visual style
(redesign_brain — that only edits brain.html's node size/colours/legend).
