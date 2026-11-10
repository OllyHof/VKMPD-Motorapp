"""Modbus communication and motor-specific calculations for VKMPD."""
from __future__ import annotations

import math
import struct

import serial
from serial.tools import list_ports


DEFAULT_BAUD = 9600
MOTOR_POLES = 8
MAX_RPM = 3000


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
    """Small synchronous Modbus RTU client for the function codes used here."""
    def __init__(self, *, port, baudrate, bytesize, parity, stopbits, timeout):
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

    def read_holding_registers(self, address, count, *, device_id=1):
        request = bytes((device_id, 0x03)) + address.to_bytes(2, "big") + count.to_bytes(2, "big")
        response, error = self._exchange(request, 5 + count * 2)
        if error:
            return RtuResponse(error=error)
        if response[0] != device_id:
            return RtuResponse(error="Antwoord van onverwacht slave-adres")
        if response[1] & 0x80:
            return RtuResponse(error=f"Modbus exception 0x{response[2]:02X}")
        if response[1] != 0x03 or response[2] != count * 2:
            return RtuResponse(error="Ongeldig leesantwoord")
        registers = [int.from_bytes(response[i:i + 2], "big") for i in range(3, 3 + count * 2, 2)]
        return RtuResponse(registers=registers)

    def write_register(self, address, value, *, device_id=1):
        request = bytes((device_id, 0x06)) + address.to_bytes(2, "big") + value.to_bytes(2, "big")
        response, error = self._exchange(request, 8)
        if error:
            return RtuResponse(error=error)
        if response[:6] != request:
            return RtuResponse(error="Onverwacht antwoord op schrijfcommando")
        return RtuResponse(registers=[value])


