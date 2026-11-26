# -*- coding: utf-8 -*-
"""
An Sound ACP Pro PC — Companion & Direct USB Controller for ACPWorkbench_V2.44.2.exe
Target Hardware: Quoc Doan Audio 70W x 2 (MVSilicon BP1048B2, Firmware 0.3.4, Effect 2.45.5)
3-Way Spec:
  - Sub: 5" JBL Boombox 4 (5L box)
  - Mid: Pioneer S-EV61V 6 Ohm
  - Treble: Ford JX7T-18808-BA 4 Ohm 5W (3uF cap) -> Safe max gain <= 4600

Zero external dependencies: runs on standard Windows Python 3.11+ (tkinter + ctypes Win32 HID/COM).
"""

import ctypes
from ctypes import wintypes
import math
import os
import re
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Tuple

try:
    import winreg
except ImportError:
    winreg = None


# ==============================================================================
# 1. MVSILICON ACPWORKBENCH V2.44.2 PROTOCOL & PACKET ENGINE
# ==============================================================================

SYNC_HEAD_0 = 0xA5
SYNC_HEAD_1 = 0x5A
SYNC_TAIL = 0x16
ALL_PARAM_MASK = 0xFF

EFFECT_INPUT_I2S_GAIN = 0x81
EFFECT_INPUT_BT_GAIN = 0x82
EFFECT_INPUT_USB_GAIN = 0x83
EFFECT_INPUT_OPT_GAIN = 0x84
EFFECT_NOISE_GATE = 0x85
EFFECT_MVBASS_CLASSIC = 0x87
EFFECT_MVBASS_ADV = 0x88
EFFECT_EXCITER = 0x89
EFFECT_MUSIC_DELAY = 0x8B
EFFECT_MUSIC_BASS_MID_TREB = 0x91
EFFECT_REMIND_GAIN = 0x92
EFFECT_MUSIC_DRC = 0x93
EFFECT_BASS_EQ = 0x95
EFFECT_TREBLE_EQ = 0x96
EFFECT_MID_EQ = 0x97
EFFECT_TREBLE_GAIN = 0x98
EFFECT_MID_GAIN = 0x99
EFFECT_BASS_PHASE = 0x9A
EFFECT_BASS_DRC = 0x9B
EFFECT_MID_DRC = 0x9C
EFFECT_BASS_DELAY = 0x9D

FILTER_PEAKING = 0
FILTER_LOW_SHELF = 1
FILTER_HIGH_SHELF = 2
FILTER_LOW_PASS = 3
FILTER_HIGH_PASS = 4

TREBLE_SAFE_MAX_GAIN = 4600


def db_to_eq_fixed(db: float) -> int:
    """Q8 fixed-point: 1.0 dB = 256."""
    return int(round(db * 256.0))


def eq_fixed_to_db(fixed: int) -> float:
    return fixed / 256.0


def q_to_fixed(q: float) -> int:
    """Q10 fixed-point: Q=1.0 -> 1024, Butterworth 0.707 -> 724."""
    return int(round(q * 1024.0))


def dbfs_to_drc_threshold(dbfs: float) -> int:
    """0.01 dBFS units: -2.0 dBFS -> -200."""
    return int(round(dbfs * 100.0))


def _pack_u16_le(val: int) -> bytes:
    v = int(val) & 0xFFFF
    return bytes((v & 0xFF, (v >> 8) & 0xFF))


def _pack_i16_le(val: int) -> bytes:
    return _pack_u16_le(int(val))


def read_u16_le(buf: bytes, offset: int) -> int:
    return (buf[offset] & 0xFF) | ((buf[offset + 1] & 0xFF) << 8)


def read_i16_le(buf: bytes, offset: int) -> int:
    v = read_u16_le(buf, offset)
    return v - 0x10000 if (v & 0x8000) else v


class EqBand:
    def __init__(self, enable: bool, ftype: int, f0_hz: int, q: float, gain_db: float):
        self.enable = bool(enable)
        self.ftype = int(ftype)
        self.f0_hz = int(f0_hz)
        self.q = float(q)
        self.gain_db = float(gain_db)


class MvsiliconPacket:
    """Represents one ACPWorkbench binary frame: [0xA5, 0x5A, Effect_ID, Length, Param_Mask, Payload, 0x16]."""

    def __init__(self, effect_id: int, param_mask: int, payload: bytes):
        self.effect_id = effect_id & 0xFF
        self.param_mask = param_mask & 0xFF
        self.payload = bytes(payload)

    def to_bytes(self) -> bytes:
        length = 1 + len(self.payload)
        return bytes([SYNC_HEAD_0, SYNC_HEAD_1, self.effect_id, length & 0xFF, self.param_mask]) + self.payload + bytes([SYNC_TAIL])

    def to_hex(self) -> str:
        return " ".join(f"{b:02X}" for b in self.to_bytes())

    @classmethod
    def parse(cls, frame: bytes) -> "MvsiliconPacket":
        if len(frame) < 6 or frame[0] != SYNC_HEAD_0 or frame[1] != SYNC_HEAD_1 or frame[-1] != SYNC_TAIL:
            raise ValueError("Invalid MVSilicon frame sync bytes")
        eff_id = frame[2] & 0xFF
        length = frame[3] & 0xFF
        if len(frame) != length + 5:
            raise ValueError(f"Frame length mismatch: expected {length + 5}, got {len(frame)}")
        mask = frame[4] & 0xFF
        payload = frame[5:-1]
        return cls(eff_id, mask, payload)

    @classmethod
    def parse_stream(cls, stream: bytes) -> List["MvsiliconPacket"]:
        out: List[MvsiliconPacket] = []
        if not stream:
            return out
        i = 0
        n = len(stream)
        while i <= n - 6:
            if stream[i] == SYNC_HEAD_0 and stream[i + 1] == SYNC_HEAD_1:
                length = stream[i + 3] & 0xFF
                total_len = length + 5
                if length >= 1 and i + total_len <= n and stream[i + total_len - 1] == SYNC_TAIL:
                    out.append(cls.parse(stream[i:i + total_len]))
                    i += total_len
                    continue
            i += 1
        return out


def build_eq10_packet(effect_id: int, enable: bool, pregain_db: float, bands: List[EqBand]) -> MvsiliconPacket:
    buf = bytearray()
    buf += _pack_u16_le(1 if enable else 0)
    buf += _pack_i16_le(db_to_eq_fixed(pregain_db))
    buf += _pack_u16_le(0)  # calculation_type = 0
    for i in range(10):
        if bands and i < len(bands):
            b = bands[i]
            buf += _pack_u16_le(1 if b.enable else 0)
            buf += _pack_u16_le(b.ftype)
            buf += _pack_u16_le(b.f0_hz)
            buf += _pack_u16_le(q_to_fixed(b.q))
            buf += _pack_i16_le(db_to_eq_fixed(b.gain_db))
        else:
            buf += _pack_u16_le(0)
            buf += _pack_u16_le(0)
            buf += _pack_u16_le(1000)
            buf += _pack_u16_le(724)
            buf += _pack_i16_le(0)
    return MvsiliconPacket(effect_id, ALL_PARAM_MASK, bytes(buf))


def build_music_bass_mid_treble(bass_db: float, mid_db: float, treble_db: float) -> MvsiliconPacket:
    bands = [
        EqBand(True, FILTER_PEAKING, 65, 0.90, bass_db),
        EqBand(True, FILTER_PEAKING, 800, 0.85, mid_db),
        EqBand(True, FILTER_HIGH_SHELF, 8500, 0.707, treble_db),
    ]
    return build_eq10_packet(EFFECT_MUSIC_BASS_MID_TREB, True, 0.0, bands)


def build_speaker_gain_packet(effect_id: int, enable: bool, mute: bool, gain_raw: int) -> MvsiliconPacket:
    clamped = max(0, min(16384, int(gain_raw)))
    buf = _pack_u16_le(1 if enable else 0) + _pack_u16_le(1 if mute else 0) + _pack_u16_le(clamped)
    return MvsiliconPacket(effect_id, ALL_PARAM_MASK, buf)


def build_bass_phase_packet(enable: bool, phase_180: bool) -> MvsiliconPacket:
    buf = _pack_u16_le(1 if enable else 0) + _pack_u16_le(1 if phase_180 else 0)
    return MvsiliconPacket(EFFECT_BASS_PHASE, ALL_PARAM_MASK, buf)


def build_drc_packet(
    effect_id: int,
    enable: bool,
    mode: int,
    ftype: int,
    fc1_hz: int,
    fc2_hz: int,
    threshold_dbfs: float,
    ratio: int,
    attack_ms: int,
    release_ms: int,
) -> MvsiliconPacket:
    buf = bytearray()
    buf += _pack_u16_le(1 if enable else 0)
    buf += _pack_u16_le(mode)
    buf += _pack_u16_le(ftype)
    buf += _pack_u16_le(724)
    buf += _pack_u16_le(724)
    buf += _pack_u16_le(fc1_hz)
    buf += _pack_u16_le(fc2_hz)
    th = dbfs_to_drc_threshold(threshold_dbfs)
    for _ in range(4):
        buf += _pack_i16_le(th)
    for _ in range(4):
        buf += _pack_u16_le(ratio)
    for _ in range(4):
        buf += _pack_u16_le(attack_ms)
    for _ in range(4):
        buf += _pack_u16_le(release_ms)
    for _ in range(4):
        buf += _pack_u16_le(4096)
    return MvsiliconPacket(effect_id, ALL_PARAM_MASK, bytes(buf))


def build_noise_gate_packet(enable: bool, threshold_db: float, ratio: int, attack_ms: int, release_ms: int) -> MvsiliconPacket:
    buf = (
        _pack_u16_le(1 if enable else 0)
        + _pack_i16_le(dbfs_to_drc_threshold(threshold_db))
        + _pack_u16_le(max(1, int(ratio)))
        + _pack_u16_le(max(1, int(attack_ms)))
        + _pack_u16_le(max(1, int(release_ms)))
    )
    return MvsiliconPacket(EFFECT_NOISE_GATE, ALL_PARAM_MASK, buf)


def build_mvbass_classic_packet(enable: bool, cutoff_hz: int, intensity: int) -> MvsiliconPacket:
    buf = _pack_u16_le(1 if enable else 0) + _pack_u16_le(cutoff_hz) + _pack_u16_le(intensity)
    return MvsiliconPacket(EFFECT_MVBASS_CLASSIC, ALL_PARAM_MASK, buf)


def build_mvbass_adv_packet(enable: bool, cutoff_hz: int, intensity: int, enhanced: int) -> MvsiliconPacket:
    buf = (
        _pack_u16_le(1 if enable else 0)
        + _pack_u16_le(cutoff_hz)
        + _pack_u16_le(intensity)
        + _pack_u16_le(enhanced)
    )
    return MvsiliconPacket(EFFECT_MVBASS_ADV, ALL_PARAM_MASK, buf)


def build_exciter_packet(enable: bool, cutoff_hz: int, dry: int, wet: int) -> MvsiliconPacket:
    buf = (
        _pack_u16_le(1 if enable else 0)
        + _pack_u16_le(cutoff_hz)
        + _pack_u16_le(dry)
        + _pack_u16_le(wet)
    )
    return MvsiliconPacket(EFFECT_EXCITER, ALL_PARAM_MASK, buf)


def build_pcm_delay_packet(effect_id: int, enable: bool, delay_ms: int, max_delay_ms: int = 50, hq: bool = False) -> MvsiliconPacket:
    buf = (
        _pack_u16_le(1 if enable else 0)
        + _pack_u16_le(max(0, min(max_delay_ms, int(delay_ms))))
        + _pack_u16_le(max_delay_ms)
        + _pack_u16_le(1 if hq else 0)
    )
    return MvsiliconPacket(effect_id, ALL_PARAM_MASK, buf)


