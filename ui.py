"""Tiny always-on-top status pill so Jacob can see what TARS is doing.

Grey = standby, green = listening, amber = thinking, blue = speaking.
Drag it anywhere with the mouse. Runs on its own thread.
"""
import queue
import threading
import tkinter as tk

STATES = {
    "standby": ("#7f8c8d", 'Standby — say "Hey TARS"'),
    "listening": ("#2ecc71", "Listening…"),
    "thinking": ("#f1c40f", "Thinking…"),
    "speaking": ("#3498db", "Speaking…"),
    "asleep": ("#8e44ad", 'Asleep — say "Hey TARS, wake up"'),
    "offline": ("#e74c3c", "Not listening"),
}

W, H = 230, 38


class StatusUI:
    def __init__(self):
        self._q: queue.Queue[str] = queue.Queue()
        import sys

        if sys.platform != "win32":
            # macOS kills the whole process (NSException) when Tk runs off
            # the main thread — first real Mac boot died exactly here.
            # On Mac/Linux the dashboard is TARS's face; no pill.
            return
        threading.Thread(target=self._run, daemon=True).start()

    def set(self, state: str) -> None:
        self._q.put(state)

    def _run(self) -> None:
        root = tk.Tk()
        root.overrideredirect(True)          # no title bar
        root.attributes("-topmost", True)    # always visible
        root.attributes("-alpha", 0.88)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{W}x{H}+{sw - W - 18}+{sh - H - 70}")  # bottom-right
        root.configure(bg="#101418")

        canvas = tk.Canvas(root, width=W, height=H, bg="#101418", highlightthickness=0)
        canvas.pack()
        dot = canvas.create_oval(12, 11, 28, 27, fill="#7f8c8d", outline="")
        label = canvas.create_text(
            38, H // 2, anchor="w", fill="#e8e8e8",
            font=("Segoe UI", 10, "bold"), text="Starting…",
        )

        # draggable
        def press(e):
            root._dx, root._dy = e.x, e.y

        def drag(e):
            root.geometry(f"+{e.x_root - root._dx}+{e.y_root - root._dy}")

        canvas.bind("<Button-1>", press)
        canvas.bind("<B1-Motion>", drag)

        # right-click the pill = the always-available off switch (Jacob:
        # "i don't know how to close tars")
        menu = tk.Menu(root, tearoff=0, bg="#101418", fg="#e8e8e8",
                       activebackground="#22303f", activeforeground="#ffffff",
                       bd=0)

        def open_dashboard():
            try:
                import tars_window

                tars_window.open_page("")
            except Exception:
                pass

        def shutdown():
            import os

            canvas.itemconfig(dot, fill="#e74c3c")
            canvas.itemconfig(label, text="Powering down…")
            root.update()
            root.after(400, lambda: os._exit(0))

        menu.add_command(label="Open TARS window", command=open_dashboard)
        menu.add_separator()
        menu.add_command(label="Shut TARS down completely", command=shutdown)
        canvas.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

        def poll():
            try:
                while True:
                    state = self._q.get_nowait()
                    color, text = STATES.get(state, ("#7f8c8d", state))
                    canvas.itemconfig(dot, fill=color)
                    canvas.itemconfig(label, text=text)
            except queue.Empty:
                pass
            root.after(80, poll)

        poll()
        root.mainloop()
