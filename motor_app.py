"""VKMPD motor bediening: interface voor AQMD3605BLS-B2."""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter import font as tkfont

IMPORT_NAMES = {"pyserial": "serial"}
COLORS = {
    "navy": "#090B10", "canvas": "#0B0D12", "card": "#151922",
    "surface": "#202633", "white": "#F5F7FB", "ink": "#F0F3F8",
    "muted": "#A2ACBC", "line": "#303847", "blue": "#68A9FF",
    "blue_dark": "#4385DD", "green": "#65E0B6", "purple": "#B99AFF",
    "orange": "#F0B572", "red": "#FF687D", "soft_blue": "#1C2C43",
}


def _rounded_polygon(canvas, x1, y1, x2, y2, radius, fill, outline=""):
    radius = min(radius, max(2, (x2 - x1) / 2), max(2, (y2 - y1) / 2))
    points = [x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
              x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
              x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1]
    return canvas.create_polygon(points, smooth=True, splinesteps=20, fill=fill,
                                 outline=outline, width=1)


class RoundedCard(tk.Frame):
    """A responsive card with a rounded canvas background and themed content."""
    def __init__(self, master, title, padding=16):
        super().__init__(master, bg=COLORS["canvas"], bd=0, highlightthickness=0)
        self.canvas = tk.Canvas(self, bg=COLORS["canvas"], bd=0, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.inset = 10
        self.body = ttk.Frame(self.canvas, style="Card.TFrame", padding=padding)
        self.window = self.canvas.create_window((self.inset, self.inset), window=self.body, anchor="nw")
        ttk.Label(self.body, text=title, style="CardTitle.TLabel").pack(anchor="w", pady=(0, 10))
        self.content = ttk.Frame(self.body, style="Card.TFrame")
        self.content.pack(fill="both", expand=True)
        self.body.bind("<Configure>", self._body_configured)
        self.canvas.bind("<Configure>", self._canvas_configured)

    def _body_configured(self, _event=None):
        requested = max(self.body.winfo_reqheight() + self.inset * 2, 42)
        if int(float(self.canvas.cget("height"))) != requested:
            self.canvas.configure(height=requested)

    def _canvas_configured(self, event):
        self.canvas.delete("card-background")
        background = _rounded_polygon(self.canvas, 1, 1, event.width - 1, event.height - 1,
                                      16, COLORS["card"], COLORS["line"])
        self.canvas.addtag_withtag("card-background", background)
        self.canvas.itemconfigure(self.window, width=max(1, event.width - self.inset * 2),
                                  height=max(1, event.height - self.inset * 2))
        self.canvas.coords(self.window, self.inset, self.inset)
        self.canvas.tag_lower("card-background")


class PillButton(tk.Canvas):
    """A compact rounded clickable control used for prominent actions."""
    def __init__(self, master, text, command, color="surface", foreground="white",
                 height=38, padding=16, width=None, canvas_bg=None):
        self.text = text
        self.command = command
        self.color_key = color
        self.foreground_key = foreground
        self.fixed_width = width is not None
        self.enabled = True
        self.hovered = False
        self.pressed = False
        self.canvas_bg = canvas_bg or COLORS["card"]
        self.font = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        button_width = width or self.font.measure(text) + padding * 2
        super().__init__(master, width=button_width, height=height, bg=self.canvas_bg,
                         bd=0, highlightthickness=0, cursor="hand2")
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._draw()

    def _draw(self):
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width < 5 or height < 5:
            return
        fill = COLORS.get(self.color_key, self.color_key)
        fg = COLORS.get(self.foreground_key, self.foreground_key)
        if not self.enabled:
            fill, fg = COLORS["line"], COLORS["muted"]
        elif self.hovered:
            fill = {"blue": COLORS["blue_dark"], "green": "#43C99D",
                    "red": "#E44F67", "purple": "#A17FE6"}.get(self.color_key, COLORS["surface"])
        if self.pressed and self.enabled:
            fill = "#8E6BCF" if self.color_key == "purple" else COLORS["blue_dark"]
        _rounded_polygon(self, 1, 1, width - 1, height - 1, height / 2, fill)
        self.create_text(width / 2, height / 2, text=self.text, fill=fg,
                         font=self.font, justify="center")

    def _on_enter(self, _event):
        self.hovered = True
        self._draw()

    def _on_leave(self, _event):
        self.hovered = False
        self.pressed = False
        self._draw()

    def _on_press(self, _event):
        if self.enabled:
            self.pressed = True
            self._draw()

    def _on_release(self, event):
        invoke = self.enabled and self.pressed and 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        self.pressed = False
        self._draw()
        if invoke and self.command:
            self.command()

    def configure(self, cnf=None, **kwargs):
        if isinstance(cnf, dict):
            kwargs = {**cnf, **kwargs}
            cnf = None
        if "text" in kwargs:
            self.text = kwargs.pop("text")
            if not self.fixed_width:
                kwargs["width"] = self.font.measure(self.text) + 32
        if "state" in kwargs:
            self.enabled = kwargs.pop("state") != "disabled"
            self.configure(cursor="hand2" if self.enabled else "arrow")
        result = super().configure(cnf, **kwargs)
        self._draw()
        return result

    config = configure


def ensure_requirements():
    """Check requirements.txt and offer to install missing packages before startup."""
    requirements_file = Path(__file__).with_name("requirements.txt")
    if not requirements_file.is_file():
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Vereistenbestand ontbreekt", f"Niet gevonden naast de app:\n{requirements_file}\n\nPak de volledige projectmap uit en start motor_app.py opnieuw.")
        root.destroy()
        return False

    missing = []
    for line in requirements_file.read_text(encoding="utf-8-sig").splitlines():
        requirement = line.split("#", 1)[0].strip()
        if not requirement:
            continue
        package = re.split(r"[<>=!~;\[]", requirement, maxsplit=1)[0].strip()
        import_name = IMPORT_NAMES.get(package.lower().replace("_", "-"), package)
        try:
            available = importlib.util.find_spec(import_name) is not None
        except (ImportError, ValueError):
            available = False
        if not available:
            missing.append(package)
    if not missing:
        return True

    root = tk.Tk()
    root.withdraw()
    names = ", ".join(missing)
    if not messagebox.askyesno("Pakketten ontbreken", f"Deze pakketten ontbreken: {names}.\n\nWil je ze met pip installeren voor deze Python-versie?"):
        messagebox.showinfo("App niet gestart", f"Installeer handmatig vanuit PowerShell:\n\n\"{sys.executable}\" -m pip install -r \"{requirements_file}\"")
        root.destroy()
        return False
    progress = None
    try:
        progress = tk.Toplevel(root)
        progress.title("Installeren")
        progress.resizable(False, False)
        ttk.Label(progress, text="Pakketten worden geïnstalleerd…", padding=18).pack()
        progress.update_idletasks()
        result = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(requirements_file)], capture_output=True, text=True, timeout=300)
        progress.destroy()
        if result.returncode:
            details = (result.stderr or result.stdout or "pip gaf geen foutdetails.")[-3500:]
            messagebox.showerror("Installatie mislukt", f"Probeer handmatig:\n\n\"{sys.executable}\" -m pip install -r \"{requirements_file}\"\n\n{details}")
            root.destroy()
            return False
        messagebox.showinfo("Installatie voltooid", f"Geïnstalleerd: {names}")
    except Exception as exc:
        if progress is not None and progress.winfo_exists():
            progress.destroy()
        messagebox.showerror("Installatie mislukt", str(exc))
        root.destroy()
        return False
    root.destroy()
    return True