# ==============================================================================
# 2. ACPWORKBENCH V2.44.2 .INI & .C CONFIG PARSER / EXPORTER
# ==============================================================================

class AcpSection:
    def __init__(self, header: str, effect_id: int):
        self.header = header
        self.effect_id = effect_id
        self.entries: List[Tuple[str, str]] = []

    def put(self, key: str, value: str) -> None:
        self.entries.append((key, value))

    def set_key(self, key: str, value: str) -> None:
        for idx, (k, _) in enumerate(self.entries):
            if k == key:
                self.entries[idx] = (key, value)
                return
        self.entries.append((key, value))

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        for k, v in self.entries:
            if k == key:
                return v
        return default

    def get_int(self, key: str, default: int = 0) -> int:
        v = self.get(key)
        if v is None:
            return default
        try:
            return int(v.strip())
        except ValueError:
            return default


class AcpProfile:
    def __init__(self):
        self.acp_version = "2.44.2"
        self.comm_port = "USB[0] :Best Sound T1V2"
        self.sections: Dict[str, AcpSection] = {}

    def add_section(self, sec: AcpSection) -> None:
        self.sections[sec.header] = sec

    def find_by_effect_id(self, effect_id: int) -> Optional[AcpSection]:
        target = effect_id & 0xFF
        for sec in self.sections.values():
            if sec.effect_id == target:
                return sec
        return None


def _extract_effect_id(header: str) -> int:
    part = header.split("-", 1)[0].strip()
    if part.lower().startswith("0x"):
        try:
            return int(part[2:], 16) & 0xFF
        except ValueError:
            return -1
    return -1


def parse_ini(ini_text: str) -> AcpProfile:
    profile = AcpProfile()
    if not ini_text:
        return profile
    current: Optional[AcpSection] = None
    for raw in ini_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if line.startswith("#ACPWorkbench Version:"):
                profile.acp_version = line.split(":", 1)[1].strip()
            elif line.startswith("#Communication Port:"):
                profile.comm_port = line.split(":", 1)[1].strip()
            continue
        if line.startswith("[") and line.endswith("]"):
            header = line[1:-1].strip()
            current = AcpSection(header, _extract_effect_id(header))
            profile.add_section(current)
            continue
        if "=" in line and current is not None:
            k, v = line.split("=", 1)
            current.put(k.strip(), v.strip())
    return profile


def serialize_ini(profile: AcpProfile) -> str:
    lines = [
        "#Audio Settings Configuration: 0",
        f"#ACPWorkbench Version: {profile.acp_version}",
        f"#Communication Port: {profile.comm_port}",
        "#Generated: An Sound ACP Pro PC (MVSilicon BP1048B2)",
        "",
    ]
    for sec in profile.sections.values():
        lines.append(f"[{sec.header}]")
        for k, v in sec.entries:
            lines.append(f"{k} = {v}")
        lines.append("")
    return "\n".join(lines)


def export_c_source(array_name: str, packets: List[MvsiliconPacket]) -> str:
    raw_frames = [p.to_bytes() for p in packets]
    total_bytes = sum(len(f) for f in raw_frames)
    lines = [
        "//ACPWorkbench Version: 2.44.2",
        "//Firmware: 0.3.4 | Target: Quoc Doan Audio 70Wx2 (3-Way)",
        f"const unsigned char {array_name}[{total_bytes}] = {{",
        "",
    ]
    for idx, frame in enumerate(raw_frames):
        pkt = packets[idx]
        lines.append(f"0x{frame[0]:02X}, 0x{frame[1]:02X}, /*sync head*/")
        lines.append(f"0x{pkt.effect_id:02X}, /*Effect_ID*/")
        lines.append(f"0x{frame[3]:02X}, /*length*/")
        lines.append(f"0x{pkt.param_mask:02X}, /*all parameter*/")
        row = []
        payload_bytes = frame[5:-1]
        for j in range(0, len(payload_bytes), 2):
            if j + 1 < len(payload_bytes):
                row.append(f"0x{payload_bytes[j]:02X}, 0x{payload_bytes[j + 1]:02X},")
            else:
                row.append(f"0x{payload_bytes[j]:02X},")
            if len(row) == 6:
                lines.append(" ".join(row))
                row = []
        if row:
            lines.append(" ".join(row))
        tail = "0x16, /*sync tail*/\n" if idx < len(raw_frames) - 1 else "0x16 /*sync tail*/"
        lines.append(tail)
    lines.append("};")
    return "\n".join(lines) + "\n"


# ==============================================================================
# 3. 3-WAY BEST TUNING STATE & PRESETS (MATCHING ACPWORKBENCH V2.44.2)
# ==============================================================================