class MotorController:
    """Hardware access, position conversion, and guarded motion commands."""
    UNIT_RADIANS = {"graden": math.pi / 180, "radialen": 1.0, "rotaties": 2 * math.pi}
    PID_REGISTERS = {
        "Snelheidsregeling": (0x00C0, ((0.001, 1.0), (0.001, 1.0), (0.001, 1.0))),
        "Positieregeling": (0x00C6, ((0.1, 100.0), (0.001, 1.0), (0.001, 1.0))),
    }

    def __init__(self, pulses_per_revolution=24):
        self.pulses_per_revolution = pulses_per_revolution
        self.client = None
        self.unit_id = 1
        self.port = ""
        self.baudrate = DEFAULT_BAUD
        self.parity = "E"
        self.stopbits = 1
        self.raw_zero = 0

    @classmethod
    def radians_per_unit(cls, unit):
        return cls.UNIT_RADIANS[unit]

    @classmethod
    def value_from_counts(cls, counts, pulses_per_revolution, unit):
        if not math.isfinite(pulses_per_revolution) or pulses_per_revolution <= 0:
            raise ValueError("Pulsen per omwenteling moet groter dan nul zijn.")
        turns = counts / pulses_per_revolution
        return turns * (2 * math.pi / cls.radians_per_unit(unit))

    @classmethod
    def counts_from_value(cls, value, pulses_per_revolution, unit):
        if not math.isfinite(pulses_per_revolution) or pulses_per_revolution <= 0:
            raise ValueError("Pulsen per omwenteling moet groter dan nul zijn.")
        turns = value * cls.radians_per_unit(unit) / (2 * math.pi)
        return round(turns * pulses_per_revolution)

    @classmethod
    def to_commutation_hz(cls, angular_value, unit):
        radians_per_second = angular_value * cls.radians_per_unit(unit)
        return radians_per_second * MOTOR_POLES / (20 * 2 * math.pi) * 60

    @staticmethod
    def available_ports():
        return [port.device for port in list_ports.comports()]

    def scan_and_connect(self, ports, report_progress=None):
        """Scan COM port, serial settings, then slave ID; keep the match connected."""
        self.close()
        for port in ports:
            if report_progress:
                report_progress(f"Stap 1/3 · COM-poort {port}")
            for baud, parity, stopbits in ((9600, "E", 1), (9600, "N", 1),
                                            (19200, "E", 1), (115200, "E", 1)):
                if report_progress:
                    report_progress(f"Stap 2/3 · {port} · {baud} baud · {parity}81")
                client = RtuSerialClient(port=port, baudrate=baud, bytesize=8,
                                         parity=parity, stopbits=stopbits, timeout=0.06)
                try:
                    if not client.connect():
                        continue
                    for address in range(1, 129):
                        if report_progress and address in (1, 33, 65, 97):
                            report_progress(f"Stap 3/3 · {port} · {baud} baud · slave-ID {address}–{min(address + 31, 128)}")
                        try:
                            result = client.read_holding_registers(0x0002, 8, device_id=address)
                            if result.isError():
                                continue
                            raw = b"".join(value.to_bytes(2, "big") for value in result.registers)
                            name = raw.decode("ascii", errors="ignore").upper()
                            if "AQMD" in name or "BLS" in name:
                                self.client = client
                                self.unit_id = address
                                self.port = port
                                self.baudrate = baud
                                self.parity = parity
                                self.stopbits = stopbits
                                self.client.settings["timeout"] = 0.5
                                self.client.settings["write_timeout"] = 0.5
                                self.client.connection.timeout = 0.5
                                self.client.connection.write_timeout = 0.5
                                identity = self._read(0x0000, 1)[0]
                                return port, baud, address, parity, stopbits, identity
                        except Exception:
                            if self.client is client:
                                self.client = None
                                client.close()
                            continue
                except Exception:
                    pass
                finally:
                    if self.client is not client:
                        client.close()
        return None

    def connect(self, port, address):
        if not 1 <= address <= 128:
            raise ValueError("Slave-ID moet tussen 1 en 128 liggen.")
        self.close()
        client = RtuSerialClient(port=port, baudrate=self.baudrate, bytesize=8,
                                 parity=self.parity, stopbits=self.stopbits, timeout=0.5)
        if not client.connect():
            raise RuntimeError("COM-poort openen is mislukt.")
        self.client, self.unit_id, self.port = client, address, port
        try:
            identity = self._read(0x0000, 1)[0]
        except Exception:
            self.close()
            raise
        return identity

    def _read(self, register, count):
        if not self.client:
            raise RuntimeError("Verbind eerst met de driver.")
        response = self.client.read_holding_registers(register, count, device_id=self.unit_id)
        if response.isError():
            raise RuntimeError(f"Modbus leesfout bij register 0x{register:04X}: {response}")
        return response.registers

    def _write(self, register, value):
        if not self.client:
            raise RuntimeError("Verbind eerst met de driver.")
        response = self.client.write_register(register, value & 0xFFFF, device_id=self.unit_id)
        if response.isError():
            raise RuntimeError(f"Modbus schrijffout bij register 0x{register:04X}: {response}")

    def write_register(self, register, value):
        """Write one user-selected holding register after validating its 16-bit range."""
        if isinstance(register, bool) or not isinstance(register, int) or not 0 <= register <= 0xFFFF:
            raise ValueError("Registeradres moet tussen 0 en 65535 liggen.")
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFFFF:
            raise ValueError("Registerwaarde moet tussen 0 en 65535 liggen.")
        self._write(register, value)

    def read_register(self, register):
        """Read one user-selected holding register after validating its 16-bit address."""
        if isinstance(register, bool) or not isinstance(register, int) or not 0 <= register <= 0xFFFF:
            raise ValueError("Registeradres moet tussen 0 en 65535 liggen.")
        return self._read(register, 1)[0]

    def read_pid(self, mode):
        """Read P, I and D float32 gains (high register word first)."""
        try:
            start, _ranges = self.PID_REGISTERS[mode]
        except KeyError as exc:
            raise ValueError("Kies snelheidsregeling of positieregeling.") from exc
        words = self._read(start, 6)
        values = []
        for offset in (0, 2, 4):
            raw = words[offset].to_bytes(2, "big") + words[offset + 1].to_bytes(2, "big")
            value = struct.unpack(">f", raw)[0]
            if not math.isfinite(value):
                raise RuntimeError("De driver gaf een ongeldige PID-waarde terug.")
            values.append(value)
        return tuple(values)

    def write_pid(self, mode, p, i, d):
        """Write P, I and D float32 gains after checking the manual's ranges."""
        try:
            start, ranges = self.PID_REGISTERS[mode]
        except KeyError as exc:
            raise ValueError("Kies snelheidsregeling of positieregeling.") from exc
        values = tuple(float(value) for value in (p, i, d))
        for name, value, (minimum, maximum) in zip(("P", "I", "D"), values, ranges):
            if not math.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError(f"{name} moet tussen {minimum:g} en {maximum:g} liggen.")
        for offset, value in enumerate(values):
            high, low = struct.unpack(">HH", struct.pack(">f", value))
            self._write(start + offset * 2, high)
            self._write(start + offset * 2 + 1, low)

    def position_counts(self):
        words = self._read(0x0024, 2)
        value = (words[0] << 16) | words[1]
        return value - (1 << 32) if value & 0x80000000 else value

    def position(self, unit):
        counts = self.position_counts() - self.raw_zero
        return self.value_from_counts(counts, float(self.pulses_per_revolution), unit)

    def telemetry(self, unit):
        """Read position, speed, current, PWM, bus voltage, and fault in one request."""
        registers = self._read(0x0020, 25)
        commutation_raw = registers[2]
        if commutation_raw & 0x8000:
            commutation_raw -= 1 << 16
        speed_flag = registers[21]
        speed_rpm = registers[20] * (10 if speed_flag == 1 else 1)
        if registers[20] == 0xFFFF:
            # 0xFFFF was observed as a fixed, nonphysical reading; fall back to Hall commutation speed.
            commutation_hz = commutation_raw if speed_flag == 1 else commutation_raw * 0.1
            speed_rpm = commutation_hz / MOTOR_POLES * 20
        rpm = speed_rpm
        if commutation_raw < 0:
            rpm = -abs(rpm)
        speed = rpm * 2 * math.pi / 60 / self.radians_per_unit(unit)
        pwm_percent = registers[0] * 0.1
        current_amps = registers[1] * 0.01
        fault_code = registers[19]
        bus_voltage = registers[24] * 0.1
        position_raw = (registers[4] << 16) | registers[5]
        if position_raw & 0x80000000:
            position_raw -= 1 << 32
        position = self.value_from_counts(
            position_raw - self.raw_zero, float(self.pulses_per_revolution), unit)
        commutation_hz = commutation_raw * (1 if speed_flag == 1 else 0.1)
        return position, speed, current_amps, fault_code, pwm_percent, bus_voltage, commutation_hz

    def speed_configuration(self):
        """Return the driver speed calculation settings: motor poles and gear ratio."""
        poles, ratio_tenths = self._read(0x0073, 2)
        return poles, ratio_tenths / 10

    def set_zero(self):
        self.raw_zero = self.position_counts()

    def apply_limits(self, speed, acceleration, unit):
        speed, acceleration = float(speed), float(acceleration)
        if speed <= 0 or acceleration <= 0 or not math.isfinite(speed + acceleration):
            raise ValueError("Snelheid en versnelling moeten positief zijn.")
        rpm = speed * self.radians_per_unit(unit) * 60 / (2 * math.pi)
        if rpm > MAX_RPM:
            raise ValueError("De ingestelde snelheid overschrijdt 3000 rpm, de nominale motorsnelheid.")
        speed_raw = round(self.to_commutation_hz(speed, unit) * 10)
        accel_raw = round(self.to_commutation_hz(acceleration, unit) * 10)
        if not 1 <= speed_raw <= 32767:
            raise ValueError("Snelheid moet binnen het driverbereik liggen (0,1 Hz t/m 3276,7 Hz).")
        if not 1 <= accel_raw <= 65535:
            raise ValueError("Versnelling ligt buiten het registerbereik van de driver.")
        self._write(0x0066, speed_raw)
        self._write(0x0062, accel_raw)
        # 0x0052 is the live acceleration override; 0x0062 is its configured ceiling.
        self._write(0x0052, accel_raw)
        live_acceleration = self._read(0x0052, 1)[0]
        if live_acceleration != accel_raw:
            raise RuntimeError(
                "De driver heeft de tijdelijke versnelling niet bevestigd "
                f"(gevraagd {accel_raw}, teruggelezen {live_acceleration}).")

    def move_to(self, target, positive_limit, negative_limit, speed, acceleration, unit):
        target = float(target)
        speed, acceleration = float(speed), float(acceleration)
        if not math.isfinite(target):
            raise ValueError("Geef een geldige doelpositie op.")
        if positive_limit is not None or negative_limit is not None:
            positive_limit, negative_limit = float(positive_limit), float(negative_limit)
            if (not math.isfinite(positive_limit) or not math.isfinite(negative_limit)
                    or positive_limit <= 0 or negative_limit <= 0):
                raise ValueError("Beide positielimieten moeten groter zijn dan nul.")
            if target > positive_limit or target < -negative_limit:
                raise ValueError(f"Doelpositie valt buiten de limiet: +{positive_limit:g} en −{negative_limit:g} {unit}.")
        rpm = speed * self.radians_per_unit(unit) * 60 / (2 * math.pi)
        if not math.isfinite(rpm) or rpm <= 0 or rpm > MAX_RPM:
            raise ValueError("Snelheid moet positief zijn en maximaal 3000 rpm.")
        speed_raw = round(self.to_commutation_hz(speed, unit) * 10)
        if not 1 <= speed_raw <= 32767:
            raise ValueError("Snelheid ligt buiten het bereik van het driverregister.")
        self.apply_limits(speed, acceleration, unit)
        current = self.position_counts()
        target_counts = self.raw_zero + self.counts_from_value(
            target, float(self.pulses_per_revolution), unit)
        if not -(1 << 31) <= target_counts < (1 << 31):
            raise ValueError("Doelpositie past niet in het 32-bit positie-register van de driver.")
        target_counts &= 0xFFFFFFFF
        self._write(0x0044, speed_raw)
        self._write(0x0045, 0)
        self._write(0x0046, target_counts >> 16)
        self._write(0x0047, target_counts & 0xFFFF)
        return current

    def stop(self):
        self._write(0x0040, 0)

    def close(self):
        if self.client:
            self.client.close()
            self.client = None
