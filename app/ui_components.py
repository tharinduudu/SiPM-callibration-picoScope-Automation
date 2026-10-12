#!/usr/bin/env python3
"""Reusable Tkinter pieces for the calibration desktop application."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from help_content import HelpTopic


# Hover text gives a quick reminder. The adjacent help button opens the full
# explanation, so important information is never available only by hovering.
class ToolTip:
    def __init__(self, widget: tk.Misc, text: str, delay_ms: int = 550) -> None:
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.pending: str | None = None
        self.window: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def _schedule(self, _event: tk.Event | None = None) -> None:
        self._cancel()
        self.pending = self.widget.after(self.delay_ms, self._show)

    def _cancel(self) -> None:
        if self.pending is not None:
            try:
                self.widget.after_cancel(self.pending)
            except tk.TclError:
                pass
            self.pending = None

    def _show(self) -> None:
        self.pending = None
        if self.window is not None or not self.widget.winfo_exists():
            return
        window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        window.attributes("-topmost", True)
        tk.Label(
            window,
            text=self.text,
            justify="left",
            wraplength=390,
            background="#fffbd6",
            foreground="#17242b",
            relief="solid",
            borderwidth=1,
            padx=9,
            pady=7,
        ).pack()
        window.update_idletasks()
        x = min(self.widget.winfo_pointerx() + 14, self.widget.winfo_screenwidth() - window.winfo_reqwidth() - 8)
        y = min(self.widget.winfo_pointery() + 12, self.widget.winfo_screenheight() - window.winfo_reqheight() - 8)
        window.wm_geometry(f"+{max(0, x)}+{max(0, y)}")
        self.window = window

    def _hide(self, _event: tk.Event | None = None) -> None:
        self._cancel()
        if self.window is not None:
            try:
                self.window.destroy()
            except tk.TclError:
                pass
            self.window = None


def add_tooltip(widget: tk.Misc, text: str) -> None:
    if text:
        setattr(widget, "_glowcost_tooltip", ToolTip(widget, text))


class ScrolledFrame(ttk.Frame):
    """A vertical form that remains usable on a small laboratory monitor."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.body = ttk.Frame(canvas, padding=(8, 6, 12, 14))
        window = canvas.create_window((0, 0), window=self.body, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.body.columnconfigure(1, weight=1)
        self.body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))


def show_help(parent: tk.Misc, topic: HelpTopic) -> None:
    """Open a readable help page with a small physical sketch."""

    window = tk.Toplevel(parent)
    window.title(topic.title)
    window.transient(parent.winfo_toplevel())
    window.geometry("640x560")
    window.minsize(560, 500)

    body = ttk.Frame(window, padding=18)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text=topic.title, font=("TkDefaultFont", 16, "bold")).pack(anchor="w")
    if topic.units:
        ttk.Label(body, text=f"Units: {topic.units}", foreground="#52606b").pack(anchor="w", pady=(2, 8))

    diagram = tk.Canvas(body, height=145, background="#f5f8fa", highlightthickness=1, highlightbackground="#c8d1d8")
    diagram.pack(fill="x", pady=(4, 14))
    diagram.bind("<Configure>", lambda event: _draw_diagram(diagram, topic.diagram, event.width, event.height))

    for heading, text in (
        ("What this controls", topic.summary),
        ("Why it matters", topic.why),
        ("How to choose it", topic.choose),
    ):
        ttk.Label(body, text=heading, font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(4, 2))
        ttk.Label(body, text=text, wraplength=585, justify="left").pack(anchor="w", fill="x", pady=(0, 7))

    ttk.Button(body, text="Close", command=window.destroy).pack(anchor="e", pady=(8, 0))
    window.bind("<Escape>", lambda _event: window.destroy())


