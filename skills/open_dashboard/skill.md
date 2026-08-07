# open_dashboard
Opens the HUD home page (localhost:8765): status, weather, timers, personality sliders, activity feed, skills, brain stats.
**Say:** "show me the home page" / "open your dashboard"
**Args:** none (the brain passes `confirmed` only after Jacob says yes).
If asked again within 20 seconds of the last open, TARS checks first ("I just
opened that — want me to bring it up again?") instead of silently repeating,
to avoid accidental double-opens.
