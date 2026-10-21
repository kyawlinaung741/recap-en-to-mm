from __future__ import annotations

import re
import shutil
from pathlib import Path
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from preview_tools import extract_preview_frame, probe_duration
from subtitle_service import POSITIONS, ass_colour, burn_subtitles, mux_soft_subtitles


class SubtitleTab(ttk.Frame):
    """Standalone subtitle editor for an existing voice-synced SRT + video."""

    def __init__(self, parent, *, cfg: dict, tool, colors: dict[str, str]):
        super().__init__(parent)
        self.cfg = cfg
        self.tool = tool
        self.colors = colors
        self.video = tk.StringVar()
        self.srt = tk.StringVar()
        self.position = tk.StringVar(value="Bottom Center")
        self.font_size = tk.DoubleVar(value=30)
        self.opacity = tk.DoubleVar(value=1.0)
        self.margin = tk.DoubleVar(value=42)
        self.color = tk.StringVar(value="#FFFFFF")
        self.preview_time = tk.DoubleVar(value=0.0)
        self.rows: list[dict] = []
        self.duration = 0.0
        self.generate_srt = tk.BooleanVar(value=True)
        self.soft_track = tk.BooleanVar(value=False)
        self.burn_in = tk.BooleanVar(value=True)
        self.mode = tk.StringVar(value="Burn-in MP4")
        self._photo = None
        self._frame_photo = None
        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        top = ttk.Frame(self, padding=10)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Video").grid(row=0, column=0, padx=(0, 6))
        ttk.Entry(top, textvariable=self.video).grid(row=0, column=1, sticky="ew")
        ttk.Button(top, text="Browse", command=self._browse_video).grid(row=0, column=2, padx=5)
        ttk.Label(top, text="SRT").grid(row=1, column=0, padx=(0, 6), pady=(6, 0))
        ttk.Entry(top, textvariable=self.srt).grid(row=1, column=1, sticky="ew", pady=(6, 0))
        ttk.Button(top, text="Browse", command=self._browse_srt).grid(row=1, column=2, padx=5, pady=(6, 0))

        body = ttk.Panedwindow(self, orient="horizontal")
        body.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        preview_box = ttk.LabelFrame(body, text="Subtitle Preview", padding=8)
        controls = ttk.LabelFrame(body, text="Subtitle Settings / Export", padding=10)
        body.add(preview_box, weight=4)
        body.add(controls, weight=2)
        preview_box.rowconfigure(0, weight=1)
        preview_box.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(preview_box, background="#10131a", highlightthickness=0, height=420)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        seek = ttk.Frame(preview_box)
        seek.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        seek.columnconfigure(0, weight=1)
        ttk.Scale(seek, from_=0, to=1, variable=self.preview_time, command=lambda _v: self._draw()).grid(row=0, column=0, sticky="ew")
        self.time_label = ttk.Label(seek, text="0:00 / 0:00", width=14, anchor="e")
        self.time_label.grid(row=0, column=1, padx=(8, 0))

        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="Position").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Combobox(controls, textvariable=self.position, values=tuple(POSITIONS), state="readonly").grid(row=0, column=1, sticky="ew", pady=4)
        self._slider(controls, 1, "Size", 10, 96, self.font_size, "size_value", "")
        self._slider(controls, 2, "Opacity", 0.10, 1.00, self.opacity, "opacity_value", "%", steps=100)
        self._slider(controls, 3, "Margin", 0, 500, self.margin, "margin_value", "")
        color_row = ttk.Frame(controls)
        color_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Label(color_row, text="Color", width=10).pack(side="left")
        self.swatch = tk.Label(color_row, text="   ", bg=self.color.get(), relief="sunken")
        self.swatch.pack(side="left", padx=6)
        ttk.Button(color_row, text="Choose", command=self._choose_color).pack(side="left")
        ttk.Separator(controls).grid(row=5, column=0, columnspan=2, sticky="ew", pady=8)
        ttk.Label(controls, text="Subtitle mode").grid(row=6, column=0, sticky="w", pady=4)
        mode_combo = ttk.Combobox(controls, textvariable=self.mode,
                     values=("SRT only", "Soft subtitle MP4", "Burn-in MP4", "Both"), state="readonly")
        mode_combo.grid(row=6, column=1, sticky="ew", pady=4)
        mode_combo.bind("<<ComboboxSelected>>", lambda _e: self._mode_changed())
        ttk.Checkbutton(controls, text="Generate SRT file", variable=self.generate_srt).grid(row=7, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(controls, text="Add soft subtitle track", variable=self.soft_track).grid(row=8, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(controls, text="Burn subtitles into video", variable=self.burn_in).grid(row=9, column=0, columnspan=2, sticky="w")
        ttk.Button(controls, text="Load / Refresh Preview", command=self._load).grid(row=10, column=0, columnspan=2, sticky="ew", pady=(14, 5))
        ttk.Button(controls, text="Export Selected Mode", command=self._export).grid(row=11, column=0, columnspan=2, sticky="ew")
        ttk.Label(controls, text="အသံ timing ပါတဲ့ SRT ကိုပဲ ရွေးပါ။\nPreview time ရွှေ့ပြီး စာတန်းကို ကြည့်နိုင်ပါတယ်။", style="Muted.TLabel").grid(row=12, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self._draw()

    def _slider(self, parent, row, label, low, high, var, attr, suffix, steps=None):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=4)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text=label, width=10).grid(row=0, column=0, sticky="w")
        ttk.Scale(frame, from_=low, to=high, variable=var, command=lambda _v: self._slider_changed(var, attr, suffix, steps)).grid(row=0, column=1, sticky="ew")
        label_widget = ttk.Label(frame, text="", width=8, anchor="e")
        label_widget.grid(row=0, column=2, padx=(6, 0))
        setattr(self, attr, label_widget)
        self._slider_changed(var, attr, suffix, steps)

    def _slider_changed(self, var, attr, suffix, steps=None):
        value = float(var.get())
        if steps == 100:
            text = f"{value * 100:.0f}%"
        else:
            text = f"{value:.0f}{suffix}"
        getattr(self, attr).configure(text=text)
        self._draw()

    def _mode_changed(self):
        mode = self.mode.get()
        self.generate_srt.set(True)
        self.soft_track.set(mode in {"Soft subtitle MP4", "Both"})
        self.burn_in.set(mode in {"Burn-in MP4", "Both"})

    def _browse_video(self):
        p = filedialog.askopenfilename(filetypes=[("Video", "*.mp4 *.mkv *.mov *.webm *.avi"), ("All", "*.*")])
        if p:
            self.video.set(p)
            self._load()

    def _browse_srt(self):
        p = filedialog.askopenfilename(filetypes=[("SRT", "*.srt"), ("All", "*.*")])
        if p:
            self.srt.set(p)
            self._load()

    @staticmethod
    def _parse_time(value: str) -> float:
        h, m, rest = value.replace(",", ".").split(":")
        return int(h) * 3600 + int(m) * 60 + float(rest)

    def _load_rows(self):
        text = Path(self.srt.get()).read_text(encoding="utf-8-sig")
        blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
        rows = []
        for block in blocks:
            lines = block.strip().splitlines()
            if len(lines) < 3 or "-->" not in lines[1]:
                continue
            start, end = [x.strip() for x in lines[1].split("-->", 1)]
            rows.append({"start": self._parse_time(start), "end": self._parse_time(end), "text": "\n".join(lines[2:])})
        self.rows = rows
        self.duration = max([float(row["end"]) for row in rows] or [0.0])

    def _load(self):
        try:
            if Path(self.srt.get()).is_file():
                self._load_rows()
            if Path(self.video.get()).is_file():
                self.duration = max(self.duration, probe_duration(self.tool("ffprobe"), Path(self.video.get())))
                frame = Path(self.video.get()).parent / ".subtitle_preview.png"
                extract_preview_frame(self.tool("ffmpeg"), self.video.get(), float(self.preview_time.get()),
                                      1.0, False, str(frame), 960, 540, ratio="16:9", fill="black")
                self._frame_photo = tk.PhotoImage(file=str(frame))
            self._draw()
        except Exception as exc:
            messagebox.showerror("Subtitle preview", str(exc))

    def _draw(self):
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("all")
        w = max(320, self.canvas.winfo_width())
        h = max(180, self.canvas.winfo_height())
        self.canvas.create_rectangle(0, 0, w, h, fill="#10131a", outline="")
        if self._frame_photo:
            self.canvas.create_image(w / 2, h / 2, image=self._frame_photo, anchor="center")
        now = float(self.preview_time.get())
        row = next((x for x in self.rows if x["start"] <= now <= x["end"]), None)
        if row:
            position = self.position.get()
            x = w * (0.5 if "Left" not in position and "Right" not in position else (0.08 if "Left" in position else 0.92))
            y = h * (0.14 if "Top" in position else (0.5 if "Middle" in position or position == "Center" else 0.88))
            anchor = "center" if "Center" in position or position == "Center" else ("w" if "Left" in position else "e")
            self.canvas.create_text(x + 2, y + 2, text=row["text"], fill="#000000", anchor=anchor, font=("Myanmar Text", max(12, int(self.font_size.get() * w / 1280)), "bold"), width=int(w * .86))
            self.canvas.create_text(x, y, text=row["text"], fill=self.color.get(), anchor=anchor, font=("Myanmar Text", max(12, int(self.font_size.get() * w / 1280)), "bold"), width=int(w * .86))
        self.time_label.configure(text=f"{int(now)//60}:{int(now)%60:02d} / {int(self.duration)//60}:{int(self.duration)%60:02d}")

    def _choose_color(self):
        picked = colorchooser.askcolor(color=self.color.get(), title="Choose subtitle color")
        if picked and picked[1]:
            self.color.set(picked[1].upper())
            self.swatch.configure(bg=picked[1])
            self._draw()

    def _export(self):
        if not Path(self.video.get()).is_file() or not Path(self.srt.get()).is_file():
            messagebox.showinfo("Subtitle export", "Video နဲ့ SRT ဖိုင်ကို အရင်ရွေးပါ။")
            return
        mode = self.mode.get()
        folder = filedialog.askdirectory(title="Choose output folder")
        if not folder:
            return
        try:
            video = Path(self.video.get())
            srt = Path(self.srt.get())
            out_dir = Path(folder)
            outputs = []
            if self.generate_srt.get() or mode == "SRT only":
                target = out_dir / f"{video.stem}_Myanmar.srt"
                shutil.copy2(srt, target)
                outputs.append(target)
            if self.soft_track.get() or mode in {"Soft subtitle MP4", "Both"}:
                target = out_dir / f"{video.stem}_soft.mp4"
                mux_soft_subtitles(self.tool("ffmpeg"), video, None, srt, target)
                outputs.append(target)
            if self.burn_in.get() or mode in {"Burn-in MP4", "Both"}:
                target = out_dir / f"{video.stem}_burned.mp4"
                burn_subtitles(self.tool("ffmpeg"), video, srt, target, position=self.position.get(), font_size=int(self.font_size.get()), margin=int(self.margin.get()), primary_colour=ass_colour(self.color.get(), self.opacity.get()))
                outputs.append(target)
            messagebox.showinfo("Subtitle export", "ပြီးပါပြီ။\n\n" + "\n".join(str(x) for x in outputs))
        except Exception as exc:
            messagebox.showerror("Subtitle export", str(exc))