def _draw_diagram(canvas: tk.Canvas, kind: str, width: int, height: int) -> None:
    canvas.delete("all")
    w = max(width, 520)
    h = max(height, 130)
    blue, green, orange, red, ink = "#1877b8", "#168a61", "#df7b13", "#c53b3b", "#23313a"

    if kind == "gates":
        y = h * 0.68
        points = [(20, y), (w * 0.63, y), (w * 0.67, y - 70), (w * 0.72, y - 20), (w * 0.80, y), (w - 20, y)]
        canvas.create_line(*sum(([x, yy] for x, yy in points), []), fill=blue, width=2, smooth=True)
        canvas.create_rectangle(w * 0.16, 20, w * 0.40, h - 16, outline=orange, dash=(5, 3), width=2)
        canvas.create_rectangle(w * 0.62, 20, w * 0.84, h - 16, outline=green, dash=(5, 3), width=2)
        canvas.create_text(w * 0.28, 12, text="equal dark window", fill=orange)
        canvas.create_text(w * 0.73, 12, text="equal signal window", fill=green)
    elif kind in {"overvoltage", "vbr_fit", "pe_spacing"}:
        canvas.create_line(55, h - 28, w - 35, h - 28, arrow="last", fill=ink, width=2)
        x_vbr = w * 0.34
        x_bias = w * 0.78
        canvas.create_line(x_vbr, h - 48, x_vbr, h - 12, fill=red, width=3)
        canvas.create_line(x_bias, h - 48, x_bias, h - 12, fill=blue, width=3)
        canvas.create_line(x_vbr, 48, x_bias, 48, arrow="both", fill=green, width=3)
        canvas.create_text(x_vbr, h - 58, text="Vbr", fill=red, font=("TkDefaultFont", 10, "bold"))
        canvas.create_text(x_bias, h - 58, text="applied bias", fill=blue, font=("TkDefaultFont", 10, "bold"))
        canvas.create_text((x_vbr + x_bias) / 2, 34, text="overvoltage = bias - Vbr", fill=green)
    elif kind in {"attenuation", "scope_range", "threshold"}:
        canvas.create_text(70, h / 2, text="detector\npulse", fill=blue, font=("TkDefaultFont", 11, "bold"))
        canvas.create_line(115, h / 2, 205, h / 2, arrow="last", fill=ink, width=2)
        canvas.create_rectangle(210, 35, 330, h - 35, outline=orange, width=2)
        canvas.create_text(270, h / 2, text="probe\nattenuation")
        canvas.create_line(335, h / 2, 420, h / 2, arrow="last", fill=ink, width=2)
        canvas.create_rectangle(425, 25, w - 25, h - 25, outline=green, width=2)
        canvas.create_text((425 + w - 25) / 2, h / 2, text="scope range\nand trigger")
    elif kind == "statistics":
        canvas.create_text(80, 28, text="more tracks", fill=blue, font=("TkDefaultFont", 11, "bold"))
        for index, count in enumerate((4, 9, 16)):
            x = 55 + index * (w - 130) / 2
            for dot in range(count):
                canvas.create_oval(x + (dot % 4) * 10, 50 + (dot // 4) * 10, x + 6 + (dot % 4) * 10, 56 + (dot // 4) * 10, fill=blue, outline="")
            canvas.create_text(x + 18, h - 22, text=("large" if index == 0 else "smaller" if index == 2 else "") + " uncertainty")
    elif kind == "coincidence":
        canvas.create_line(40, 45, w - 40, 45, fill=blue, width=2)
        canvas.create_line(40, 95, w - 40, 95, fill=orange, width=2)
        canvas.create_oval(w * 0.48 - 6, 39, w * 0.48 + 6, 51, fill=blue, outline="")
        canvas.create_oval(w * 0.54 - 6, 89, w * 0.54 + 6, 101, fill=orange, outline="")
        canvas.create_line(w * 0.48, 70, w * 0.54, 70, arrow="both", fill=green, width=3)
        canvas.create_text(w * 0.51, 22, text="same particle when time difference is small", fill=green)
    elif kind == "sampling":
        canvas.create_line(25, h * 0.72, w - 25, h * 0.72, fill="#aeb8bf")
        for index in range(18):
            x = 35 + index * (w - 70) / 17
            y = h * 0.72 - 70 * max(0, 1 - abs(index - 9) / 4)
            canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=blue, outline="")
        canvas.create_text(w / 2, 18, text="closer samples describe the pulse shape", fill=ink)
    elif kind == "settling":
        canvas.create_line(35, h - 28, w - 30, h - 28, arrow="last", fill=ink)
        canvas.create_line(55, h - 38, 55, 28, fill=red, width=2)
        canvas.create_line(55, 28, w * 0.42, 65, w * 0.70, 55, w - 45, 55, fill=blue, smooth=True, width=3)
        canvas.create_text(82, 18, text="bias changed", fill=red)
        canvas.create_text(w * 0.70, 34, text="record only after stable", fill=green)
    else:
        labels = {
            "connection": ("SiPM / PCB", "Detector Pi", "Acquisition PC"),
            "files": ("settings", "raw waveforms", "plots + tables"),
            "safety": ("requested run", "final-state command", "verify voltage"),
            "control": ("one controller", "known bias", "valid result"),
            "identity": ("physical SiPM", "stable name", "traceable result"),
            "trigger_wait": ("wait for pulse", "timeout", "continue safely"),
        }.get(kind, ("setting", "saved configuration", "reproducible result"))
        positions = (w * 0.16, w * 0.50, w * 0.84)
        colors = (blue, orange, green)
        for index, (x, label, color) in enumerate(zip(positions, labels, colors)):
            canvas.create_rectangle(x - 62, 42, x + 62, 98, outline=color, width=2)
            canvas.create_text(x, 70, text=label, width=112, fill=ink)
            if index < 2:
                canvas.create_line(x + 66, 70, positions[index + 1] - 66, 70, arrow="last", fill=ink, width=2)
