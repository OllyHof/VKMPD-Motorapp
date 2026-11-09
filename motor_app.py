"""Simple Modbus RTU control panel for the AKELC AQMD3605BLS-B2.

Install dependencies with: py -m pip install -r requirements.txt
Run with: py motor_app.py
"""
from __future__ import annotations

import math
import importlib.util
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk


IMPORT_NAMES = {"pyserial": "serial"}


def ensure_requirements():
    """Check requirements.txt and offer to install missing packages before app startup."""
    requirements_file = Path(__file__).with_name("requirements.txt")
    if not requirements_file.is_file():
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Vereistenbestand ontbreekt",
            f"Ik kan requirements.txt niet vinden naast de app:\n{requirements_file}\n\n"
            "Pak de volledige ZIP-map uit en start motor_app.py opnieuw.",
        )
        root.destroy()
        return False

    missing = []
    for line in requirements_file.read_text(encoding="utf-8").splitlines():
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
    install = messagebox.askyesno(
        "Pakketten ontbreken",
        f"Deze vereiste pakketten ontbreken: {names}.\n\n"
        "Wil je ze nu installeren met pip? De installatie gebruikt de Python-versie "
        "waarmee je deze app hebt gestart.",
    )
    if not install:
        messagebox.showinfo(
            "App niet gestart",
            "Installeer de pakketten handmatig vanuit PowerShell met:\n\n"
            f'"{sys.executable}" -m pip install -r "{requirements_file}"',
        )
        root.destroy()
        return False

    progress = None
    try:
        progress = tk.Toplevel(root)
        progress.title("Pakketten installeren")
        progress.resizable(False, False)
        ttk.Label(progress, text="Pip installeert de ontbrekende pakketten…", padding=18).pack()
        progress.update_idletasks()
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(requirements_file)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        progress.destroy()
        if result.returncode != 0:
            details = (result.stderr or result.stdout or "pip gaf geen foutdetails.")[-3500:]
            messagebox.showerror(
                "Installatie mislukt",
                "Pip kon de vereiste pakketten niet installeren.\n\n"
                f"Probeer dit handmatig in PowerShell:\n\n"
                f'"{sys.executable}" -m pip install -r "{requirements_file}"\n\n'
                f"Details:\n{details}",
            )
            root.destroy()
            return False
        messagebox.showinfo("Installatie voltooid", f"De ontbrekende pakketten zijn geïnstalleerd.\n\n{names}")
    except Exception as exc:
        if progress is not None and progress.winfo_exists():
            progress.destroy()
        messagebox.showerror("Installatie mislukt", f"Pip starten is niet gelukt:\n{exc}")
        root.destroy()
        return False

    root.destroy()
    return True


if not ensure_requirements():
    raise SystemExit(1)

import serial
from serial.tools import list_ports


DEFAULT_BAUD = 9600
MOTOR_POLES = 8


class RtuResponse:
    def __init__(self, registers=None, error=None):
        self.registers = registers or []
        self.error = error

    def isError(self):
        return self.error is not None

    def __str__(self):
        return self.error or f"{self.registers}"


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


class RtuSerialClient:
    """Small synchronous Modbus RTU client for the two function codes this app needs."""
    def __init__(self, *, port, baudrate, bytesize, parity, stopbits, timeout, retries=0):
        self.port = port
        self.settings = dict(baudrate=baudrate, bytesize=bytesize, parity=parity,
                             stopbits=stopbits, timeout=timeout, write_timeout=timeout)
        self.connection = None

    def connect(self):
        if self.connection and self.connection.is_open:
            return True
        self.connection = serial.Serial(self.port, **self.settings)
        return self.connection.is_open

    def close(self):
        if self.connection and self.connection.is_open:
            self.connection.close()

    def _exchange(self, frame, expected_length):
        if not self.connection or not self.connection.is_open:
            return None, "COM-poort is niet geopend"
        self.connection.reset_input_buffer()
        self.connection.write(frame + crc16(frame).to_bytes(2, "little"))
        self.connection.flush()
        response = self.connection.read(expected_length)
        if len(response) < 5:
            return None, "Geen volledig Modbus-antwoord (timeout)"
        if crc16(response[:-2]) != int.from_bytes(response[-2:], "little"):
            return None, "Ongeldige Modbus CRC"
        return response, None

    def read_holding_registers(self, address, count, *, device_id=1, slave=None, unit=None):
        unit_id = device_id if slave is None and unit is None else (slave if slave is not None else unit)
        request = bytes((unit_id, 0x03)) + address.to_bytes(2, "big") + count.to_bytes(2, "big")
        response, error = self._exchange(request, 5 + count * 2)
        if error:
            return RtuResponse(error=error)
        if response[0] != unit_id:
            return RtuResponse(error="Antwoord van onverwacht slave-adres")
        if response[1] & 0x80:
            return RtuResponse(error=f"Modbus exception 0x{response[2]:02X}")
        if response[1] != 0x03 or response[2] != count * 2:
            return RtuResponse(error="Ongeldig leesantwoord")
        regs = [int.from_bytes(response[i:i+2], "big") for i in range(3, 3 + count * 2, 2)]
        return RtuResponse(registers=regs)

    def write_register(self, address, value, *, device_id=1, slave=None, unit=None):
        unit_id = device_id if slave is None and unit is None else (slave if slave is not None else unit)
        request = bytes((unit_id, 0x06)) + address.to_bytes(2, "big") + value.to_bytes(2, "big")
        response, error = self._exchange(request, 8)
        if error:
            return RtuResponse(error=error)
        if response[:6] != request:
            return RtuResponse(error="Onverwacht antwoord op schrijfcommando")
        return RtuResponse(registers=[value])