class Dsp3WayState:
    def __init__(
        self,
        name: str,
        description: str,
        music_bass_db: float = 0.0,
        music_mid_db: float = 0.0,
        music_treble_db: float = 0.0,
        bass_hpf_hz: int = 60,
        bass_lpf_hz: int = 150,
        bass_pregain_db: float = -4.0,
        bass_phase_180: bool = False,
        mid_hpf_hz: int = 150,
        mid_gain_raw: int = 4600,
        treble_hpf_hz: int = 9500,
        treble_gain_raw: int = 4600,
        drc_enabled: bool = True,
        music_drc_dbfs: float = -2.0,
        spk_drc_dbfs: float = -3.0,
        ini_source: Optional[str] = None,
    ):
        self.name = name
        self.description = description
        self.music_bass_db = music_bass_db
        self.music_mid_db = music_mid_db
        self.music_treble_db = music_treble_db
        self.bass_hpf_hz = bass_hpf_hz
        self.bass_lpf_hz = bass_lpf_hz
        self.bass_pregain_db = bass_pregain_db
        self.bass_phase_180 = bass_phase_180
        self.mid_hpf_hz = mid_hpf_hz
        self.mid_gain_raw = mid_gain_raw
        self.treble_hpf_hz = treble_hpf_hz
        self.treble_gain_raw = treble_gain_raw
        self.drc_enabled = drc_enabled
        self.music_drc_dbfs = music_drc_dbfs
        self.spk_drc_dbfs = spk_drc_dbfs
        self.drc_ratio = 50
        self.drc_attack_ms = 2
        self.drc_release_ms = 80
        self.ini_source = ini_source

        # Extended ACPWorkbench parameters (0x81-0x8B, 0x92, 0x9D)
        self.in_i2s_gain = 4096
        self.in_bt_gain = 4096
        self.in_usb_gain = 4096
        self.in_opt_gain = 4096
        self.remind_gain = 4096

        self.ng_enable = False
        self.ng_thresh_db = -65.0
        self.ng_ratio = 1
        self.ng_attack_ms = 5
        self.ng_release_ms = 160

        self.mvb_classic_en = False
        self.mvb_classic_hz = 58
        self.mvb_classic_int = 24

        self.mvb_adv_en = False
        self.mvb_adv_hz = 56
        self.mvb_adv_int = 15
        self.mvb_adv_enh = 0

        self.exc_en = False
        self.exc_hz = 4500
        self.exc_dry = 100
        self.exc_wet = 25

        self.music_delay_en = False
        self.music_delay_ms = 0
        self.bass_delay_en = False
        self.bass_delay_ms = 0

        self.peq_banks: Dict[int, List[EqBand]] = self._default_peq_banks()

    def _default_peq_banks(self) -> Dict[int, List[EqBand]]:
        def _pad(bands: List[EqBand]) -> List[EqBand]:
            out = list(bands)
            while len(out) < 10:
                out.append(EqBand(False, FILTER_PEAKING, 1000, 0.707, 0.0))
            return out[:10]

        return {
            EFFECT_MUSIC_BASS_MID_TREB: _pad([
                EqBand(True, FILTER_PEAKING, 65, 0.90, self.music_bass_db),
                EqBand(True, FILTER_PEAKING, 800, 0.85, self.music_mid_db),
                EqBand(True, FILTER_HIGH_SHELF, 8500, 0.707, self.music_treble_db),
            ]),
            EFFECT_BASS_EQ: _pad([
                EqBand(True, FILTER_HIGH_PASS, self.bass_hpf_hz, 0.707, 0.0),
                EqBand(True, FILTER_LOW_PASS, self.bass_lpf_hz, 0.707, 0.0),
                EqBand(True, FILTER_HIGH_PASS, self.bass_hpf_hz, 0.707, 0.0),
                EqBand(True, FILTER_LOW_PASS, self.bass_lpf_hz, 0.707, 0.0),
                EqBand(True, FILTER_PEAKING, 110, 2.2, -2.5),
                EqBand(True, FILTER_PEAKING, 68, 1.4, 2.0),
            ]),
            EFFECT_MID_EQ: _pad([
                EqBand(True, FILTER_HIGH_PASS, self.mid_hpf_hz, 0.707, 0.0),
                EqBand(True, FILTER_HIGH_PASS, self.mid_hpf_hz, 0.707, 0.0),
                EqBand(True, FILTER_PEAKING, 2200, 1.2, 1.5),
            ]),
            EFFECT_TREBLE_EQ: _pad([
                EqBand(True, FILTER_HIGH_PASS, self.treble_hpf_hz, 0.707, 0.0),
                EqBand(True, FILTER_HIGH_PASS, self.treble_hpf_hz, 0.707, 0.0),
                EqBand(True, FILTER_PEAKING, 12500, 1.0, 1.5),
            ]),
        }

    def build_packets(self) -> List[MvsiliconPacket]:
        # Sync quick controls into PEQ banks
        m_bands = self.peq_banks[EFFECT_MUSIC_BASS_MID_TREB]
        m_bands[0].gain_db = self.music_bass_db
        m_bands[1].gain_db = self.music_mid_db
        m_bands[2].gain_db = self.music_treble_db

        b_bands = self.peq_banks[EFFECT_BASS_EQ]
        b_bands[0].f0_hz = self.bass_hpf_hz
        b_bands[2].f0_hz = self.bass_hpf_hz
        b_bands[1].f0_hz = self.bass_lpf_hz
        b_bands[3].f0_hz = self.bass_lpf_hz

        t_bands = self.peq_banks[EFFECT_TREBLE_EQ]
        t_bands[0].f0_hz = self.treble_hpf_hz
        t_bands[1].f0_hz = self.treble_hpf_hz

        mid_bands = self.peq_banks[EFFECT_MID_EQ]
        mid_bands[0].f0_hz = self.mid_hpf_hz
        mid_bands[1].f0_hz = self.mid_hpf_hz

        return [
            build_speaker_gain_packet(EFFECT_INPUT_I2S_GAIN, True, False, self.in_i2s_gain),
            build_speaker_gain_packet(EFFECT_INPUT_BT_GAIN, True, False, self.in_bt_gain),
            build_speaker_gain_packet(EFFECT_INPUT_USB_GAIN, True, False, self.in_usb_gain),
            build_speaker_gain_packet(EFFECT_INPUT_OPT_GAIN, True, False, self.in_opt_gain),
            build_noise_gate_packet(self.ng_enable, self.ng_thresh_db, self.ng_ratio, self.ng_attack_ms, self.ng_release_ms),
            build_mvbass_classic_packet(self.mvb_classic_en, self.mvb_classic_hz, self.mvb_classic_int),
            build_mvbass_adv_packet(self.mvb_adv_en, self.mvb_adv_hz, self.mvb_adv_int, self.mvb_adv_enh),
            build_exciter_packet(self.exc_en, self.exc_hz, self.exc_dry, self.exc_wet),
            build_pcm_delay_packet(EFFECT_MUSIC_DELAY, self.music_delay_en, self.music_delay_ms, 50, False),
            build_eq10_packet(EFFECT_MUSIC_BASS_MID_TREB, True, 0.0, m_bands),
            build_speaker_gain_packet(EFFECT_REMIND_GAIN, True, False, self.remind_gain),
            build_drc_packet(EFFECT_MUSIC_DRC, self.drc_enabled, 2, 4, 300, 2000, self.music_drc_dbfs, self.drc_ratio, self.drc_attack_ms, self.drc_release_ms),
            build_eq10_packet(EFFECT_BASS_EQ, True, self.bass_pregain_db, b_bands),
            build_eq10_packet(EFFECT_TREBLE_EQ, True, -2.0, t_bands),
            build_eq10_packet(EFFECT_MID_EQ, True, -2.0, mid_bands),
            build_speaker_gain_packet(EFFECT_TREBLE_GAIN, True, False, self.treble_gain_raw),
            build_speaker_gain_packet(EFFECT_MID_GAIN, True, False, self.mid_gain_raw),
            build_bass_phase_packet(self.bass_phase_180, self.bass_phase_180),
            build_drc_packet(EFFECT_BASS_DRC, self.drc_enabled, 0, 4, 137, 19978, self.spk_drc_dbfs, self.drc_ratio, self.drc_attack_ms, max(20, self.drc_release_ms - 20)),
            build_drc_packet(EFFECT_MID_DRC, self.drc_enabled, 0, 1, 319, 2000, self.spk_drc_dbfs, self.drc_ratio, self.drc_attack_ms, max(20, self.drc_release_ms - 20)),
            build_pcm_delay_packet(EFFECT_BASS_DELAY, self.bass_delay_en, self.bass_delay_ms, 50, False),
        ]

    def apply_to_profile(self, profile: AcpProfile) -> AcpProfile:
        sec98 = profile.find_by_effect_id(EFFECT_TREBLE_GAIN)
        if sec98 is None:
            sec98 = AcpSection("0x98-Gain_Control", EFFECT_TREBLE_GAIN)
            profile.add_section(sec98)
        sec98.set_key("enable", "1")
        sec98.set_key("mute", "0")
        sec98.set_key("gain", str(int(self.treble_gain_raw)))

        sec99 = profile.find_by_effect_id(EFFECT_MID_GAIN)
        if sec99 is None:
            sec99 = AcpSection("0x99-Gain_Control", EFFECT_MID_GAIN)
            profile.add_section(sec99)
        sec99.set_key("enable", "1")
        sec99.set_key("mute", "0")
        sec99.set_key("gain", str(int(self.mid_gain_raw)))

        sec9a = profile.find_by_effect_id(EFFECT_BASS_PHASE)
        if sec9a is None:
            sec9a = AcpSection("0x9a-Phase_Control", EFFECT_BASS_PHASE)
            profile.add_section(sec9a)
        sec9a.set_key("enable", "1" if self.bass_phase_180 else "0")
        sec9a.set_key("phase_difference", "1" if self.bass_phase_180 else "0")

        sec95 = profile.find_by_effect_id(EFFECT_BASS_EQ)
        if sec95 is not None:
            sec95.set_key("pregain", str(db_to_eq_fixed(self.bass_pregain_db)))
            sec95.set_key("filter1_f0", str(self.bass_hpf_hz))
            sec95.set_key("filter2_f0", str(self.bass_lpf_hz))

        sec96 = profile.find_by_effect_id(EFFECT_TREBLE_EQ)
        if sec96 is not None:
            sec96.set_key("filter1_f0", str(self.treble_hpf_hz))
            sec96.set_key("filter2_f0", str(self.treble_hpf_hz))

        sec97 = profile.find_by_effect_id(EFFECT_MID_EQ)
        if sec97 is not None:
            sec97.set_key("filter1_f0", str(self.mid_hpf_hz))
            sec97.set_key("filter2_f0", str(self.mid_hpf_hz))

        for eid, bands in self.peq_banks.items():
            sec_eq = profile.find_by_effect_id(eid)
            if sec_eq is not None:
                for idx, b in enumerate(bands, start=1):
                    sec_eq.set_key(f"filter{idx}_enable", "1" if b.enable else "0")
                    sec_eq.set_key(f"filter{idx}_type", str(b.ftype))
                    sec_eq.set_key(f"filter{idx}_f0", str(b.f0_hz))
                    sec_eq.set_key(f"filter{idx}_Q", str(q_to_fixed(b.q)))
                    sec_eq.set_key(f"filter{idx}_gain", str(db_to_eq_fixed(b.gain_db)))

        for eid, dbfs in (
            (EFFECT_MUSIC_DRC, self.music_drc_dbfs),
            (EFFECT_BASS_DRC, self.spk_drc_dbfs),
            (EFFECT_MID_DRC, self.spk_drc_dbfs),
        ):
            sec_drc = profile.find_by_effect_id(eid)
            if sec_drc is not None:
                sec_drc.set_key("enable", "1" if self.drc_enabled else "0")
                th = str(dbfs_to_drc_threshold(dbfs))
                for k in ("threshold1", "threshold2", "threshold3", "threshold4"):
                    sec_drc.set_key(k, th)
                for k in ("ratio1", "ratio2", "ratio3", "ratio4"):
                    sec_drc.set_key(k, str(self.drc_ratio))
                for k in ("attack_tc1", "attack_tc2", "attack_tc3", "attack_tc4"):
                    sec_drc.set_key(k, str(self.drc_attack_ms))
                for k in ("release_tc1", "release_tc2", "release_tc3", "release_tc4"):
                    sec_drc.set_key(k, str(self.drc_release_ms))

        for eid, gval in (
            (EFFECT_INPUT_I2S_GAIN, self.in_i2s_gain),
            (EFFECT_INPUT_BT_GAIN, self.in_bt_gain),
            (EFFECT_INPUT_USB_GAIN, self.in_usb_gain),
            (EFFECT_INPUT_OPT_GAIN, self.in_opt_gain),
            (EFFECT_REMIND_GAIN, self.remind_gain),
        ):
            sec_g = profile.find_by_effect_id(eid)
            if sec_g is not None:
                sec_g.set_key("gain", str(int(gval)))

        sec85 = profile.find_by_effect_id(EFFECT_NOISE_GATE)
        if sec85 is not None:
            sec85.set_key("enable", "1" if self.ng_enable else "0")
            sec85.set_key("threshold", str(dbfs_to_drc_threshold(self.ng_thresh_db)))
            sec85.set_key("ratio", str(int(self.ng_ratio)))
            sec85.set_key("attack", str(int(self.ng_attack_ms)))
            sec85.set_key("release", str(int(self.ng_release_ms)))

        sec87 = profile.find_by_effect_id(EFFECT_MVBASS_CLASSIC)
        if sec87 is not None:
            sec87.set_key("enable", "1" if self.mvb_classic_en else "0")
            sec87.set_key("cutoff_frequency", str(int(self.mvb_classic_hz)))
            sec87.set_key("intensity", str(int(self.mvb_classic_int)))

        sec88 = profile.find_by_effect_id(EFFECT_MVBASS_ADV)
        if sec88 is not None:
            sec88.set_key("enable", "1" if self.mvb_adv_en else "0")
            sec88.set_key("cutoff_frequency", str(int(self.mvb_adv_hz)))
            sec88.set_key("intensity", str(int(self.mvb_adv_int)))
            sec88.set_key("enhanced", str(int(self.mvb_adv_enh)))

        sec89 = profile.find_by_effect_id(EFFECT_EXCITER)
        if sec89 is not None:
            sec89.set_key("enable", "1" if self.exc_en else "0")
            sec89.set_key("cutoff_frequency", str(int(self.exc_hz)))
            sec89.set_key("dry", str(int(self.exc_dry)))
            sec89.set_key("wet", str(int(self.exc_wet)))

        sec8b = profile.find_by_effect_id(EFFECT_MUSIC_DELAY)
        if sec8b is not None:
            sec8b.set_key("enable", "1" if self.music_delay_en else "0")
            sec8b.set_key("delay", str(int(self.music_delay_ms)))

        sec9d = profile.find_by_effect_id(EFFECT_BASS_DELAY)
        if sec9d is not None:
            sec9d.set_key("enable", "1" if self.bass_delay_en else "0")
            sec9d.set_key("delay", str(int(self.bass_delay_ms)))
        return profile


def get_builtin_presets() -> List[Dsp3WayState]:
    return [
        Dsp3WayState(
            name="3-Way Spec Matched (Chuẩn Loa)",
            description="Cân bằng chuẩn JBL Sub 5\" 5L + Pioneer Mid 6Ω + Ford Treble 4Ω 5W (an toàn <=4600)",
            music_bass_db=1.0,
            music_mid_db=0.5,
            music_treble_db=1.0,
            bass_hpf_hz=60,
            bass_lpf_hz=150,
            bass_pregain_db=-4.0,
            bass_phase_180=False,
            mid_hpf_hz=150,
            mid_gain_raw=4600,
            treble_hpf_hz=9500,
            treble_gain_raw=4600,
            drc_enabled=True,
            music_drc_dbfs=-2.0,
            spk_drc_dbfs=-3.0,
            ini_source="dsp_3way_spec_matched.ini",
        ),
        Dsp3WayState(
            name="Factory Style (DynamicEQ)",
            description="Phong cách nghe nhỏ vẫn đầy bass/tép, tự nén mượt khi mở lớn",
            music_bass_db=2.5,
            music_mid_db=0.0,
            music_treble_db=2.0,
            bass_hpf_hz=55,
            bass_lpf_hz=160,
            bass_pregain_db=-3.0,
            bass_phase_180=False,
            mid_hpf_hz=160,
            mid_gain_raw=4500,
            treble_hpf_hz=9000,
            treble_gain_raw=4400,
            drc_enabled=True,
            music_drc_dbfs=-2.5,
            spk_drc_dbfs=-3.0,
            ini_source="dsp_factory_style_3way.ini",
        ),
        Dsp3WayState(
            name="3-Way Bright Treble Final",
            description="Tăng độ tách bạch vocal và độ tơi dải cao (vẫn khóa ngưỡng an toàn 4600)",
            music_bass_db=1.5,
            music_mid_db=1.0,
            music_treble_db=2.5,
            bass_hpf_hz=60,
            bass_lpf_hz=150,
            bass_pregain_db=-3.5,
            bass_phase_180=False,
            mid_hpf_hz=150,
            mid_gain_raw=4650,
            treble_hpf_hz=8800,
            treble_gain_raw=4600,
            drc_enabled=True,
            music_drc_dbfs=-2.0,
            spk_drc_dbfs=-2.5,
            ini_source="dsp_3way_bright_treble_final.ini",
        ),
        Dsp3WayState(
            name="Punchy Bass Sweet Vocal",
            description="Trầm gọn chắc lực, trung âm ngọt hát karaoke/bolero",
            music_bass_db=2.0,
            music_mid_db=1.5,
            music_treble_db=0.5,
            bass_hpf_hz=58,
            bass_lpf_hz=155,
            bass_pregain_db=-3.0,
            bass_phase_180=False,
            mid_hpf_hz=155,
            mid_gain_raw=4600,
            treble_hpf_hz=9500,
            treble_gain_raw=4350,
            drc_enabled=True,
            music_drc_dbfs=-2.0,
            spk_drc_dbfs=-2.5,
            ini_source="dsp_punchy_bass_sweet_vocal.ini",
        ),
    ]


# ==============================================================================
# 4. ZERO-DEPENDENCY WINDOWS NATIVE USB HID + SERIAL COM TRANSPORT
# ==============================================================================

class UsbEndpointInfo:
    def __init__(self, kind: str, path: str, label: str, vid: int = 0, pid: int = 0, out_report_len: int = 65):
        self.kind = kind  # "HID" or "COM"
        self.path = path
        self.label = label
        self.vid = vid
        self.pid = pid
        self.out_report_len = out_report_len

    def is_preferred_mvsilicon(self) -> bool:
        upper = self.label.upper()
        return self.vid in (0x8888, 0x10D6) or "BEST SOUND" in upper or "MVSILICON" in upper or "BP1048" in upper


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", _GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


