"""Visible, disposable UI used by the manual native-input smoke test."""
import json
import os
import tkinter as tk
from pathlib import Path


OUTPUT = Path(os.environ["AKASHI_INPUT_HARNESS_OUTPUT"])

root = tk.Tk()
root.title("AKASHI Computer Agent Input Harness")
root.geometry("720x360+180+180")
root.configure(background="#101418")

label = tk.Label(
    root,
    text="AKASHI NATIVE INPUT TEST",
    foreground="#f0f4f7",
    background="#101418",
    font=("Segoe UI", 16, "bold"),
)
label.pack(pady=(35, 12))

text = tk.Text(root, height=6, width=70, font=("Consolas", 14))
text.pack(padx=35, pady=12, fill="both", expand=True)

events = []
surface = tk.Canvas(root, height=70, background="#24303a", highlightthickness=0)
surface.pack(padx=35, pady=(0, 20), fill="x")
surface.create_text(320, 35, text="CLICK TARGET", fill="#f0f4f7", font=("Segoe UI", 14, "bold"))
status = tk.StringVar(value="WAITING")
status_label = tk.Label(root, textvariable=status, foreground="#80d8ff", background="#101418")
status_label.place(x=600, y=42)


def persist(_event=None) -> None:
    OUTPUT.write_text(
        json.dumps({"text": text.get("1.0", "end-1c"), "events": events}),
        encoding="utf-8",
    )


def note(name: str) -> None:
    events.append(name)
    status.set(name.upper())
    persist()


text.bind("<KeyRelease>", persist)
surface.bind("<Button-1>", lambda _event: note("click"))
surface.bind("<Double-Button-1>", lambda _event: note("double_click"))
surface.bind("<Button-3>", lambda _event: note("right_click"))
surface.bind("<B1-Motion>", lambda _event: note("drag"))
surface.bind("<MouseWheel>", lambda _event: note("scroll"))
text.focus_force()
root.bind("<Escape>", lambda _event: root.destroy())
root.mainloop()