def call_with_unit(method, *args, unit_id: int):
    # Kept as a small adapter so both the scanner and UI pass the target slave ID.
    return method(*args, device_id=unit_id)


class MotorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("AQMD3605BLS-B2 · motorbediening")
        self.root.geometry("720x720")
        self.root.minsize(680, 660)
        self.client = None
        self.unit_id = 1
        self.baudrate = DEFAULT_BAUD
        self.parity = "E"
        self.stopbits = 1
        self.raw_zero = 0
        self.poll_job = None
        self.last_unit = "graden"
        self.position_pulses_per_rev = tk.StringVar(value="24")
        self.units = tk.StringVar(value="graden")
        self.travel_limit = tk.StringVar(value="360")
        self.auto_update = tk.BooleanVar(value=True)
        self.poll_interval = tk.StringVar(value="500")
        self.port = tk.StringVar()
        self.address = tk.StringVar(value="1")
        self.status = tk.StringVar(value="Niet verbonden")
        self.position = tk.StringVar(value="—")
        self.speed = tk.StringVar(value="30")
        self.acceleration = tk.StringVar(value="60")
        self.target = tk.StringVar(value="10")
        self._build()
        self.scan_ports()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build(self):
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="AQMD3605BLS-B2", font=("Segoe UI", 17, "bold")).pack(anchor="w")
        ttk.Label(outer, text="Eenvoudige Modbus-bediening voor 57BSA79-36-01", foreground="#555").pack(anchor="w", pady=(0, 10))

        conn = ttk.LabelFrame(outer, text="Verbinding", padding=10)
        conn.pack(fill="x")
        self.port_box = ttk.Combobox(conn, textvariable=self.port, width=18, state="readonly")
        self.port_box.grid(row=0, column=0, padx=(0, 6), sticky="w")
        ttk.Button(conn, text="Poorten zoeken", command=self.scan_ports).grid(row=0, column=1, padx=4)
        ttk.Button(conn, text="Verbinden", command=self.connect).grid(row=0, column=2, padx=4)
        ttk.Label(conn, text="Driveradres").grid(row=0, column=3, padx=(14, 4))
        ttk.Entry(conn, textvariable=self.address, width=5).grid(row=0, column=4)
        ttk.Label(conn, textvariable=self.status).grid(row=1, column=0, columnspan=5, sticky="w", pady=(8, 0))

        pos = ttk.LabelFrame(outer, text="Positie", padding=10)
        pos.pack(fill="x", pady=(10, 0))
        ttk.Label(pos, text="Aspositie vanaf nulpunt", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(pos, textvariable=self.position, font=("Segoe UI", 20, "bold")).grid(row=0, column=1, sticky="w", padx=10)
        ttk.Button(pos, text="Nu uitlezen", command=self.read_position).grid(row=0, column=2, padx=4)
        ttk.Button(pos, text="Maak huidige positie nul", command=self.set_zero).grid(row=1, column=0, pady=(10, 0), sticky="w")
        ttk.Label(pos, text="Eenheid").grid(row=1, column=1, sticky="e", pady=(10, 0))
        ttk.Combobox(pos, textvariable=self.units, values=("graden", "radialen"), width=12, state="readonly").grid(row=1, column=2, sticky="w", pady=(10, 0))
        ttk.Checkbutton(pos, text="Positie automatisch verversen", variable=self.auto_update,
                        command=self._toggle_polling).grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Label(pos, text="Elke (ms)").grid(row=2, column=1, sticky="e", pady=(10, 0))
        ttk.Spinbox(pos, from_=100, to=5000, increment=100, textvariable=self.poll_interval,
                    width=10).grid(row=2, column=2, sticky="w", pady=(10, 0))
        ttk.Label(pos, text="Pulsen per omwenteling").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(pos, textvariable=self.position_pulses_per_rev, width=10).grid(row=3, column=1, sticky="w", padx=10, pady=(8, 0))
        ttk.Label(pos, text="Kalibreer dit getal vóór positiebewegingen; 24 is alleen een startwaarde.",
                  foreground="#555", wraplength=650).grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))

        motion = ttk.LabelFrame(outer, text="Beweging en limieten", padding=10)
        motion.pack(fill="x", pady=(10, 0))
        ttk.Label(motion, text="1. Doelpositie vanaf nul").grid(row=0, column=0, sticky="w")
        ttk.Entry(motion, textvariable=self.target, width=12).grid(row=0, column=1, padx=8)
        ttk.Button(motion, text="Beweeg naar doel", command=self.move_to).grid(row=0, column=2, padx=4)
        ttk.Label(motion, text="2. Softwarebereik vanaf nul: ±").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(motion, textvariable=self.travel_limit, width=12).grid(row=1, column=1, padx=8, sticky="w", pady=(10, 0))
        self.travel_max_label = ttk.Label(motion, text="", foreground="#555")
        self.travel_max_label.grid(row=1, column=2, sticky="w", pady=(10, 0))
        ttk.Label(motion, text="3. Maximum snelheid en versnelling").grid(row=2, column=0, columnspan=3, sticky="w", pady=(12, 4))
        ttk.Label(motion, text="Snelheid (°/s of rad/s)").grid(row=3, column=0, sticky="w")
        ttk.Entry(motion, textvariable=self.speed, width=12).grid(row=3, column=1, padx=8, sticky="w")
        self.speed_max_label = ttk.Label(motion, text="", foreground="#555")
        self.speed_max_label.grid(row=3, column=2, sticky="w")
        ttk.Label(motion, text="Versnelling (°/s² of rad/s²)").grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(motion, textvariable=self.acceleration, width=12).grid(row=4, column=1, padx=8, sticky="w", pady=(6, 0))
        self.accel_max_label = ttk.Label(motion, text="", foreground="#555")
        self.accel_max_label.grid(row=4, column=2, sticky="w", pady=(6, 0))
        ttk.Button(motion, text="Limieten toepassen", command=self.apply_limits).grid(row=5, column=2, padx=4, pady=(10, 0))
        ttk.Label(motion, text="Waarden moeten groter zijn dan 0. De snelheidslimiet volgt de nominale motorsnelheid.",
                  foreground="#555", wraplength=650).grid(row=6, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.units.trace_add("write", lambda *_: self._update_units())
        self._update_units()

        ttk.Label(outer, text="Let op: softwarebereik is geen fysieke eindstop. Houd de as vrij. STOP stuurt een normale stop naar de driver.",
                  foreground="#9a4b00", wraplength=680).pack(anchor="w", pady=(12, 0))
        ttk.Button(outer, text="STOP MOTOR", command=self.stop, style="Stop.TButton").pack(anchor="e", pady=(8, 0))
        style = ttk.Style()
        style.configure("Stop.TButton", foreground="#b00020", font=("Segoe UI", 11, "bold"))

    def _update_units(self):
        new_unit = self.units.get()
        if new_unit != self.last_unit:
            factor = math.pi / 180 if new_unit == "radialen" else 180 / math.pi
            for variable in (self.target, self.travel_limit, self.speed, self.acceleration):
                try:
                    variable.set(f"{float(variable.get()) * factor:.6g}")
                except ValueError:
                    pass
            self.last_unit = new_unit
            if self.client:
                self.read_position()
        max_accel = 6553.5 * (15.0 if new_unit == "graden" else math.pi / 12)
        accel_unit = "°/s²" if new_unit == "graden" else "rad/s²"
        self.accel_max_label.configure(text=f"Max. {max_accel:,.0f} {accel_unit} (driverregister)")
        speed_max = "18.000°/s" if new_unit == "graden" else f"{3000 * 2 * math.pi / 60:.1f} rad/s"
        self.speed_max_label.configure(text=f"Max. {speed_max} (3000 rpm nominaal)")
        travel_max = "3600°" if new_unit == "graden" else f"{20 * math.pi:.2f} rad"
        self.travel_max_label.configure(text=f"Max. ±{travel_max} (appgrens)")

    def _toggle_polling(self):
        if not self.auto_update.get():
            if self.poll_job is not None:
                self.root.after_cancel(self.poll_job)
                self.poll_job = None
        elif self.client:
            self._schedule_position_poll()

    def _schedule_position_poll(self):
        if not self.client or not self.auto_update.get() or self.poll_job is not None:
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
        self.read_position(show_errors=False)
        self._schedule_position_poll()

    def scan_ports(self):
        ports = [p.device for p in list_ports.comports()]
        self.port_box["values"] = ports
        if ports and self.port.get() not in ports:
            self.port.set(ports[0])
        self.status.set(f"{len(ports)} COM-poort(en) gevonden. Zoeken naar driver…")
        threading.Thread(target=self._probe_ports, args=(ports,), daemon=True).start()

    def _probe_ports(self, ports):
        # Read-only scan: verify both the documented version and device-name registers.
        for port in ports:
            self.root.after(0, lambda p=port: self.status.set(f"Scannen: {p} …"))
            # Keep each COM port open while checking addresses. Reopening it for every
            # address can add seconds per probe on Windows USB serial adapters.
            for baud, parity, stopbits in (
                (DEFAULT_BAUD, "E", 1), (9600, "N", 1),
                (19200, "E", 1), (115200, "E", 1),
            ):
                c = RtuSerialClient(port=port, baudrate=baud, bytesize=8,
                                    parity=parity, stopbits=stopbits, timeout=0.06, retries=0)
                try:
                    if not c.connect():
                        continue
                    for address in range(1, 129):
                        try:
                            name = call_with_unit(c.read_holding_registers, 0x0002, 8, unit_id=address)
                            if name.isError():
                                continue
                            raw = b"".join(v.to_bytes(2, "big") for v in name.registers)
                            device_name = raw.decode("ascii", errors="ignore").upper()
                            if "AQMD" not in device_name and "BLS" not in device_name:
                                continue
                            self.root.after(0, self._found_device, port, baud, address, parity, stopbits)
                            return
                        except Exception:
                            continue
                except Exception:
                    pass
                finally:
                    c.close()
        self.root.after(0, lambda: self.status.set("Geen driver gevonden. Controleer DIP 8, A/B, baudrate en slave-ID."))

    def _found_device(self, port, baud, address, parity, stopbits):
        self.port.set(port)
        self.address.set(str(address))
        self.baudrate = baud
        self.parity = parity
        self.stopbits = stopbits
        self.status.set(f"Driver gevonden op {port}, {baud} baud, {parity}{stopbits}, slave {address}")

    def connect(self):
        try:
            address = int(self.address.get())
            if not 1 <= address <= 128:
                raise ValueError("Slave-ID moet tussen 1 en 128 liggen.")
            if self.client:
                self.client.close()
            self.client = RtuSerialClient(port=self.port.get(), baudrate=self.baudrate,
                                          bytesize=8, parity=self.parity, stopbits=self.stopbits, timeout=0.5)
            if not self.client.connect():
                raise RuntimeError("COM-poort openen is mislukt.")
            self.unit_id = address
            r = self._read(0x0000, 1)
            self.status.set(f"Verbonden · {self.port.get()} · slave {address} · ID 0x{r[0]:04X}")
            self.read_position()
            self._schedule_position_poll()
        except Exception as exc:
            self.status.set("Verbinding mislukt")
            messagebox.showerror("Modbus", str(exc))

    def _read(self, register, count):
        if not self.client:
            raise RuntimeError("Verbind eerst met de driver.")
        response = call_with_unit(self.client.read_holding_registers, register, count, unit_id=self.unit_id)
        if response.isError():
            raise RuntimeError(f"Modbus leesfout bij register 0x{register:04X}: {response}")
        return response.registers

    def _write(self, register, value):
        if not self.client:
            raise RuntimeError("Verbind eerst met de driver.")
        response = call_with_unit(self.client.write_register, register, value & 0xFFFF, unit_id=self.unit_id)
        if response.isError():
            raise RuntimeError(f"Modbus schrijffout bij register 0x{register:04X}: {response}")

    def _position_counts(self):
        words = self._read(0x0024, 2)
        value = (words[0] << 16) | words[1]
        return value - (1 << 32) if value & 0x80000000 else value

    def _counts_per_rev(self):
        v = float(self.position_pulses_per_rev.get())
        if not math.isfinite(v) or v <= 0:
            raise ValueError("Pulsen per omwenteling moet groter dan nul zijn.")
        return v

    def _value_from_counts(self, counts):
        turns = counts / self._counts_per_rev()
        return turns * (2 * math.pi if self.units.get() == "radialen" else 360.0)

    def _counts_from_value(self, value):
        turns = value / (2 * math.pi if self.units.get() == "radialen" else 360.0)
        return round(turns * self._counts_per_rev())

    def read_position(self, show_errors=True):
        try:
            counts = self._position_counts() - self.raw_zero
            self.position.set(f"{self._value_from_counts(counts):.3f} {'rad' if self.units.get() == 'radialen' else '°'}")
        except Exception as exc:
            if show_errors:
                messagebox.showerror("Positie uitlezen", str(exc))
            else:
                self.status.set(f"Automatische positie-update mislukt: {exc}")

    def set_zero(self):
        try:
            self.raw_zero = self._position_counts()
            self.position.set(f"0.000 {'rad' if self.units.get() == 'radialen' else '°'}")
        except Exception as exc:
            messagebox.showerror("Nulpunt", str(exc))

    def _to_commutation_hz(self, angular_value):
        radians_factor = math.pi / 180 if self.units.get() == "graden" else 1.0
        radians_per_second = angular_value * radians_factor
        # Manual's speed relation: RPM = commutation_Hz * 20 / motor_poles.
        return radians_per_second * MOTOR_POLES / (20 * 2 * math.pi) * 60

    def apply_limits(self):
        try:
            speed = float(self.speed.get())
            accel = float(self.acceleration.get())
            if speed <= 0 or accel <= 0 or not math.isfinite(speed + accel):
                raise ValueError("Snelheid en versnelling moeten positief zijn.")
            rpm = speed * (60 / (2 * math.pi) if self.units.get() == "radialen" else 1 / 6)
            if rpm > 3000:
                raise ValueError("De ingestelde snelheid overschrijdt 3000 rpm, de nominale motorsnelheid.")
            # 0x0066 maximum commutation speed (0.1 Hz); 0x0062 acceleration (0.1 Hz/s).
            speed_raw = round(self._to_commutation_hz(speed) * 10)
            accel_raw = round(self._to_commutation_hz(accel) * 10)
            if not 1 <= speed_raw <= 32767:
                raise ValueError("Snelheid moet binnen het driverbereik liggen (0,1 Hz t/m 3276,7 Hz).")
            if not 1 <= accel_raw <= 65535:
                raise ValueError("Versnelling ligt buiten het registerbereik van de driver.")
            self._write(0x0066, speed_raw)
            self._write(0x0062, accel_raw)
            self.status.set("Maximale snelheid en versnelling toegepast (0x0066, 0x0062).")
        except Exception as exc:
            messagebox.showerror("Limieten", str(exc))

    def move_to(self):
        try:
            target_value = float(self.target.get())
            if not math.isfinite(target_value):
                raise ValueError("Geef een geldige doelpositie op.")
            travel_limit = float(self.travel_limit.get())
            max_travel = 20 * math.pi if self.units.get() == "radialen" else 3600.0
            if not math.isfinite(travel_limit) or not 0 < travel_limit <= max_travel:
                raise ValueError(f"Softwarebereik moet groter zijn dan 0 en maximaal {max_travel:g} {self.units.get()} zijn.")
            if abs(target_value) > travel_limit:
                raise ValueError(f"Doelpositie valt buiten het ingestelde softwarebereik ±{travel_limit:g}.")
            speed_value = float(self.speed.get())
            rpm = speed_value * (60 / (2 * math.pi) if self.units.get() == "radialen" else 1 / 6)
            if rpm <= 0 or rpm > 3000:
                raise ValueError("Snelheid moet positief zijn en maximaal 3000 rpm.")
            speed_raw = round(self._to_commutation_hz(speed_value) * 10)
            if speed_raw > 32767:
                raise ValueError("Snelheid ligt boven het bereik van het driverregister.")
            current = self._position_counts()
            target_counts = self.raw_zero + self._counts_from_value(target_value)
            target_counts &= 0xFFFFFFFF
            # Program the speed and absolute target only after all software bounds pass.
            self._write(0x0044, max(speed_raw, 1))
            self._write(0x0045, 0)
            self._write(0x0046, target_counts >> 16)
            self._write(0x0047, target_counts & 0xFFFF)
            self.status.set(f"Positiecommando verzonden · huidige pulsen {current}")
        except Exception as exc:
            messagebox.showerror("Beweging", str(exc))

    def stop(self):
        try:
            self._write(0x0040, 0)
            self.status.set("Normale stop verzonden")
        except Exception as exc:
            messagebox.showerror("Stop", str(exc))

    def close(self):
        if self.poll_job is not None:
            self.root.after_cancel(self.poll_job)
            self.poll_job = None
        if self.client:
            self.client.close()
        self.root.destroy()


if __name__ == "__main__":
    app_root = tk.Tk()
    MotorApp(app_root)
    app_root.mainloop()