class _HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Size", wintypes.ULONG),
        ("VendorID", wintypes.USHORT),
        ("ProductID", wintypes.USHORT),
        ("VersionNumber", wintypes.USHORT),
    ]


class _HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", wintypes.USHORT),
        ("UsagePage", wintypes.USHORT),
        ("InputReportByteLength", wintypes.USHORT),
        ("OutputReportByteLength", wintypes.USHORT),
        ("FeatureReportByteLength", wintypes.USHORT),
        ("Reserved", wintypes.USHORT * 17),
        ("NumberLinkCollectionNodes", wintypes.USHORT),
        ("NumberInputButtonCaps", wintypes.USHORT),
        ("NumberInputValueCaps", wintypes.USHORT),
        ("NumberInputDataIndices", wintypes.USHORT),
        ("NumberOutputButtonCaps", wintypes.USHORT),
        ("NumberOutputValueCaps", wintypes.USHORT),
        ("NumberOutputDataIndices", wintypes.USHORT),
        ("NumberFeatureButtonCaps", wintypes.USHORT),
        ("NumberFeatureValueCaps", wintypes.USHORT),
        ("NumberFeatureDataIndices", wintypes.USHORT),
    ]


class _DCB(ctypes.Structure):
    _fields_ = [
        ("DCBlength", wintypes.DWORD),
        ("BaudRate", wintypes.DWORD),
        ("fBinary", wintypes.DWORD, 1),
        ("fParity", wintypes.DWORD, 1),
        ("fOutxCtsFlow", wintypes.DWORD, 1),
        ("fOutxDsrFlow", wintypes.DWORD, 1),
        ("fDtrControl", wintypes.DWORD, 2),
        ("fDsrSensitivity", wintypes.DWORD, 1),
        ("fTXContinueOnXoff", wintypes.DWORD, 1),
        ("fOutX", wintypes.DWORD, 1),
        ("fInX", wintypes.DWORD, 1),
        ("fErrorChar", wintypes.DWORD, 1),
        ("fNull", wintypes.DWORD, 1),
        ("fRtsControl", wintypes.DWORD, 2),
        ("fAbortOnError", wintypes.DWORD, 1),
        ("fDummy2", wintypes.DWORD, 17),
        ("wReserved", wintypes.WORD),
        ("XonLim", wintypes.WORD),
        ("XoffLim", wintypes.WORD),
        ("ByteSize", ctypes.c_ubyte),
        ("Parity", ctypes.c_ubyte),
        ("StopBits", ctypes.c_ubyte),
        ("XonChar", ctypes.c_char),
        ("XoffChar", ctypes.c_char),
        ("ErrorChar", ctypes.c_char),
        ("EofChar", ctypes.c_char),
        ("EvtChar", ctypes.c_char),
        ("wReserved1", wintypes.WORD),
    ]


class _COMMTIMEOUTS(ctypes.Structure):
    _fields_ = [
        ("ReadIntervalTimeout", wintypes.DWORD),
        ("ReadTotalTimeoutMultiplier", wintypes.DWORD),
        ("ReadTotalTimeoutConstant", wintypes.DWORD),
        ("WriteTotalTimeoutMultiplier", wintypes.DWORD),
        ("WriteTotalTimeoutConstant", wintypes.DWORD),
    ]


def scan_windows_usb_endpoints() -> List[UsbEndpointInfo]:
    """Enumerates USB HID devices and Serial COM ports using native Windows DLLs."""
    endpoints: List[UsbEndpointInfo] = []

    # 1. Enumerate USB HID via hid.dll + setupapi.dll
    if os.name == "nt":
        try:
            hid = ctypes.windll.hid
            setupapi = ctypes.windll.setupapi
            kernel32 = ctypes.windll.kernel32

            guid = _GUID()
            hid.HidD_GetHidGuid(ctypes.byref(guid))

            DIGCF_PRESENT = 0x02
            DIGCF_DEVICEINTERFACE = 0x10
            h_dev_info = setupapi.SetupDiGetClassDevsW(
                ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
            )
            INVALID_HANDLE = ctypes.c_void_p(-1).value
            if h_dev_info != INVALID_HANDLE:
                try:
                    iface_data = _SP_DEVICE_INTERFACE_DATA()
                    iface_data.cbSize = ctypes.sizeof(_SP_DEVICE_INTERFACE_DATA)
                    idx = 0
                    while setupapi.SetupDiEnumDeviceInterfaces(
                        h_dev_info, None, ctypes.byref(guid), idx, ctypes.byref(iface_data)
                    ):
                        idx += 1
                        req_size = wintypes.DWORD(0)
                        setupapi.SetupDiGetDeviceInterfaceDetailW(
                            h_dev_info, ctypes.byref(iface_data), None, 0, ctypes.byref(req_size), None
                        )
                        if req_size.value <= 4:
                            continue
                        buf = ctypes.create_string_buffer(req_size.value)
                        # cbSize = 8 on 64-bit Windows, 6 on 32-bit
                        cb_size = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
                        ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = cb_size
                        if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                            h_dev_info, ctypes.byref(iface_data), buf, req_size.value, None, None
                        ):
                            continue
                        dev_path = ctypes.wstring_at(ctypes.addressof(buf) + 4)

                        h_hid = kernel32.CreateFileW(
                            dev_path, 0, 3, None, 3, 0, None
                        )
                        if h_hid != INVALID_HANDLE:
                            try:
                                attr = _HIDD_ATTRIBUTES()
                                attr.Size = ctypes.sizeof(_HIDD_ATTRIBUTES)
                                if hid.HidD_GetAttributes(h_hid, ctypes.byref(attr)):
                                    prod_buf = ctypes.create_unicode_buffer(128)
                                    prod_name = "USB HID"
                                    if hid.HidD_GetProductString(h_hid, prod_buf, 256) and prod_buf.value.strip():
                                        prod_name = prod_buf.value.strip()
                                    out_len = 65
                                    ppd = ctypes.c_void_p()
                                    if hid.HidD_GetPreparsedData(h_hid, ctypes.byref(ppd)):
                                        caps = _HIDP_CAPS()
                                        if hid.HidP_GetCaps(ppd, ctypes.byref(caps)) == 0x00110000:
                                            out_len = max(64, int(caps.OutputReportByteLength))
                                        hid.HidD_FreePreparsedData(ppd)
                                    label = f"[HID] {prod_name} (VID:{attr.VendorID:04X} PID:{attr.ProductID:04X})"
                                    endpoints.append(
                                        UsbEndpointInfo("HID", dev_path, label, attr.VendorID, attr.ProductID, out_len)
                                    )
                            finally:
                                kernel32.CloseHandle(h_hid)
                finally:
                    setupapi.SetupDiDestroyDeviceInfoList(h_dev_info)
        except Exception:
            pass

    # 2. Enumerate Serial COM ports via Registry
    if winreg is not None:
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM")
            i = 0
            while True:
                try:
                    name, val, _ = winreg.EnumValue(key, i)
                    endpoints.append(UsbEndpointInfo("COM", rf"\\.\{val}", f"[COM] {val} ({name})"))
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except OSError:
            pass

    # Put preferred MVSilicon / Best Sound devices first
    endpoints.sort(key=lambda e: (0 if e.is_preferred_mvsilicon() else 1, e.kind, e.label))
    return endpoints


class WinUsbTransport:
    """Handles read/write over Windows USB HID or Serial COM without external packages."""

    def __init__(self, on_rx=None, on_log=None):
        self.handle = None
        self.endpoint: Optional[UsbEndpointInfo] = None
        self.on_rx = on_rx
        self.on_log = on_log
        self._stop_evt = threading.Event()
        self._rx_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def is_connected(self) -> bool:
        return self.handle is not None

    def connect(self, endpoint: UsbEndpointInfo) -> bool:
        self.disconnect()
        if os.name != "nt":
            return False
        kernel32 = ctypes.windll.kernel32
        GENERIC_RW = 0x80000000 | 0x40000000
        FILE_SHARE_RW = 0x03
        OPEN_EXISTING = 3
        INVALID_HANDLE = ctypes.c_void_p(-1).value

        h = kernel32.CreateFileW(
            endpoint.path, GENERIC_RW, FILE_SHARE_RW, None, OPEN_EXISTING, 0, None
        )
        if h == INVALID_HANDLE:
            err = ctypes.GetLastError()
            if self.on_log:
                self.on_log("ERR", f"Không mở được {endpoint.label} (WinError {err}). Kiểm tra loa đã bật nguồn chưa hoặc đóng ACPWorkbench.")
            return False

        if endpoint.kind == "COM":
            dcb = _DCB()
            dcb.DCBlength = ctypes.sizeof(_DCB)
            if kernel32.GetCommState(h, ctypes.byref(dcb)):
                dcb.BaudRate = 115200
                dcb.ByteSize = 8
                dcb.Parity = 0
                dcb.StopBits = 0
                kernel32.SetCommState(h, ctypes.byref(dcb))
            timeouts = _COMMTIMEOUTS(20, 0, 60, 0, 60)
            kernel32.SetCommTimeouts(h, ctypes.byref(timeouts))

        self.handle = h
        self.endpoint = endpoint
        self._stop_evt.clear()
        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self._rx_thread.start()
        if self.on_log:
            self.on_log("SYS", f"Đã kết nối: {endpoint.label}")
        return True

    def disconnect(self) -> None:
        self._stop_evt.set()
        if self.handle is not None and os.name == "nt":
            try:
                ctypes.windll.kernel32.CloseHandle(self.handle)
            except Exception:
                pass
        self.handle = None
        self.endpoint = None

    def send_packet(self, pkt: MvsiliconPacket) -> bool:
        raw = pkt.to_bytes()
        if not self.is_connected:
            if self.on_log:
                self.on_log("SIM-TX", f"0x{pkt.effect_id:02X} ({len(raw)}B): {pkt.to_hex()}")
            return False

        with self._lock:
            kernel32 = ctypes.windll.kernel32
            written = wintypes.DWORD(0)
            if self.endpoint and self.endpoint.kind == "HID":
                rep_len = max(65, self.endpoint.out_report_len)
                chunk_cap = rep_len - 1
                for offset in range(0, len(raw), chunk_cap):
                    part = raw[offset:offset + chunk_cap]
                    report = bytes([0x00]) + part + bytes(chunk_cap - len(part))
                    ok = kernel32.WriteFile(self.handle, report, len(report), ctypes.byref(written), None)
                    if not ok:
                        if self.on_log:
                            self.on_log("ERR", f"Gửi HID thất bại (WinError {ctypes.GetLastError()})")
                        return False
            else:
                ok = kernel32.WriteFile(self.handle, raw, len(raw), ctypes.byref(written), None)
                if not ok:
                    if self.on_log:
                        self.on_log("ERR", f"Gửi COM thất bại (WinError {ctypes.GetLastError()})")
                    return False

        if self.on_log:
            self.on_log("TX", f"0x{pkt.effect_id:02X} ({len(raw)}B): {pkt.to_hex()}")
        return True

    def _rx_loop(self) -> None:
        kernel32 = ctypes.windll.kernel32
        buf = ctypes.create_string_buffer(256)
        read_bytes = wintypes.DWORD(0)
        while not self._stop_evt.is_set() and self.handle is not None:
            ok = kernel32.ReadFile(self.handle, buf, 256, ctypes.byref(read_bytes), None)
            if ok and read_bytes.value > 0:
                data = buf.raw[:read_bytes.value]
                frames = MvsiliconPacket.parse_stream(data)
                if self.on_rx:
                    for f in frames:
                        self.on_rx(f)
            else:
                time.sleep(0.03)


# ==============================================================================
# 5. RBJ BIQUAD FREQUENCY RESPONSE SIMULATOR (FOR REALTIME 3-WAY GRAPH)
# ==============================================================================