class MotorApp:
    """Tkinter presentation layer. Device logic lives in motor_controller.py."""
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("VKMPD | Motorbediening")
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        self.root.geometry(f"{min(1000, screen_width - 60)}x{min(790, screen_height - 100)}")
        self.root.minsize(680, 480)
        self.controller = MotorController()
        self.poll_job = None
        self.last_unit = "graden"
        self.units = tk.StringVar(value="graden")
        self.position_pulses_per_rev = tk.StringVar(value="24")
        self.auto_update = tk.BooleanVar(value=True)
        self.poll_interval = tk.StringVar(value="100")
        self.travel_limit = tk.StringVar(value="360")
        self.positive_limit = tk.StringVar(value="360")
        self.negative_limit = tk.StringVar(value="360")
        self.limit_mode = tk.StringVar(value="Symmetrisch (+/−)")
        self.last_limit_mode = self.limit_mode.get()
        self.scanning = False
        self.port = tk.StringVar()
        self.address = tk.StringVar(value="1")
        self.status = tk.StringVar(value="Niet verbonden · COM-poort invullen en op Verbinden klikken")
        self.position = tk.StringVar(value="—")
        self.motor_speed = tk.StringVar(value="—")
        self.motor_current = tk.StringVar(value="— A")
        self.motor_pwm = tk.StringVar(value="— %")
        self.bus_voltage = tk.StringVar(value="— V")
        self.commutation_frequency = tk.StringVar(value="— Hz")
        self.driver_fault = tk.StringVar(value="Nog niet uitgelezen")
        self.baudrate = tk.StringVar(value="9600")
        self.parity = tk.StringVar(value="E")
        self.speed = tk.StringVar(value="18000")
        self.acceleration = tk.StringVar(value="98302.5")
        self.target = tk.StringVar(value="10")
        self.desired_position = None
        self.chart_visible = False
        self.chart_samples = []
        self.chart_start_time = None
        self.chart_signals = {
            "position": tk.BooleanVar(value=True),
            "desired": tk.BooleanVar(value=True),
            "speed": tk.BooleanVar(value=True),
            "current": tk.BooleanVar(value=False),
        }
        self._configure_style()
        self._build()
        self.refresh_ports()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _configure_style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        self.root.configure(bg=COLORS["canvas"])
        style.configure("TFrame", background=COLORS["canvas"])
        style.configure("Canvas.TFrame", background=COLORS["canvas"])
        style.configure("CanvasMuted.TLabel", background=COLORS["canvas"], foreground=COLORS["muted"], font=("Segoe UI", 9))
        style.configure("Card.TFrame", background=COLORS["card"])
        style.configure("Card.TLabel", background=COLORS["card"], foreground=COLORS["ink"], font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", background=COLORS["card"], foreground=COLORS["green"], font=("Segoe UI", 9, "bold"))
        style.configure("TLabel", background=COLORS["card"], foreground=COLORS["ink"], font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=COLORS["card"], foreground=COLORS["muted"], font=("Segoe UI", 9))
        style.configure("Value.TLabel", background=COLORS["card"], foreground=COLORS["white"], font=("Segoe UI", 30, "bold"))
        style.configure("Section.TLabel", background=COLORS["card"], foreground=COLORS["white"], font=("Segoe UI", 10, "bold"))
        style.configure("TEntry", padding=8, fieldbackground=COLORS["surface"], foreground=COLORS["white"], bordercolor=COLORS["surface"], lightcolor=COLORS["surface"], darkcolor=COLORS["surface"], relief="flat")
        style.configure("TCombobox", padding=7, fieldbackground=COLORS["surface"], background=COLORS["surface"], foreground=COLORS["white"], arrowcolor=COLORS["green"], bordercolor=COLORS["surface"], lightcolor=COLORS["surface"], darkcolor=COLORS["surface"])
        style.map("TCombobox", fieldbackground=[("readonly", COLORS["surface"])], foreground=[("readonly", COLORS["white"])])
        style.configure("TSpinbox", padding=7, fieldbackground=COLORS["surface"], foreground=COLORS["white"], arrowcolor=COLORS["green"], bordercolor=COLORS["surface"], lightcolor=COLORS["surface"], darkcolor=COLORS["surface"])
        style.configure("TButton", padding=(11, 7), font=("Segoe UI", 9, "bold"), background=COLORS["surface"], foreground=COLORS["white"], borderwidth=0, focusthickness=0, relief="flat")
        style.map("TButton", background=[("active", COLORS["blue_dark"]), ("disabled", COLORS["line"])], foreground=[("disabled", COLORS["muted"])])
        style.configure("Primary.TButton", background=COLORS["green"], foreground=COLORS["navy"])
        style.map("Primary.TButton", background=[("active", "#43C99D")])
        style.configure("Stop.TButton", background=COLORS["red"], foreground=COLORS["white"], padding=(18, 11), font=("Segoe UI", 11, "bold"), borderwidth=0)
        style.map("Stop.TButton", background=[("active", "#E44F67")])
        style.configure("TCheckbutton", background=COLORS["card"], foreground=COLORS["ink"], font=("Segoe UI", 9))
        style.map("TCheckbutton", background=[("active", COLORS["card"])], foreground=[("active", COLORS["green"])])
        style.configure("TSeparator", background=COLORS["line"])
        style.configure("Vertical.TScrollbar", background=COLORS["surface"], troughcolor=COLORS["canvas"], bordercolor=COLORS["canvas"], arrowcolor=COLORS["muted"], lightcolor=COLORS["canvas"], darkcolor=COLORS["canvas"])

    def _build(self):
        header = tk.Frame(self.root, bg=COLORS["navy"], padx=28, pady=19)
        header.pack(fill="x")
        PillButton(header, "■  STOP MOTOR", self.stop, color="red", height=44,
                   canvas_bg=COLORS["navy"], width=150).pack(side="right", padx=(16, 0), fill="y")
        tk.Label(header, text="VKMPD", bg=COLORS["navy"], fg=COLORS["green"], font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Label(header, text="Motorbediening", bg=COLORS["navy"], fg=COLORS["white"], font=("Segoe UI", 22, "bold")).pack(anchor="w", pady=(2, 0))
        tk.Label(header, text="AQMD3605BLS-B2  ·  57BSA79-36-01  ·  Modbus RTU", bg=COLORS["navy"], fg=COLORS["muted"], font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 0))

        scroll_host = tk.Frame(self.root, bg=COLORS["canvas"])
        scroll_host.pack(fill="both", expand=True)
        self.scroll_canvas = tk.Canvas(scroll_host, bg=COLORS["canvas"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_host, orient="vertical", command=self.scroll_canvas.yview)
        self.scroll_canvas.configure(yscrollcommand=scrollbar.set)
        self.scroll_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        page = ttk.Frame(self.scroll_canvas, padding=(22, 18, 22, 14), style="Canvas.TFrame")
        self.page_window = self.scroll_canvas.create_window((0, 0), window=page, anchor="nw")
        page.bind("<Configure>", lambda _event: self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox("all")))
        self.scroll_canvas.bind("<Configure>", lambda event: self.scroll_canvas.itemconfigure(self.page_window, width=event.width))
        self.scroll_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        connection_card = RoundedCard(page, "VERBINDING", padding=14)
        connection_card.pack(fill="x", pady=(0, 14))
        connection = connection_card.content
        ttk.Label(connection, text="COM-poort", style="Muted.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.port_box = ttk.Combobox(connection, textvariable=self.port, width=12, state="normal")
        self.port_box.grid(row=0, column=1, sticky="w")
        self.refresh_button = PillButton(connection, "↻", self.refresh_ports, color="surface",
                                         foreground="green", width=36, height=34)
        self.refresh_button.grid(row=0, column=2, padx=(4, 8), sticky="w")
        self.scan_button = PillButton(connection, "Driver zoeken", self.scan_ports,
                                      color="blue", height=34)
        self.scan_button.grid(row=0, column=3, padx=(0, 16), sticky="w")
        ttk.Label(connection, text="Baudrate", style="Muted.TLabel").grid(row=0, column=4, sticky="w", padx=(0, 6))
        ttk.Combobox(connection, textvariable=self.baudrate, values=("9600", "19200", "115200"), width=9, state="readonly").grid(row=0, column=5, sticky="w")
        ttk.Label(connection, text="Parity", style="Muted.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Combobox(connection, textvariable=self.parity, values=("E", "N"), width=4, state="readonly").grid(row=1, column=1, sticky="w", pady=(8, 0))
        ttk.Label(connection, text="Slave-adres", style="Muted.TLabel").grid(row=1, column=2, sticky="w", padx=(8, 6), pady=(8, 0))
        ttk.Entry(connection, textvariable=self.address, width=5).grid(row=1, column=3, sticky="w", pady=(8, 0))
        self.connect_button = PillButton(connection, "Verbinden", self.connect,
                                         color="green", foreground="navy", height=34)
        self.connect_button.grid(row=1, column=5, padx=(12, 0), sticky="w", pady=(8, 0))
        self.status_label = ttk.Label(connection, textvariable=self.status, style="Muted.TLabel")
        self.status_label.configure(wraplength=760)
        self.status_label.grid(row=2, column=0, columnspan=6, sticky="w", pady=(10, 0))

        columns = ttk.Frame(page, style="Canvas.TFrame")
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(0, weight=6, uniform="col")
        columns.columnconfigure(1, weight=5, uniform="col")
        columns.rowconfigure(0, weight=1)
        left = ttk.Frame(columns, style="Canvas.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right = ttk.Frame(columns, style="Canvas.TFrame")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.columns = columns
        self.left_column = left
        self.right_column = right
        self.columns_stacked = None
        columns.bind("<Configure>", self._responsive_columns)

        position_card = RoundedCard(left, "HUIDIGE POSITIE", padding=18)
        position_card.pack(fill="x", pady=(0, 14))
        position = position_card.content
        ttk.Label(position, text="Aspositie vanaf het ingestelde nulpunt", style="Muted.TLabel").pack(anchor="w")
        value_row = ttk.Frame(position, style="Card.TFrame")
        value_row.pack(fill="x", pady=(4, 12))
        ttk.Label(value_row, textvariable=self.position, style="Value.TLabel").pack(side="left")
        PillButton(value_row, "Nu uitlezen", self.read_position, color="surface",
                   foreground="blue", height=34).pack(side="right", anchor="s", pady=(0, 4))
        ttk.Separator(position).pack(fill="x", pady=(2, 12))
        unit_row = ttk.Frame(position, style="Card.TFrame")
        unit_row.pack(fill="x")
        ttk.Label(unit_row, text="Weergave-eenheid", style="Muted.TLabel").pack(side="left")
        unit_box = ttk.Combobox(unit_row, textvariable=self.units, values=("graden", "radialen", "rotaties"), width=13, state="readonly")
        unit_box.pack(side="right")
        self.units.trace_add("write", lambda *_: self._update_units())
        speed_row = ttk.Frame(position, style="Card.TFrame")
        speed_row.pack(fill="x", pady=(12, 0))
        ttk.Label(speed_row, text="Motorsnelheid", style="Muted.TLabel").pack(side="left")
        ttk.Label(speed_row, textvariable=self.motor_speed, style="Section.TLabel").pack(side="left", padx=(6, 0))
        telemetry_row = ttk.Frame(position, style="Card.TFrame")
        telemetry_row.pack(fill="x", pady=(12, 0))
        ttk.Label(telemetry_row, text="Motorfasestroom", style="Muted.TLabel").pack(side="left")
        ttk.Label(telemetry_row, textvariable=self.motor_current, style="Section.TLabel").pack(side="left", padx=(6, 0))
        power_row = ttk.Frame(position, style="Card.TFrame")
        power_row.pack(fill="x", pady=(5, 0))
        ttk.Label(power_row, text="Busspanning", style="Muted.TLabel").pack(side="left")
        ttk.Label(power_row, textvariable=self.bus_voltage, style="Section.TLabel").pack(side="left", padx=(6, 18))
        ttk.Label(power_row, text="PWM-duty", style="Muted.TLabel").pack(side="left")
        ttk.Label(power_row, textvariable=self.motor_pwm, style="Section.TLabel").pack(side="left", padx=(6, 0))
        commutation_row = ttk.Frame(position, style="Card.TFrame")
        commutation_row.pack(fill="x", pady=(5, 0))
        ttk.Label(commutation_row, text="Hall-commutatie", style="Muted.TLabel").pack(side="left")
        ttk.Label(commutation_row, textvariable=self.commutation_frequency, style="Section.TLabel").pack(side="left", padx=(6, 0))
        fault_row = ttk.Frame(position, style="Card.TFrame")
        fault_row.pack(fill="x", pady=(5, 0))
        ttk.Label(fault_row, text="Driverstatus", style="Muted.TLabel").pack(side="left")
        self.driver_fault_label = ttk.Label(fault_row, textvariable=self.driver_fault, style="Section.TLabel")
        self.driver_fault_label.pack(side="left", padx=(6, 0))

        motion_card = RoundedCard(left, "BEWEGING", padding=18)
        motion_card.pack(fill="both", expand=True)
        motion = motion_card.content
        ttk.Label(motion, text="Doelpositie vanaf nulpunt", style="Section.TLabel").pack(anchor="w")
        ttk.Label(motion, text="Voer een doel binnen de ingestelde positielimiet in.", style="Muted.TLabel", wraplength=440).pack(anchor="w", pady=(3, 10))
        target_row = ttk.Frame(motion, style="Card.TFrame")
        target_row.pack(fill="x")
        ttk.Entry(target_row, textvariable=self.target, font=("Segoe UI", 14), width=14).pack(side="left", ipady=2)
        PillButton(target_row, "Beweeg naar doel  →", self.move_to, color="green",
                   foreground="navy", height=42).pack(side="left", padx=(10, 0))
        ttk.Label(motion, text="De as kan direct bewegen. Houd de as vrij en begin met lage limieten.", style="Muted.TLabel", wraplength=450).pack(anchor="w", pady=(14, 0))

        limits_card = RoundedCard(right, "SNELHEID & VERSNELLING", padding=18)
        limits_card.pack(fill="x", pady=(0, 14))
        limits = limits_card.content
        ttk.Label(limits, text="Maximums voor de positieregeling", style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
        self.speed_unit_label = ttk.Label(limits, text="Snelheid (°/s)", style="Section.TLabel")
        self.speed_unit_label.pack(anchor="w")
        speed_row = ttk.Frame(limits, style="Card.TFrame")
        speed_row.pack(fill="x", pady=(4, 10))
        ttk.Entry(speed_row, textvariable=self.speed).pack(side="left", fill="x", expand=True)
        self.speed_max_label = ttk.Label(speed_row, text="", style="Muted.TLabel")
        self.speed_max_label.pack(side="left", padx=(10, 0))
        self.accel_unit_label = ttk.Label(limits, text="Versnelling (°/s²)", style="Section.TLabel")
        self.accel_unit_label.pack(anchor="w")
        accel_row = ttk.Frame(limits, style="Card.TFrame")
        accel_row.pack(fill="x", pady=(4, 8))
        ttk.Entry(accel_row, textvariable=self.acceleration).pack(side="left", fill="x", expand=True)
        self.accel_max_label = ttk.Label(accel_row, text="", style="Muted.TLabel")
        self.accel_max_label.pack(side="left", padx=(10, 0))
        PillButton(limits, "Limieten toepassen", self.apply_limits, color="purple",
                   height=36).pack(anchor="e", pady=(4, 0))

        setup_card = RoundedCard(right, "NULPUNT & VERVERSEN", padding=18)
        setup_card.pack(fill="both", expand=True)
        setup = setup_card.content
        PillButton(setup, "Maak huidige positie nul", self.set_zero, color="purple",
                   height=36).pack(anchor="w")
        ttk.Label(setup, text="Nulpunt geldt voor deze sessie en wordt niet in de driver opgeslagen.", style="Muted.TLabel", wraplength=390).pack(anchor="w", pady=(6, 15))
        ttk.Separator(setup).pack(fill="x", pady=(0, 13))
        ttk.Label(setup, text="Softwarematige positielimiet vanaf nul", style="Section.TLabel").pack(anchor="w")
        mode_box = ttk.Combobox(setup, textvariable=self.limit_mode,
                                values=("Symmetrisch (+/−)", "Apart (+ en −)"),
                                state="readonly", width=22)
        mode_box.pack(anchor="w", pady=(5, 7))
        mode_box.bind("<<ComboboxSelected>>", self._change_limit_mode)
        self.limit_symmetric_row = ttk.Frame(setup, style="Card.TFrame")
        ttk.Label(self.limit_symmetric_row, text="±", style="Section.TLabel").pack(side="left", padx=(0, 5))
        ttk.Entry(self.limit_symmetric_row, textvariable=self.travel_limit, width=12).pack(side="left")
        self.travel_unit_sym_label = ttk.Label(self.limit_symmetric_row, text="°", style="Muted.TLabel")
        self.travel_unit_sym_label.pack(side="left", padx=(8, 0))
        self.limit_asymmetric_row = ttk.Frame(setup, style="Card.TFrame")
        ttk.Label(self.limit_asymmetric_row, text="+", style="Section.TLabel").pack(side="left", padx=(0, 4))
        ttk.Entry(self.limit_asymmetric_row, textvariable=self.positive_limit, width=9).pack(side="left")
        ttk.Label(self.limit_asymmetric_row, text="−", style="Section.TLabel").pack(side="left", padx=(12, 4))
        ttk.Entry(self.limit_asymmetric_row, textvariable=self.negative_limit, width=9).pack(side="left")
        self.travel_unit_asym_label = ttk.Label(self.limit_asymmetric_row, text="°", style="Muted.TLabel")
        self.travel_unit_asym_label.pack(side="left", padx=(8, 0))
        ttk.Label(setup, text="Geen vaste bovengrens; de driver gebruikt een 32-bit doelpositie.", style="Muted.TLabel", wraplength=390).pack(anchor="w", pady=(5, 13))
        ttk.Separator(setup).pack(fill="x", pady=(0, 12))
        ttk.Checkbutton(setup, text="Positie automatisch verversen", variable=self.auto_update, command=self._toggle_polling).pack(anchor="w")
        refresh = ttk.Frame(setup, style="Card.TFrame")
        refresh.pack(fill="x", pady=(7, 0))
        ttk.Label(refresh, text="Interval in milliseconden", style="Muted.TLabel").pack(side="left")
        ttk.Spinbox(refresh, from_=100, to=5000, increment=100, textvariable=self.poll_interval, width=9).pack(side="right")
        ttk.Label(setup, text="Pulsen per omwenteling", style="Section.TLabel").pack(anchor="w", pady=(14, 4))
        ttk.Entry(setup, textvariable=self.position_pulses_per_rev, width=12).pack(anchor="w")
        ttk.Label(setup, text="Kalibreer deze waarde vóór gebruik. 24 is alleen een startwaarde.", style="Muted.TLabel", wraplength=390).pack(anchor="w", pady=(5, 0))

        self.chart_toggle = PillButton(page, "▸  Livegrafiek tonen", self.toggle_chart,
                                       color="purple", canvas_bg=COLORS["canvas"], height=38)
        self.chart_toggle.pack(anchor="w", pady=(14, 0))
        self.chart_card = RoundedCard(page, "LIVEGRAFIEK", padding=12)
        chart_content = self.chart_card.content
        signal_row = ttk.Frame(chart_content, style="Card.TFrame")
        signal_row.pack(fill="x", pady=(0, 8))
        self.chart_checkbuttons = {}
        for key, label in (("position", "Positie"), ("desired", "Gewenste positie"),
                           ("speed", "Snelheid"), ("current", "Fasestroom (A)")):
            button = ttk.Checkbutton(signal_row, text=label, variable=self.chart_signals[key],
                                     command=self._draw_chart)
            button.pack(side="left", padx=(0, 14))
            self.chart_checkbuttons[key] = button
        self.chart_canvas = tk.Canvas(chart_content, height=260, bg=COLORS["card"],
                                      highlightthickness=0)
        self.chart_canvas.pack(fill="both", expand=True)
        self.chart_canvas.bind("<Configure>", lambda _event: self._draw_chart())
        ttk.Label(chart_content, text="Eén gedeelde schaal met 0 in het midden; de actuele waarden staan rechts bij de lijnen.",
                  style="Muted.TLabel", wraplength=900).pack(anchor="w", pady=(6, 0))

        footer = ttk.Frame(page, style="Canvas.TFrame")
        footer.pack(fill="x", pady=(14, 0))
        ttk.Label(footer, text="Gebruik fysieke begrenzing en houd de as vrij; de positielimiet geldt vanaf het nulpunt.", style="CanvasMuted.TLabel").pack(side="left", anchor="center")
        self._show_limit_row()
        self._update_units()

    def _responsive_columns(self, event=None):
        width = event.width if event else self.columns.winfo_width()
        stacked = width < 860
        if stacked == self.columns_stacked:
            return
        self.columns_stacked = stacked
        if stacked:
            self.columns.columnconfigure(0, weight=1, uniform="col")
            self.columns.columnconfigure(1, weight=0, uniform="col")
            self.columns.rowconfigure(0, weight=0)
            self.columns.rowconfigure(1, weight=0)
            self.left_column.grid_configure(row=0, column=0, padx=0, sticky="ew")
            self.right_column.grid_configure(row=1, column=0, padx=0, pady=(14, 0), sticky="ew")
        else:
            self.columns.columnconfigure(0, weight=6, uniform="col")
            self.columns.columnconfigure(1, weight=5, uniform="col")
            self.columns.rowconfigure(0, weight=1)
            self.columns.rowconfigure(1, weight=0)
            self.left_column.grid_configure(row=0, column=0, padx=(0, 8), pady=0, sticky="nsew")
            self.right_column.grid_configure(row=0, column=1, padx=(8, 0), pady=0, sticky="nsew")

    def _on_mousewheel(self, event):
        if event.delta:
            self.scroll_canvas.yview_scroll(-int(event.delta / 120), "units")

    def _unit_symbol(self):
        return {"graden": "°", "radialen": "rad", "rotaties": "rot"}[self.units.get()]

    def _speed_symbol(self):
        return "rps" if self.units.get() == "rotaties" else f"{self._unit_symbol()}/s"

    def _show_driver_telemetry(self, speed, current, fault_code, pwm_percent, bus_voltage, commutation_hz):
        fault_names = {
            0: "Geen fout", 1: "Niet ingeleerd", 2: "Gestopt",
            3: "Hall-sensorfout", 4: "Doelsnelheid niet gehaald",
            5: "Spoelfout", 6: "Overstroom", 7: "Overtemperatuur",
            8: "Overspanning", 9: "Onderspanning",
        }
        self.motor_speed.set(f"{speed:.2f} {self._speed_symbol()}")
        self.motor_current.set(f"{current:.2f} A")
        self.motor_pwm.set(f"{pwm_percent:.1f} %")
        self.bus_voltage.set(f"{bus_voltage:.1f} V")
        self.commutation_frequency.set(f"{commutation_hz:.1f} Hz")
        state = fault_names.get(fault_code, f"Onbekende status {fault_code}")
        self.driver_fault.set(f"{state} ({fault_code})")
        self.driver_fault_label.configure(
            foreground=COLORS["green"] if fault_code == 0 else COLORS["red"])

    def _read_chart_sample(self):
        try:
            self.controller.pulses_per_revolution = float(self.position_pulses_per_rev.get())
            position, speed, current, fault_code, pwm_percent, bus_voltage, commutation_hz = self.controller.telemetry(self.units.get())
            self._show_driver_telemetry(speed, current, fault_code, pwm_percent, bus_voltage, commutation_hz)
            now = time.monotonic()
            if self.chart_start_time is None:
                self.chart_start_time = now
            if self.desired_position is None:
                self.desired_position = position
            self.chart_samples.append({
                "time": now - self.chart_start_time,
                "position": position,
                "desired": self.desired_position,
                "speed": speed,
                "current": current,
            })
            if len(self.chart_samples) > 300:
                self.chart_samples.pop(0)
            self.position.set(f"{position:.3f} {self._unit_symbol()}")
            self._draw_chart()
        except Exception as exc:
            self.status.set(f"Grafiekmeting mislukt: {exc}")

    def _draw_chart(self):
        if not hasattr(self, "chart_canvas"):
            return
        canvas = self.chart_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 400)
        height = max(canvas.winfo_height(), 180)
        selected = [
            ("position", "Positie", "#2878D0", self._unit_symbol()),
            ("desired", "Gewenste positie", "#9B59B6", self._unit_symbol()),
            ("speed", "Snelheid", "#16845B", self._speed_symbol()),
            ("current", "Fasestroom", COLORS["red"], "A"),
        ]
        selected = [item for item in selected if self.chart_signals[item[0]].get()]
        if not selected:
            canvas.create_text(width / 2, height / 2, text="Selecteer minimaal één signaal",
                               fill=COLORS["muted"], font=("Segoe UI", 11))
            return
        if not self.chart_samples:
            canvas.create_text(width / 2, height / 2, text="Verbind met de driver om meetwaarden te zien",
                               fill=COLORS["muted"], font=("Segoe UI", 11))
            return

        left, right, top, bottom = 74, width - 172, 22, height - 30
        first_time = self.chart_samples[0]["time"]
        last_time = self.chart_samples[-1]["time"]
        time_span = max(last_time - first_time, 0.001)
        all_values = [sample[key] for sample in self.chart_samples
                      for key, _, _, _ in selected if sample[key] is not None]
        amplitude = max((abs(value) for value in all_values), default=0)
        amplitude = max(amplitude * 1.08, 1.0)
        for tick in range(5):
            fraction = tick / 4
            value = -amplitude + 2 * amplitude * fraction
            y = bottom - (value + amplitude) / (2 * amplitude) * (bottom - top)
            canvas.create_line(left, y, right, y, fill=COLORS["line"])
            canvas.create_text(left - 8, y, text=f"{value:.3g}", anchor="e",
                               fill=COLORS["muted"], font=("Segoe UI", 8))
        zero_y = (top + bottom) / 2
        canvas.create_line(left, zero_y, right, zero_y, fill="#8795A5", width=2)
        current_labels = []
        for key, _label, color, _unit in selected:
            points = [(sample["time"], sample[key]) for sample in self.chart_samples
                      if sample[key] is not None]
            coords = []
            for sample_time, value in points:
                x = left + (sample_time - first_time) / time_span * (right - left)
                value = max(-amplitude, min(value, amplitude))
                y = bottom - (value + amplitude) / (2 * amplitude) * (bottom - top)
                coords.extend((x, y))
            if len(coords) >= 4:
                canvas.create_line(*coords, fill=color, width=2)
            elif coords:
                x, y = coords
                canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=color, outline=color)
            if points:
                _label, unit = next((label, unit) for signal_key, label, _signal_color, unit in selected
                                    if signal_key == key)
                current_value = points[-1][1]
                value_y = bottom - (max(-amplitude, min(current_value, amplitude)) + amplitude) / (2 * amplitude) * (bottom - top)
                short_name = {"position": "Pos", "desired": "Doel", "speed": "Snelheid", "current": "Stroom"}[key]
                current_labels.append((value_y, color, f"{short_name}: {current_value:.4g} {unit}"))

        current_labels.sort(key=lambda item: item[0])
        label_gap = 15
        label_ys = []
        for value_y, _color, _text in current_labels:
            label_ys.append(max(value_y, top + 7) if not label_ys else max(value_y, label_ys[-1] + label_gap))
        if label_ys and label_ys[-1] > bottom - 7:
            shift = label_ys[-1] - (bottom - 7)
            label_ys = [y - shift for y in label_ys]
        for (value_y, color, label), label_y in zip(current_labels, label_ys):
            canvas.create_line(right, value_y, right + 6, label_y, fill=color, width=1)
            canvas.create_text(right + 9, label_y, text=label, anchor="w", fill=color,
                               font=("Segoe UI", 8, "bold"))
        canvas.create_text(left, height - 6, text=f"{first_time:.1f} s", anchor="sw",
                           fill=COLORS["muted"], font=("Segoe UI", 8))
        canvas.create_text(right, height - 6, text=f"{last_time:.1f} s", anchor="se",
                           fill=COLORS["muted"], font=("Segoe UI", 8))

    def toggle_chart(self):
        self.chart_visible = not self.chart_visible
        if self.chart_visible:
            self.chart_card.pack(fill="x", pady=(8, 0), before=self.chart_toggle.master.winfo_children()[-1])
            self.chart_toggle.configure(text="▾  Livegrafiek verbergen")
            self._draw_chart()
            if self.controller.client:
                self._schedule_position_poll()
        else:
            self.chart_card.pack_forget()
            self.chart_toggle.configure(text="▸  Livegrafiek tonen")
            if not self.auto_update.get() and self.poll_job is not None:
                self.root.after_cancel(self.poll_job)
                self.poll_job = None

    def _show_limit_row(self):
        self.limit_symmetric_row.pack_forget()
        self.limit_asymmetric_row.pack_forget()
        row = self.limit_symmetric_row if self.limit_mode.get().startswith("Symmetrisch") else self.limit_asymmetric_row
        row.pack(anchor="w")

    def _change_limit_mode(self, _event=None):
        new_mode = self.limit_mode.get()
        try:
            if new_mode.startswith("Apart") and self.last_limit_mode.startswith("Symmetrisch"):
                value = self.travel_limit.get()
                self.positive_limit.set(value)
                self.negative_limit.set(value)
            elif new_mode.startswith("Symmetrisch") and self.last_limit_mode.startswith("Apart"):
                positive = abs(float(self.positive_limit.get()))
                negative = abs(float(self.negative_limit.get()))
                self.travel_limit.set(f"{min(positive, negative):.6g}")
        except ValueError:
            pass
        self.last_limit_mode = new_mode
        self._show_limit_row()

    def _limit_bounds(self):
        if self.limit_mode.get().startswith("Symmetrisch"):
            limit = float(self.travel_limit.get())
            return limit, limit
        return float(self.positive_limit.get()), float(self.negative_limit.get())

    def _set_scanning(self, scanning):
        self.scanning = scanning
        state = "disabled" if scanning else "normal"
        self.scan_button.configure(state=state)
        self.connect_button.configure(state=state)

    def refresh_ports(self):
        """List Windows COM ports without probing them for a motor driver."""
        try:
            ports = MotorController.available_ports()
            self.port_box["values"] = ports
            if ports and self.port.get() not in ports:
                self.port.set(ports[0])
            if not ports:
                self.status.set("Geen COM-poorten gevonden · je kunt ook een poortnaam invullen")
            elif not self.controller.client:
                self.status.set(f"{len(ports)} COM-poort(en) beschikbaar · kies een poort en klik op Verbinden")
        except Exception as exc:
            self.status.set(f"COM-poorten ophalen mislukt: {exc}")

    def _update_units(self):
        new_unit = self.units.get()
        radians_per_unit = MotorController.radians_per_unit
        if new_unit != self.last_unit:
            factor = radians_per_unit(self.last_unit) / radians_per_unit(new_unit)
            for variable in (self.target, self.speed, self.acceleration, self.travel_limit,
                             self.positive_limit, self.negative_limit):
                try:
                    variable.set(f"{float(variable.get()) * factor:.6g}")
                except ValueError:
                    pass
            for sample in self.chart_samples:
                for key in ("position", "desired", "speed"):
                    if sample[key] is not None:
                        sample[key] *= factor
            if self.desired_position is not None:
                self.desired_position *= factor
            self.last_unit = new_unit
            if self.controller.client:
                self.read_position()
            self._draw_chart()
        symbol = {"graden": "°", "radialen": "rad", "rotaties": "rot"}[new_unit]
        max_accel = (6553.5 * 3.141592653589793 / 12) / radians_per_unit(new_unit)
        max_speed = (MAX_RPM * 2 * 3.141592653589793 / 60) / radians_per_unit(new_unit)
        self.speed_unit_label.configure(text=f"Snelheid ({self._speed_symbol()})")
        self.accel_unit_label.configure(text=f"Versnelling ({symbol}/s²)")
        if hasattr(self, "chart_checkbuttons"):
            self.chart_checkbuttons["position"].configure(text=f"Positie ({symbol})")
            self.chart_checkbuttons["desired"].configure(text=f"Gewenst ({symbol})")
            self.chart_checkbuttons["speed"].configure(text=f"Snelheid ({self._speed_symbol()})")
        self.travel_unit_sym_label.configure(text=symbol)
        self.travel_unit_asym_label.configure(text=symbol)
        self.speed_max_label.configure(text=f"Max {max_speed:,.1f} {self._speed_symbol()}")
        self.accel_max_label.configure(text=f"Max {max_accel:,.0f} {symbol}/s²")

    def _toggle_polling(self):
        if not self.auto_update.get() and not self.chart_visible:
            if self.poll_job is not None:
                self.root.after_cancel(self.poll_job)
                self.poll_job = None
        elif self.controller.client:
            self._schedule_position_poll()

    def _schedule_position_poll(self):
        if (not self.controller.client or (not self.auto_update.get() and not self.chart_visible)
                or self.poll_job is not None):
            return
        try:
            interval = int(self.poll_interval.get())
            if not 100 <= interval <= 5000:
                raise ValueError
        except ValueError:
            interval = 500
            self.poll_interval.set("500")
        self.poll_job = self.root.after(interval, self._poll_position)

    def _poll_position(self):
        self.poll_job = None
        if self.chart_visible:
            self._read_chart_sample()
        elif self.auto_update.get():
            self.read_position(show_errors=False)
        if self.auto_update.get() or self.chart_visible:
            self._schedule_position_poll()

    def scan_ports(self):
        if self.scanning:
            return
        try:
            ports = MotorController.available_ports()
        except Exception as exc:
            self.status.set(f"COM-poorten ophalen mislukt: {exc}")
            return
        self.port_box["values"] = ports
        if ports and self.port.get() not in ports:
            self.port.set(ports[0])
        if not ports:
            self.status.set("Geen COM-poorten gevonden")
            return
        self.status.set(f"Stap 1/3 · {len(ports)} COM-poort(en) gevonden · driver zoeken…")
        self._set_scanning(True)
        threading.Thread(target=self._probe_ports, args=(ports,), daemon=True).start()

    def _probe_ports(self, ports):
        result = self.controller.scan_and_connect(
            ports, report_progress=lambda text: self.root.after(0, self.status.set, text))
        if result:
            self.root.after(0, self._found_device, *result)
        else:
            self.root.after(0, self._scan_failed)

    def _scan_failed(self):
        self._set_scanning(False)
        self.status.set("Geen driver gevonden · controleer DIP 8, A/B, baudrate en slave-ID")

    def _found_device(self, port, baud, address, parity, stopbits, identity):
        self.port.set(port)
        self.address.set(str(address))
        self.baudrate.set(str(baud))
        self.parity.set(parity)
        self._set_scanning(False)
        note = self._speed_config_note()
        self.status.set(f"Verbonden · {port} · {baud} baud · {parity}{stopbits} · slave {address} · ID 0x{identity:04X}{note}")
        self.read_position()
        self._schedule_position_poll()

    def _speed_config_note(self):
        try:
            poles, ratio = self.controller.speed_configuration()
            if poles != 8 or abs(ratio - 1.0) > 0.001:
                return f" · controleer snelheidsconfiguratie: {poles} polen, ratio {ratio:g}; verwacht 8 en 1,0"
        except Exception:
            return " · snelheidsconfiguratie niet uitleesbaar"
        return ""

    def connect(self):
        try:
            address = int(self.address.get())
            self.controller.baudrate = int(self.baudrate.get())
            self.controller.parity = self.parity.get()
            self.controller.stopbits = 1
            if self.controller.client and (self.controller.port != self.port.get() or self.controller.unit_id != address):
                self.controller.close()
            identity = self.controller.connect(self.port.get(), address)
            note = self._speed_config_note()
            self.status.set(f"Verbonden · {self.port.get()} · slave {address} · ID 0x{identity:04X}{note}")
            self.read_position()
            self._schedule_position_poll()
        except Exception as exc:
            self.status.set("Verbinding mislukt")
            messagebox.showerror("Verbinding", str(exc))

    def read_position(self, show_errors=True):
        try:
            self.controller.pulses_per_revolution = float(self.position_pulses_per_rev.get())
            value, speed, current, fault_code, pwm_percent, bus_voltage, commutation_hz = self.controller.telemetry(self.units.get())
            self._show_driver_telemetry(speed, current, fault_code, pwm_percent, bus_voltage, commutation_hz)
            symbol = {"graden": "°", "radialen": "rad", "rotaties": "rot"}[self.units.get()]
            self.position.set(f"{value:.3f} {symbol}")
            if self.desired_position is None:
                self.desired_position = value
        except Exception as exc:
            if show_errors:
                messagebox.showerror("Positie uitlezen", str(exc))
            else:
                self.status.set(f"Automatische positie-update mislukt: {exc}")

    def set_zero(self):
        try:
            self.controller.set_zero()
            self.desired_position = 0.0
            self.chart_samples.clear()
            self.chart_start_time = None
            symbol = {"graden": "°", "radialen": "rad", "rotaties": "rot"}[self.units.get()]
            self.position.set(f"0.000 {symbol}")
            self._draw_chart()
        except Exception as exc:
            messagebox.showerror("Nulpunt", str(exc))

    def apply_limits(self):
        try:
            self.controller.pulses_per_revolution = float(self.position_pulses_per_rev.get())
            self.controller.apply_limits(self.speed.get(), self.acceleration.get(), self.units.get())
            self.status.set("Snelheids- en versnellingslimiet zijn toegepast")
        except Exception as exc:
            messagebox.showerror("Limieten toepassen", str(exc))

    def move_to(self):
        try:
            self.controller.pulses_per_revolution = float(self.position_pulses_per_rev.get())
            positive_limit, negative_limit = self._limit_bounds()
            current = self.controller.move_to(self.target.get(), positive_limit, negative_limit,
                                              self.speed.get(), self.acceleration.get(), self.units.get())
            self.desired_position = float(self.target.get())
            self.status.set(f"Positiecommando verzonden · huidige pulsen {current}")
            self._draw_chart()
        except Exception as exc:
            messagebox.showerror("Bewegen naar doel", str(exc))

    def stop(self):
        try:
            self.controller.stop()
            self.status.set("Normale stop verzonden")
        except Exception as exc:
            messagebox.showerror("Stop", str(exc))

    def close(self):
        if self.poll_job is not None:
            self.root.after_cancel(self.poll_job)
            self.poll_job = None
        self.controller.close()
        self.root.destroy()


if __name__ == "__main__":
    if not ensure_requirements():
        raise SystemExit(1)
    from motor_controller import MAX_RPM, MotorController

    root = tk.Tk()
    MotorApp(root)
    root.mainloop()