def _biquad_mag_db(ftype: int, f0: float, q: float, gain_db: float, freqs: List[float], fs: float = 48000.0) -> List[float]:
    if ftype == FILTER_PEAKING and abs(gain_db) < 0.05:
        return [0.0] * len(freqs)
    w0 = 2.0 * math.pi * max(10.0, min(fs * 0.45, f0)) / fs
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    alpha = sin_w0 / (2.0 * max(0.2, q))
    A = 10.0 ** (gain_db / 40.0)

    if ftype == FILTER_PEAKING:
        b0, b1, b2 = 1.0 + alpha * A, -2.0 * cos_w0, 1.0 - alpha * A
        a0, a1, a2 = 1.0 + alpha / A, -2.0 * cos_w0, 1.0 - alpha / A
    elif ftype == FILTER_HIGH_PASS:
        b0, b1, b2 = (1.0 + cos_w0) / 2.0, -(1.0 + cos_w0), (1.0 + cos_w0) / 2.0
        a0, a1, a2 = 1.0 + alpha, -2.0 * cos_w0, 1.0 - alpha
    elif ftype == FILTER_LOW_PASS:
        b0, b1, b2 = (1.0 - cos_w0) / 2.0, 1.0 - cos_w0, (1.0 - cos_w0) / 2.0
        a0, a1, a2 = 1.0 + alpha, -2.0 * cos_w0, 1.0 - alpha
    elif ftype == FILTER_HIGH_SHELF:
        sq = 2.0 * math.sqrt(A) * alpha
        b0 = A * ((A + 1) + (A - 1) * cos_w0 + sq)
        b1 = -2 * A * ((A - 1) + (A + 1) * cos_w0)
        b2 = A * ((A + 1) + (A - 1) * cos_w0 - sq)
        a0 = (A + 1) - (A - 1) * cos_w0 + sq
        a1 = 2 * ((A - 1) - (A + 1) * cos_w0)
        a2 = (A + 1) - (A - 1) * cos_w0 - sq
    else:
        return [0.0] * len(freqs)

    out = []
    for f in freqs:
        w = 2.0 * math.pi * f / fs
        cw, sw = math.cos(w), math.sin(w)
        c2w, s2w = math.cos(2 * w), math.sin(2 * w)
        nr = b0 + b1 * cw + b2 * c2w
        ni = -b1 * sw - b2 * s2w
        dr = a0 + a1 * cw + a2 * c2w
        di = -a1 * sw - a2 * s2w
        mag = math.sqrt((nr * nr + ni * ni) / max(1e-18, dr * dr + di * di))
        out.append(20.0 * math.log10(max(1e-6, mag)))
    return out


# ==============================================================================
# 6. MODERN PRO AUDIO WEB-DESKTOP SERVER (Edge/Chrome --app + Python Win32 USB)
# ==============================================================================

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import urllib.error
import urllib.request
import webbrowser


class AnSoundWebController:
    def __init__(self):
        self.work_dir = os.path.dirname(os.path.abspath(__file__))
        self.presets = get_builtin_presets()
        self.state = self.presets[0]
        self.base_profile: Optional[AcpProfile] = None
        self.endpoints: List[UsbEndpointInfo] = []
        self.logs: List[str] = []
        self.transport = WinUsbTransport(on_rx=self._on_rx, on_log=self._log)
        self.load_preset(0)

    def _log(self, tag: str, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.logs.append(f"[{ts}] [{tag}] {msg}")
        if len(self.logs) > 250:
            self.logs = self.logs[-250:]

    def _on_rx(self, pkt: MvsiliconPacket) -> None:
        self._log("RX", f"0x{pkt.effect_id:02X}: {pkt.to_hex()}")

    def load_preset(self, idx: int) -> dict:
        if 0 <= idx < len(self.presets):
            self.state = self.presets[idx]
            if self.state.ini_source:
                ini_path = os.path.join(self.work_dir, self.state.ini_source)
                if os.path.exists(ini_path):
                    with open(ini_path, "r", encoding="utf-8", errors="ignore") as f:
                        self.base_profile = parse_ini(f.read())
                    self._extract_profile_into_state(self.base_profile)
                    self._log("SYS", f"Đã nạp preset: {self.state.ini_source} ({len(self.base_profile.sections)} khối)")
        return self.to_dict()

    def _extract_profile_into_state(self, prof: AcpProfile) -> None:
        s = self.state
        for eid, attr in (
            (EFFECT_INPUT_I2S_GAIN, "in_i2s_gain"),
            (EFFECT_INPUT_BT_GAIN, "in_bt_gain"),
            (EFFECT_INPUT_USB_GAIN, "in_usb_gain"),
            (EFFECT_INPUT_OPT_GAIN, "in_opt_gain"),
            (EFFECT_REMIND_GAIN, "remind_gain"),
            (EFFECT_MID_GAIN, "mid_gain_raw"),
            (EFFECT_TREBLE_GAIN, "treble_gain_raw"),
        ):
            sec = prof.find_by_effect_id(eid)
            if sec:
                setattr(s, attr, sec.get_int("gain", getattr(s, attr)))

        s9a = prof.find_by_effect_id(EFFECT_BASS_PHASE)
        if s9a:
            s.bass_phase_180 = (s9a.get_int("phase_difference", 0) == 1)

        s85 = prof.find_by_effect_id(EFFECT_NOISE_GATE)
        if s85:
            s.ng_enable = (s85.get_int("enable", 0) == 1)
            s.ng_thresh_db = s85.get_int("threshold", -6500) / 100.0

        s87 = prof.find_by_effect_id(EFFECT_MVBASS_CLASSIC)
        if s87:
            s.mvb_classic_en = (s87.get_int("enable", 0) == 1)
            s.mvb_classic_hz = s87.get_int("cutoff_frequency", 58)
            s.mvb_classic_int = s87.get_int("intensity", 24)

        s88 = prof.find_by_effect_id(EFFECT_MVBASS_ADV)
        if s88:
            s.mvb_adv_en = (s88.get_int("enable", 0) == 1)
            s.mvb_adv_hz = s88.get_int("cutoff_frequency", 56)
            s.mvb_adv_int = s88.get_int("intensity", 15)

        s89 = prof.find_by_effect_id(EFFECT_EXCITER)
        if s89:
            s.exc_en = (s89.get_int("enable", 0) == 1)
            s.exc_hz = s89.get_int("cutoff_frequency", 4500)
            s.exc_wet = s89.get_int("wet", 25)

        s9d = prof.find_by_effect_id(EFFECT_BASS_DELAY)
        if s9d:
            s.bass_delay_en = (s9d.get_int("enable", 0) == 1)
            s.bass_delay_ms = s9d.get_int("delay", 0)

        for eid in (EFFECT_MUSIC_BASS_MID_TREB, EFFECT_BASS_EQ, EFFECT_MID_EQ, EFFECT_TREBLE_EQ):
            sec_eq = prof.find_by_effect_id(eid)
            if sec_eq:
                bands = []
                for idx in range(1, 11):
                    en = (sec_eq.get_int(f"filter{idx}_enable", 0) == 1)
                    ft = sec_eq.get_int(f"filter{idx}_type", 0)
                    f0 = sec_eq.get_int(f"filter{idx}_f0", 1000)
                    q = max(0.2, sec_eq.get_int(f"filter{idx}_Q", 724) / 1024.0)
                    g = eq_fixed_to_db(sec_eq.get_int(f"filter{idx}_gain", 0))
                    bands.append(EqBand(en, ft, f0, q, g))
                s.peq_banks[eid] = bands
                if eid == EFFECT_BASS_EQ:
                    s.bass_hpf_hz = bands[0].f0_hz
                    s.bass_lpf_hz = bands[1].f0_hz
                    s.bass_pregain_db = round(eq_fixed_to_db(sec_eq.get_int("pregain", -1024)), 1)
                elif eid == EFFECT_TREBLE_EQ:
                    s.treble_hpf_hz = bands[0].f0_hz
                elif eid == EFFECT_MID_EQ:
                    s.mid_hpf_hz = bands[0].f0_hz

    def _build_hw_info(self) -> str:
        p = self.base_profile
        if p is None:
            return "Chưa nạp file .INI nền."
        fw = p.find_by_effect_id(0x00)
        sys_c = p.find_by_effect_id(0x01)
        pga0 = p.find_by_effect_id(0x03)
        adc0 = p.find_by_effect_id(0x04)
        dac0 = p.find_by_effect_id(0x09)
        tag = p.find_by_effect_id(0xFC)
        eff_list = p.find_by_effect_id(0x80)
        tag_ascii = ""
        if tag and tag.get("data"):
            try:
                tag_ascii = "".join(chr(int(x.strip())) for x in tag.get("data").split(",") if x.strip().isdigit())
            except Exception:
                tag_ascii = tag.get("data", "")

        s = self.state
        return "\n".join([
            f"ACPWorkbench Version : {p.acp_version}",
            f"Communication Port   : {p.comm_port}",
            f"Tổng số khối (.INI)  : {len(p.sections)} sections",
            f"Firmware / Effect    : {fw.get('firmware_version', '?') if fw else '?'} / {fw.get('effect_version', '?') if fw else '?'}",
            f"User Tag (0xFC)      : {tag_ascii}",
            f"Sample Rate (0x01)   : code={sys_c.get('system_sample_rate', '?') if sys_c else '?'} (7 = 48kHz)",
            f"PGA0 Line1 Gain (0x03): L={pga0.get('line1_left_gain', '?') if pga0 else '?'}, R={pga0.get('line1_right_gain', '?') if pga0 else '?'}",
            f"ADC0 Vol (0x04)      : L={adc0.get('left_volume', '?') if adc0 else '?'}, DC_Blocker={adc0.get('dc_blocker', '?') if adc0 else '?'}",
            f"DAC0 Vol (0x09)      : L={dac0.get('left_volume', '?') if dac0 else '?'}, Dither={dac0.get('dither', '?') if dac0 else '?'}",
            f"Active Effects (0x80): {len(eff_list.entries) if eff_list else 0} mục cấu hình",
            "",
            "--- TÓM TẮT VẬT LÝ & AN TOÀN 3-WAY ---",
            f"• Sub JBL 5\" (5L)     : HPF {s.bass_hpf_hz}Hz / LPF {s.bass_lpf_hz}Hz | Pregain {s.bass_pregain_db:+.1f}dB",
            f"• Mid Pioneer (6Ω)   : HPF {s.mid_hpf_hz}Hz | Gain {s.mid_gain_raw}",
            f"• Treble Ford (4Ω 5W): HPF {s.treble_hpf_hz}Hz | Gain {s.treble_gain_raw} (Max an toàn 4600)",
            f"• MVBass / Exciter   : MVBass={'ON' if s.mvb_classic_en else 'OFF'} ({s.mvb_classic_int}%) | Exciter={'ON' if s.exc_en else 'OFF'}",
            f"• Noise Gate / DRC   : Gate={'ON' if s.ng_enable else 'OFF'} ({s.ng_thresh_db:.0f}dB) | DRC={s.music_drc_dbfs:.1f}/{s.spk_drc_dbfs:.1f}dBFS",
        ])

    def to_dict(self) -> dict:
        s = self.state
        return {
            "name": s.name,
            "description": s.description,
            "preset_names": [p.name for p in self.presets],
            "music_bass_db": s.music_bass_db,
            "music_mid_db": s.music_mid_db,
            "music_treble_db": s.music_treble_db,
            "bass_hpf_hz": s.bass_hpf_hz,
            "bass_lpf_hz": s.bass_lpf_hz,
            "bass_pregain_db": s.bass_pregain_db,
            "bass_phase_180": s.bass_phase_180,
            "mid_hpf_hz": s.mid_hpf_hz,
            "mid_gain_raw": s.mid_gain_raw,
            "treble_hpf_hz": s.treble_hpf_hz,
            "treble_gain_raw": s.treble_gain_raw,
            "drc_enabled": s.drc_enabled,
            "music_drc_dbfs": s.music_drc_dbfs,
            "spk_drc_dbfs": s.spk_drc_dbfs,
            "drc_ratio": s.drc_ratio,
            "drc_attack_ms": s.drc_attack_ms,
            "drc_release_ms": s.drc_release_ms,
            "in_i2s_gain": s.in_i2s_gain,
            "in_bt_gain": s.in_bt_gain,
            "in_usb_gain": s.in_usb_gain,
            "in_opt_gain": s.in_opt_gain,
            "remind_gain": s.remind_gain,
            "ng_enable": s.ng_enable,
            "ng_thresh_db": s.ng_thresh_db,
            "mvb_classic_en": s.mvb_classic_en,
            "mvb_classic_hz": s.mvb_classic_hz,
            "mvb_classic_int": s.mvb_classic_int,
            "mvb_adv_en": s.mvb_adv_en,
            "mvb_adv_hz": s.mvb_adv_hz,
            "mvb_adv_int": s.mvb_adv_int,
            "exc_en": s.exc_en,
            "exc_hz": s.exc_hz,
            "exc_wet": s.exc_wet,
            "bass_delay_en": s.bass_delay_en,
            "bass_delay_ms": s.bass_delay_ms,
            "peq_banks": {
                str(eid): [
                    {"enable": b.enable, "ftype": b.ftype, "f0_hz": b.f0_hz, "q": b.q, "gain_db": b.gain_db}
                    for b in bands
                ]
                for eid, bands in s.peq_banks.items()
            },
            "hw_info": self._build_hw_info(),
        }

    def update_from_dict(self, data: dict) -> None:
        s = self.state
        for k in (
            "music_bass_db", "music_mid_db", "music_treble_db", "bass_pregain_db",
            "music_drc_dbfs", "spk_drc_dbfs", "ng_thresh_db",
        ):
            if k in data:
                setattr(s, k, float(data[k]))
        for k in (
            "bass_hpf_hz", "bass_lpf_hz", "mid_hpf_hz", "mid_gain_raw",
            "treble_hpf_hz", "treble_gain_raw", "drc_ratio", "drc_attack_ms", "drc_release_ms",
            "in_i2s_gain", "in_bt_gain", "in_usb_gain", "in_opt_gain", "remind_gain",
            "mvb_classic_hz", "mvb_classic_int", "mvb_adv_hz", "mvb_adv_int",
            "exc_hz", "exc_wet", "bass_delay_ms",
        ):
            if k in data:
                setattr(s, k, int(data[k]))
        for k in (
            "bass_phase_180", "drc_enabled", "ng_enable",
            "mvb_classic_en", "mvb_adv_en", "exc_en", "bass_delay_en",
        ):
            if k in data:
                setattr(s, k, bool(data[k]))
        if "peq_banks" in data and isinstance(data["peq_banks"], dict):
            for eid_str, arr in data["peq_banks"].items():
                eid = int(eid_str)
                s.peq_banks[eid] = [
                    EqBand(bool(b["enable"]), int(b["ftype"]), int(b["f0_hz"]), float(b["q"]), float(b["gain_db"]))
                    for b in arr
                ]

    def push_all(self) -> int:
        pkts = self.state.build_packets()
        for pkt in pkts:
            self.transport.send_packet(pkt)
            time.sleep(0.012)
        self._log("SYS", f"Đã đẩy {len(pkts)} khối DSP lên mạch.")
        return len(pkts)

    def run_autotune(self, mode: str) -> dict:
        s = self.state
        if mode == "hifi":
            s.bass_hpf_hz, s.bass_lpf_hz, s.bass_pregain_db = 60, 150, -4.0
            s.mid_hpf_hz, s.mid_gain_raw = 150, 4600
            s.treble_hpf_hz, s.treble_gain_raw = 9500, 4550
            s.music_bass_db, s.music_mid_db, s.music_treble_db = 1.0, 0.5, 1.0
            s.mvb_classic_en, s.mvb_classic_hz, s.mvb_classic_int = True, 58, 22
            s.exc_en, s.exc_hz, s.exc_wet = False, 4500, 20
            s.ng_enable, s.ng_thresh_db = True, -68.0
            s.drc_enabled, s.music_drc_dbfs, s.spk_drc_dbfs = True, -2.0, -3.0
        elif mode == "outdoor":
            s.bass_hpf_hz, s.bass_lpf_hz, s.bass_pregain_db = 65, 155, -4.5
            s.mid_hpf_hz, s.mid_gain_raw = 160, 4650
            s.treble_hpf_hz, s.treble_gain_raw = 9500, 4350
            s.music_bass_db, s.music_mid_db, s.music_treble_db = 0.5, 1.0, 0.5
            s.mvb_classic_en, s.mvb_classic_hz, s.mvb_classic_int = True, 60, 18
            s.exc_en, s.exc_hz, s.exc_wet = True, 5000, 20
            s.ng_enable, s.ng_thresh_db = True, -62.0
            s.drc_enabled, s.music_drc_dbfs, s.spk_drc_dbfs = True, -3.0, -3.5
        else:
            s.bass_hpf_hz, s.bass_lpf_hz, s.bass_pregain_db = 52, 150, -3.0
            s.mid_hpf_hz, s.mid_gain_raw = 145, 4500
            s.treble_hpf_hz, s.treble_gain_raw = 9000, 4450
            s.music_bass_db, s.music_mid_db, s.music_treble_db = 3.0, 0.5, 2.0
            s.mvb_classic_en, s.mvb_classic_hz, s.mvb_classic_int = True, 56, 32
            s.exc_en, s.exc_hz, s.exc_wet = True, 4500, 28
            s.ng_enable, s.ng_thresh_db = True, -72.0
            s.drc_enabled, s.music_drc_dbfs, s.spk_drc_dbfs = True, -2.0, -2.5
        self.push_all()
        return self.to_dict()

    def _resolve_gemini_models(self, api_key: str) -> List[str]:
        """Queries available Gemini models for the API key and returns ranked generateContent models."""
        preferred = (
            "gemini-flash-latest",
            "gemini-3-flash-preview",
            "gemini-3.1-flash-lite-preview",
            "gemini-2.5-flash-lite",
            "gemini-3.8-flash",
            "gemini-2.5-flash",
            "gemini-pro-latest",
        )
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            usable = []
            for m in data.get("models", []):
                methods = m.get("supportedGenerationMethods", [])
                name = m.get("name", "").replace("models/", "")
                if "generateContent" in methods and "gemini" in name and "tts" not in name and "image" not in name:
                    usable.append(name)
            ranked = [p for p in preferred if p in usable]
            for u in usable:
                if u not in ranked:
                    ranked.append(u)
            if ranked:
                return ranked[:5]
        except Exception:
            pass
        return ["gemini-flash-latest", "gemini-3-flash-preview", "gemini-2.5-flash-lite"]

    def ai_chat(self, prompt: str, history: list, baseline: Optional[dict], api_key: str = "") -> dict:
        cur = self.to_dict()
        base = baseline if baseline else cur
        editable_keys = (
            "music_bass_db", "music_mid_db", "music_treble_db",
            "bass_hpf_hz", "bass_lpf_hz", "bass_pregain_db", "bass_phase_180",
            "mid_hpf_hz", "mid_gain_raw", "treble_hpf_hz", "treble_gain_raw",
            "drc_enabled", "music_drc_dbfs", "spk_drc_dbfs",
            "mvb_classic_en", "mvb_classic_hz", "mvb_classic_int",
            "exc_en", "exc_hz", "exc_wet", "ng_enable", "ng_thresh_db", "bass_delay_ms",
        )
        base_summary = {k: base.get(k) for k in editable_keys if k in base}
        cur_summary = {k: cur.get(k) for k in editable_keys if k in cur}

        if api_key and api_key.strip():
            key_clean = api_key.strip()
            if not (key_clean.startswith("AIza") or key_clean.startswith("AQ.")) or any(c.isspace() for c in key_clean):
                key_clean = ""
        else:
            key_clean = ""
        if key_clean:
            models_to_try = self._resolve_gemini_models(key_clean)
            sys_prompt = (
                "Bạn là trợ lý AI Gemini thông minh, thân thiện giống như trên website gemini.google.com. "
                "Với các câu hỏi bình thường, đời thường, chào hỏi hoặc kiến thức chung: hãy trả lời tự nhiên, đầy đủ như Gemini bình thường và để \"changes\": {}. "
                "CHỈ khi người dùng hỏi về chuyên môn âm thanh, loa, EQ, phân tần hoặc yêu cầu tinh chỉnh mạch DSP MVSilicon BP1048B2 "
                "(Quốc Doàn 70Wx2: Sub 5\" JBL 5L, Mid Pioneer 6 Ohm, Treble Ford 4 Ohm 5W tụ 3uF — LUÔN giữ treble_gain_raw <= 4600 để chống cháy loa), "
                "bạn mới trả lời theo chuyên môn Kỹ sư Audio DSP và điền các thông số cần thay đổi vào \"changes\". "
                "Luôn trả về JSON thuần theo schema: {\"reply\": \"câu trả lời tiếng Việt\", \"changes\": {}}. "
                "Các key hợp lệ cho changes: " + ", ".join(editable_keys)
            )
            contents = []
            for m in (history or [])[-10:]:
                role = "model" if m.get("role") in ("assistant", "model") else "user"
                txt_m = str(m.get("text", "")).strip()
                if txt_m:
                    contents.append({"role": role, "parts": [{"text": txt_m}]})
            dsp_ctx = (
                f"[Ngữ cảnh DSP nền — chỉ dùng khi người dùng hỏi/chỉnh âm thanh]\n"
                f"Baseline: {json.dumps(base_summary, ensure_ascii=False)}\n"
                f"Current: {json.dumps(cur_summary, ensure_ascii=False)}\n\n"
                f"Người dùng: {prompt}"
            )
            contents.append({"role": "user", "parts": [{"text": dsp_ctx}]})
            payload = {
                "system_instruction": {"parts": [{"text": sys_prompt}]},
                "contents": contents,
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.5},
            }
            for model_name in models_to_try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={key_clean}"
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=25) as resp:
                        res_json = json.loads(resp.read().decode("utf-8"))
                    txt = res_json["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = json.loads(txt)
                    changes = {k: v for k, v in (parsed.get("changes") or {}).items() if k in editable_keys}
                    if "treble_gain_raw" in changes:
                        changes["treble_gain_raw"] = min(TREBLE_SAFE_MAX_GAIN, int(changes["treble_gain_raw"]))
                    self._log("AI", f"Gemini ({model_name}) trả lời OK ({len(changes)} thông số).")
                    return {"ok": True, "source": model_name, "reply": parsed.get("reply", ""), "changes": changes}
                except Exception as exc:
                    self._log("AI", f"Model {model_name} lỗi ({exc}), thử model kế tiếp...")

        # 2. Try local Ollama LLM if running on 127.0.0.1:11434
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1.2) as r_tags:
                tags_data = json.loads(r_tags.read().decode("utf-8"))
            models = [m.get("name") for m in tags_data.get("models", []) if m.get("name")]
            if models:
                ol_payload = {
                    "model": models[0],
                    "stream": False,
                    "format": "json",
                    "messages": [
                        {"role": "system", "content": (
                            "Bạn là Kỹ sư DSP MVSilicon BP1048B2 (Sub 5\" 5L, Mid 6Ω, Treble 4Ω 5W <=4600). "
                            "Trả về JSON: {\"reply\":\"tư vấn ngắn tiếng Việt\",\"changes\":{\"key\":val}}. "
                            "Keys hợp lệ: " + ", ".join(editable_keys)
                        )},
                        {"role": "user", "content": f"Baseline: {json.dumps(base_summary)}\nCurrent: {json.dumps(cur_summary)}\nYêu cầu: {prompt}"},
                    ],
                }
                ol_req = urllib.request.Request(
                    "http://127.0.0.1:11434/api/chat",
                    data=json.dumps(ol_payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(ol_req, timeout=20) as r_ol:
                    ol_res = json.loads(r_ol.read().decode("utf-8"))
                parsed = json.loads(ol_res["message"]["content"])
                changes = {k: v for k, v in (parsed.get("changes") or {}).items() if k in editable_keys}
                if "treble_gain_raw" in changes:
                    changes["treble_gain_raw"] = min(TREBLE_SAFE_MAX_GAIN, int(changes["treble_gain_raw"]))
                return {"ok": True, "source": f"ollama:{models[0]}", "reply": parsed.get("reply", ""), "changes": changes}
        except Exception:
            pass

        # 3. Embedded Audio DSP Expert Engine (Genre Configurator + Technical Q&A + Tuning)
        p_low = (prompt or "").strip().lower()
        changes = {}
        notes = []

        # 1. Greetings or status/info questions -> answer directly without mutating DSP
        is_greeting = any(w in p_low for w in ("xin chào", "chào bạn", "hello", "hi ", "alo")) or p_low in ("chào", "hi")
        is_status_q = any(w in p_low for w in ("kết nối", "trạng thái", "hiện tại", "thông số", "đang thế nào", "có được không"))
        if is_greeting and len(p_low) < 25:
            usb_txt = "Đã kết nối USB" if self.transport.is_connected else "Chưa kết nối USB"
            return {
                "ok": True,
                "source": "smart-dsp-ai",
                "reply": (
                    f"Chào bạn! Mình là DSP AI cho mạch Quốc Doàn 70Wx2 ({usb_txt}). "
                    f"Cấu hình hiện tại: Sub HPF {cur_summary['bass_hpf_hz']}Hz / LPF {cur_summary['bass_lpf_hz']}Hz, "
                    f"Mid Gain {cur_summary['mid_gain_raw']}, Treble Gain {cur_summary['treble_gain_raw']}. "
                    "Bạn muốn tăng bass, làm ngọt giọng hát, hay bớt chói tép? (Lưu ý: nhập Gemini API Key hoặc dùng 🌐 Gemini Chrome để chat LLM đầy đủ)."
                ),
                "changes": {},
            }
        if is_status_q and not any(w in p_low for w in ("tăng", "giảm", "bớt", "đẩy", "chỉnh", "sửa", "bật", "tắt")):
            usb_txt = f"USB đã kết nối ({self.transport.endpoint.label})" if (self.transport.is_connected and self.transport.endpoint) else "Chưa kết nối USB thật"
            return {
                "ok": True,
                "source": "smart-dsp-ai",
                "reply": (
                    f"Trạng thái hiện tại: {usb_txt}. "
                    f"Bass {cur_summary['music_bass_db']}dB (HPF {cur_summary['bass_hpf_hz']}Hz), "
                    f"Mid {cur_summary['music_mid_db']}dB (Gain {cur_summary['mid_gain_raw']}), "
                    f"Treble {cur_summary['music_treble_db']}dB (Gain {cur_summary['treble_gain_raw']}/4600)."
                ),
                "changes": {},
            }

        # 2. Genre & Use-Case Complete Configuration Designer
        if any(w in p_low for w in ("bolero", "nhạc vàng", "trữ tình", "acoustic", "ballad")):
            changes = {
                "music_bass_db": 1.0, "music_mid_db": 2.0, "music_treble_db": 1.0,
                "bass_hpf_hz": 55, "bass_lpf_hz": 145, "bass_pregain_db": -3.5,
                "mid_hpf_hz": 145, "mid_gain_raw": 4750, "treble_hpf_hz": 9200, "treble_gain_raw": 4450,
                "mvb_classic_en": True, "mvb_classic_hz": 56, "mvb_classic_int": 20,
                "exc_en": True, "exc_hz": 4500, "exc_wet": 18, "drc_enabled": True,
            }
            return {
                "ok": True, "source": "dsp-expert-ai",
                "reply": (
                    "Cấu hình Bolero / Nhạc Vàng / Acoustic: Đẩy Mid Pioneer 6Ω (+2.0 dB, Gain 4750) cho giọng ca sĩ ấm ngọt và tách bạch; "
                    "Sub cắt gọn 55–145Hz (MVBass 20%) để tiếng bass tròn không lấn lời; Treble dịu ở 4450 + Exciter 18% nghe lâu không mệt."
                ),
                "changes": changes,
            }
        if any(w in p_low for w in ("remix", "vinahouse", "dj", "dance", "sôi động", "bar")):
            changes = {
                "music_bass_db": 3.5, "music_mid_db": 0.5, "music_treble_db": 2.0,
                "bass_hpf_hz": 60, "bass_lpf_hz": 155, "bass_pregain_db": -4.0,
                "mid_hpf_hz": 155, "mid_gain_raw": 4600, "treble_hpf_hz": 9500, "treble_gain_raw": 4550,
                "mvb_classic_en": True, "mvb_classic_hz": 60, "mvb_classic_int": 30,
                "exc_en": True, "exc_hz": 5000, "exc_wet": 26,
                "drc_enabled": True, "music_drc_dbfs": -2.5, "spk_drc_dbfs": -3.0,
            }
            return {
                "ok": True, "source": "dsp-expert-ai",
                "reply": (
                    "Cấu hình Remix / Vinahouse: Tăng lực kick Sub (+3.5 dB, MVBass 60Hz 30%) nhưng khóa HPF 60Hz chống dập màng 5\"; "
                    "Treble +2.0 dB + Exciter 26% (Gain 4550 an toàn) và siết DRC -2.5/-3.0 dBFS để đánh lớn không méo."
                ),
                "changes": changes,
            }
        if any(w in p_low for w in ("karaoke", "hát live", "micro", "mic")):
            changes = {
                "music_bass_db": 0.5, "music_mid_db": 2.5, "music_treble_db": 1.0,
                "bass_hpf_hz": 62, "bass_lpf_hz": 145, "mid_hpf_hz": 160, "mid_gain_raw": 4800,
                "treble_hpf_hz": 9500, "treble_gain_raw": 4400,
                "ng_enable": True, "ng_thresh_db": -60.0, "drc_enabled": True, "music_drc_dbfs": -3.0, "spk_drc_dbfs": -3.0,
            }
            return {
                "ok": True, "source": "dsp-expert-ai",
                "reply": (
                    "Cấu hình Karaoke: Mở rộng dải Mid (4800, +2.5 dB) giúp tiếng hát nhẹ hơi; cắt HPF Mid 160Hz & Sub 62Hz giảm ù mic; "
                    "bật Noise Gate -60dB chống xì nền và khóa Treble 4400 + DRC -3.0 dBFS chống hú rít cháy loa 5W."
                ),
                "changes": changes,
            }

        # 3. Technical Q&A without mutating DSP
        if any(w in p_low for w in ("4600", "cháy treble", "tụ 3uf", "5w")):
            return {
                "ok": True, "source": "dsp-expert-ai", "changes": {},
                "reply": "Treble Ford JX7T-18808-BA chỉ chịu công suất 4Ω 5W (ghép tụ 3µF cắt tự nhiên ~13.2kHz). Kết hợp DSP cắt HPF 9500Hz bậc 4 và khóa Gain <= 4600 giúp dải cao tơi sáng mà không quá nhiệt cuộn coil.",
            }
        if any(w in p_low for w in ("pha", "phase", "180")):
            return {
                "ok": True, "source": "dsp-expert-ai", "changes": {},
                "reply": "Đảo pha Sub 0° ↔ 180° (0x9A) giúp đồng bộ sóng âm tại điểm giao thoa 150Hz giữa Sub JBL 5\" và Mid Pioneer. Nếu nghe thử thấy tiếng bass dày và liền lạc hơn ở vị trí ngồi thì giữ pha đó.",
            }

        # 4. Explicit DSP tuning requests (match current prompt)
        if any(w in p_low for w in ("gốc", "ban đầu", "reset", "khôi phục")):
            changes.update(base_summary)
            notes.append("Khôi phục toàn bộ thông số về cấu hình gốc ban đầu.")
        if any(w in p_low for w in ("bass", "trầm", "sâu", "lực", "sub", "edm")):
            changes["music_bass_db"] = min(5.0, round(float(cur_summary["music_bass_db"]) + 1.5, 1))
            changes["mvb_classic_en"] = True
            changes["mvb_classic_hz"] = 58
            changes["mvb_classic_int"] = min(40, int(cur_summary["mvb_classic_int"]) + 8)
            changes["bass_hpf_hz"] = 56
            notes.append("Tăng lực Sub (+1.5 dB Music Bass, bật MVBass Classic 58Hz) nhưng giữ HPF 56Hz bảo vệ màng 5\".")
        if any(w in p_low for w in ("ù", "rền", "gọn", "5l", "boomy")):
            changes["bass_pregain_db"] = max(-6.0, round(float(cur_summary["bass_pregain_db"]) - 1.0, 1))
            changes["bass_hpf_hz"] = 62
            changes["bass_lpf_hz"] = 140
            notes.append("Siết gọn Sub thùng 5L (HPF 62Hz, LPF 140Hz, Pregain giảm 1dB) để hết ù rền.")
        if any(w in p_low for w in ("vocal", "hát", "giọng", "bolero", "trung", "mid", "ngọt")):
            changes["music_mid_db"] = min(4.5, round(float(cur_summary["music_mid_db"]) + 1.5, 1))
            changes["mid_gain_raw"] = min(5000, int(cur_summary["mid_gain_raw"]) + 150)
            notes.append("Đẩy dải Mid Pioneer 6Ω (+1.5 dB, Mid Gain +150) giúp giọng hát nổi và ngọt hơn.")
        if any(w in p_low for w in ("tép", "treble", "sáng", "tơi", "leng keng")) and not any(w in p_low for w in ("bớt", "giảm", "chói", "gắt")):
            changes["music_treble_db"] = min(4.0, round(float(cur_summary["music_treble_db"]) + 1.5, 1))
            changes["exc_en"] = True
            changes["exc_hz"] = 4800
            changes["exc_wet"] = 26
            changes["treble_gain_raw"] = min(TREBLE_SAFE_MAX_GAIN, int(cur_summary["treble_gain_raw"]))
            notes.append("Tăng độ tơi sáng bằng Harmonic Exciter (4.8kHz, 26%) và khóa Treble Gain <= 4600 bảo vệ loa 5W.")
        if any(w in p_low for w in ("chói", "gắt", "bớt tép", "giảm tép", "dịu")):
            changes["music_treble_db"] = max(-4.0, round(float(cur_summary["music_treble_db"]) - 1.5, 1))
            changes["treble_gain_raw"] = max(3600, min(TREBLE_SAFE_MAX_GAIN, int(cur_summary["treble_gain_raw"]) - 250))
            changes["exc_en"] = False
            notes.append("Giảm độ gắt dải cao (-1.5 dB Treble, tắt Exciter, hạ Treble Gain).")
        if any(w in p_low for w in ("xì", "ồn", "nhiễu", "hú", "lớn", "bảo vệ")):
            changes["ng_enable"] = True
            changes["ng_thresh_db"] = -64.0
            changes["drc_enabled"] = True
            changes["music_drc_dbfs"] = -2.5
            changes["spk_drc_dbfs"] = -3.0
            notes.append("Bật Noise Gate (-64 dB) triệt xì nền & siết DRC (-2.5 / -3.0 dBFS) chống vỡ tiếng.")

        if any(w in p_low for w in ("hay hơn", "tư vấn", "nên chỉnh", "cách chỉnh", "cấu hình thế nào", "gợi ý")):
            changes = {
                "bass_hpf_hz": 58,
                "bass_lpf_hz": 150,
                "bass_pregain_db": -3.5,
                "mid_hpf_hz": 150,
                "mid_gain_raw": 4650,
                "treble_hpf_hz": 9500,
                "treble_gain_raw": 4550,
                "mvb_classic_en": True,
                "mvb_classic_hz": 58,
                "mvb_classic_int": 24,
                "exc_en": True,
                "exc_hz": 4800,
                "exc_wet": 22,
                "ng_enable": True,
                "ng_thresh_db": -66.0,
                "drc_enabled": True,
                "music_drc_dbfs": -2.0,
                "spk_drc_dbfs": -3.0,
            }
            return {
                "ok": True,
                "source": "smart-dsp-ai",
                "reply": (
                    "Để bộ loa 3-Way (Sub JBL 5\" 5L + Mid Pioneer 6Ω + Treble Ford 4Ω 5W) tiếng hay, sạch và có lực hơn: "
                    "1) Sub cắt HPF 58Hz / LPF 150Hz + bật MVBass Classic 58Hz (24%) để bass sâu mà không ù thùng 5L; "
                    "2) Mid Gain 4650 để giọng hát nổi ngọt; "
                    "3) Treble HPF 9500Hz + Exciter 4.8kHz (22%) và giữ Treble Gain <= 4550 cho tơi sáng an toàn; "
                    "4) Bật Noise Gate -66dB và DRC -2/-3 dBFS chống vỡ tiếng."
                ),
                "changes": changes,
            }

        if not notes:
            return {
                "ok": True,
                "source": "smart-dsp-ai",
                "reply": (
                    f"Mình đã nhận câu hỏi: \"{prompt}\". Bạn có thể hỏi cụ thể hơn (VD: tăng bass, giảm ù 5L, giọng hát ngọt, "
                    "bớt chói tép, chống xì nền, hoặc 'cấu hình thế nào để hay hơn') — hoặc nhập Gemini API Key / dùng 🌐 Gemini Chrome để trò chuyện tự do!"
                ),
                "changes": {},
            }

        return {"ok": True, "source": "smart-dsp-ai", "reply": " ".join(notes), "changes": changes}


def _make_handler(ctrl: AnSoundWebController):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def _send_json(self, obj, code=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict:
            n = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(n) if n > 0 else b"{}"
            return json.loads(raw.decode("utf-8"))

        def do_GET(self):
            if self.path == "/" or self.path == "/index.html":
                ui_path = os.path.join(ctrl.work_dir, "acp_pro_ui.html")
                with open(ui_path, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif self.path == "/api/state":
                self._send_json(ctrl.to_dict())
            elif self.path == "/api/usb/scan":
                ctrl.endpoints = scan_windows_usb_endpoints()
                self._send_json({"endpoints": [{"label": e.label, "kind": e.kind} for e in ctrl.endpoints]})
            elif self.path == "/api/logs":
                self._send_json({"logs": ctrl.logs})
            elif self.path == "/api/gemini_chrome_status":
                chrome_running = False
                try:
                    out = subprocess.check_output(
                        ["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
                        creationflags=0x08000000,
                        text=True,
                        errors="ignore",
                    )
                    chrome_running = "chrome.exe" in out.lower()
                except Exception:
                    chrome_running = False
                gemini_reachable = False
                try:
                    req = urllib.request.Request("https://gemini.google.com/app", method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        gemini_reachable = resp.status in (200, 301, 302)
                except Exception:
                    gemini_reachable = False
                ok = chrome_running and gemini_reachable
                self._send_json({
                    "ok": ok,
                    "chrome_running": chrome_running,
                    "gemini_reachable": gemini_reachable,
                    "message": "Neon Connected: Chrome & Gemini sẵn sàng." if ok else f"Chrome={'ON' if chrome_running else 'OFF'}, Gemini={'OK' if gemini_reachable else 'OFF'}",
                })
            elif self.path == "/api/export/ini":
                prof = ctrl.base_profile if ctrl.base_profile is not None else AcpProfile()
                ctrl.state.apply_to_profile(prof)
                data = serialize_ini(prof).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="dsp_3way_acp_pro.ini"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif self.path == "/api/export/c":
                data = export_c_source("dsp_3way_acp_pro", ctrl.state.build_packets()).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="dsp_3way_acp_pro.c"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_error(404)

        def do_POST(self):
            body = self._read_json()
            if self.path == "/api/update":
                ctrl.update_from_dict(body)
                self._send_json({"ok": True})
            elif self.path == "/api/push_all":
                cnt = ctrl.push_all()
                conn = ctrl.transport.is_connected
                lbl = ctrl.transport.endpoint.label if (conn and ctrl.transport.endpoint) else ""
                msg = f"Đã đẩy {cnt} khối lên USB thật ({lbl})" if conn else f"Chưa kết nối USB thật — đã mô phỏng {cnt} khối trong log TX."
                self._send_json({"ok": True, "count": cnt, "connected": conn, "message": msg})
            elif self.path == "/api/push_channel":
                eid = int(body.get("effect_id", EFFECT_BASS_EQ))
                pre = ctrl.state.bass_pregain_db if eid == EFFECT_BASS_EQ else (-2.0 if eid in (EFFECT_MID_EQ, EFFECT_TREBLE_EQ) else 0.0)
                ctrl.transport.send_packet(build_eq10_packet(eid, True, pre, ctrl.state.peq_banks[eid]))
                self._send_json({"ok": True})
            elif self.path == "/api/preset":
                self._send_json(ctrl.load_preset(int(body.get("index", 0))))
            elif self.path == "/api/autotune":
                self._send_json(ctrl.run_autotune(str(body.get("mode", "hifi"))))
            elif self.path == "/api/ai/chat":
                res = ctrl.ai_chat(
                    str(body.get("prompt", "")),
                    body.get("history", []),
                    body.get("baseline"),
                    str(body.get("api_key", "")),
                )
                self._send_json(res)
            elif self.path == "/api/ai/test":
                key = str(body.get("api_key", "")).strip()
                if not key:
                    self._send_json({"ok": False, "message": "Chưa nhập Gemini API Key (đang dùng Smart DSP AI nội bộ hoặc Gemini Chrome)."})
                elif not (key.startswith("AIza") or key.startswith("AQ.")) or any(c.isspace() for c in key):
                    self._send_json({
                        "ok": False,
                        "invalid_key": True,
                        "message": "Ô API Key đang dán nhầm văn bản/prompt (Key Gemini thật bắt đầu bằng 'AIza...' hoặc 'AQ....' và không có dấu cách). Hãy xóa trắng hoặc dán đúng mã Key!",
                    })
                else:
                    last_err = ""
                    for model_name in ctrl._resolve_gemini_models(key):
                        try:
                            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={key}"
                            req = urllib.request.Request(
                                url,
                                data=json.dumps({"contents": [{"parts": [{"text": "ping"}]}]}).encode("utf-8"),
                                headers={"Content-Type": "application/json"},
                                method="POST",
                            )
                            with urllib.request.urlopen(req, timeout=15) as resp:
                                _ = resp.read()
                            ctrl._log("AI", f"Kiểm tra kết nối Gemini API ({model_name}): THÀNH CÔNG.")
                            self._send_json({"ok": True, "message": f"Kết nối Gemini API thành công ({model_name})."})
                            last_err = ""
                            break
                        except urllib.error.HTTPError as he:
                            detail = ""
                            try:
                                detail = json.loads(he.read().decode("utf-8")).get("error", {}).get("message", "")
                            except Exception:
                                pass
                            last_err = f"HTTP {he.code}: {detail or he.reason}"
                        except Exception as exc:
                            last_err = str(exc)
                    if last_err:
                        ctrl._log("AI", f"Kiểm tra kết nối Gemini API thất bại: {last_err}")
                        self._send_json({"ok": False, "message": f"Kết nối Gemini API thất bại ({last_err})."})
            elif self.path == "/api/open_gemini_chrome":
                url = str(body.get("url") or "https://gemini.google.com/app")
                chrome_paths = [
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
                ]
                launched = False
                for cp in chrome_paths:
                    if cp and os.path.exists(cp):
                        subprocess.Popen([cp, url])
                        launched = True
                        break
                self._send_json({"ok": launched, "chrome": launched})
            elif self.path == "/api/usb/connect":
                idx = int(body.get("index", -1))
                ok = 0 <= idx < len(ctrl.endpoints) and ctrl.transport.connect(ctrl.endpoints[idx])
                lbl = ctrl.endpoints[idx].label if (ok and 0 <= idx < len(ctrl.endpoints)) else ""
                msg = f"Kết nối USB thành công: {lbl}" if ok else "Kết nối thất bại: Không mở được cổng USB/COM (kiểm tra pin loa đã bật chưa hoặc đóng ACPWorkbench)."
                self._send_json({"ok": ok, "connected": ok, "label": lbl, "message": msg})
            elif self.path == "/api/usb/disconnect":
                ctrl.transport.disconnect()
                self._send_json({"ok": True})
            elif self.path == "/api/write_acp_ini":
                prof = ctrl.base_profile if ctrl.base_profile is not None else AcpProfile()
                ctrl.state.apply_to_profile(prof)
                target = os.path.join(ctrl.work_dir, "ACPWorkbench.ini")
                with open(target, "w", encoding="utf-8") as f:
                    f.write(serialize_ini(prof))
                self._send_json({"ok": True, "message": f"Đã ghi đồng bộ vào {target}"})
            elif self.path == "/api/sync_acp":
                prof = ctrl.base_profile if ctrl.base_profile is not None else AcpProfile()
                ctrl.state.apply_to_profile(prof)
                target = os.path.join(ctrl.work_dir, "ACPWorkbench.ini")
                with open(target, "w", encoding="utf-8") as f:
                    f.write(serialize_ini(prof))
                exe = os.path.join(ctrl.work_dir, "ACPWorkbench_V2.44.2.exe")
                if os.path.exists(exe):
                    if ctrl.transport.is_connected:
                        ctrl.transport.disconnect()
                    subprocess.Popen([exe], cwd=ctrl.work_dir)
                    self._send_json({"ok": True, "message": ""})
                else:
                    self._send_json({"ok": True, "message": f"Đã ghi {target} (chưa thấy ACPWorkbench_V2.44.2.exe)"})
            elif self.path == "/api/load_ini_dialog":
                r = tk.Tk()
                r.withdraw()
                r.attributes("-topmost", True)
                path = filedialog.askopenfilename(initialdir=ctrl.work_dir, title="Chọn file .INI", filetypes=[("ACPWorkbench INI", "*.ini")])
                r.destroy()
                if path:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        ctrl.base_profile = parse_ini(f.read())
                    ctrl._extract_profile_into_state(ctrl.base_profile)
                    self._send_json(ctrl.to_dict())
                else:
                    self._send_json({})
            else:
                self.send_error(404)

    return Handler


def _launch_desktop_window(url: str) -> Optional[subprocess.Popen]:
    profile_dir = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AnSoundAcpProChromeProfile")
    os.makedirs(profile_dir, exist_ok=True)
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
    ]
    for exe in candidates:
        if exe and os.path.exists(exe):
            return subprocess.Popen([
                exe,
                f"--app={url}",
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--window-size=1360,860",
            ])
    raise RuntimeError("Không tìm thấy Google Chrome (chrome.exe) trên máy.")


def main() -> None:
    ctrl = AnSoundWebController()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(ctrl))
    port = srv.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    print(f"An Sound ACP Pro PC running at {url}")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    t0 = time.time()
    proc = _launch_desktop_window(url)
    try:
        if proc is not None:
            proc.wait()
            if time.time() - t0 < 3.0:
                print(f"Browser handed off window; keeping server alive at {url} (Ctrl+C to stop)")
                t.join()
        else:
            t.join()
    except KeyboardInterrupt:
        pass
    finally:
        ctrl.transport.disconnect()
        srv.shutdown()


if __name__ == "__main__":
    main()
