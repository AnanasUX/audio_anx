# -*- coding: utf-8 -*-
import os
import unittest

import An_Sound_ACP_Pro_PC as acp


class TestAnSoundAcpProPc(unittest.TestCase):
    def test_bass_phase_frame_exact_bytes(self):
        pkt0 = acp.build_bass_phase_packet(False, False)
        self.assertEqual(
            pkt0.to_bytes(),
            bytes([0xA5, 0x5A, 0x9A, 0x05, 0xFF, 0x00, 0x00, 0x00, 0x00, 0x16]),
        )
        pkt180 = acp.build_bass_phase_packet(True, True)
        parsed = acp.MvsiliconPacket.parse(pkt180.to_bytes())
        self.assertEqual(parsed.effect_id, 0x9A)
        self.assertEqual(acp.read_u16_le(parsed.payload, 0), 1)
        self.assertEqual(acp.read_u16_le(parsed.payload, 2), 1)

    def test_speaker_gain_little_endian(self):
        pkt = acp.build_speaker_gain_packet(acp.EFFECT_TREBLE_GAIN, True, False, 4350)
        raw = pkt.to_bytes()
        self.assertEqual(len(raw), 12)
        self.assertEqual(raw[3], 0x07)
        self.assertEqual(raw[9], 0xFE)
        self.assertEqual(raw[10], 0x10)
        self.assertEqual(raw[11], 0x16)

    def test_music_eq_and_drc_lengths(self):
        eq = acp.build_music_bass_mid_treble(2.0, 0.5, -1.5)
        raw_eq = eq.to_bytes()
        self.assertEqual(raw_eq[2], 0x91)
        self.assertEqual(raw_eq[3], 0x6B)
        self.assertEqual(len(raw_eq), 112)

        drc = acp.build_drc_packet(acp.EFFECT_MUSIC_DRC, True, 2, 4, 300, 2000, -2.5, 50, 2, 80)
        raw_drc = drc.to_bytes()
        self.assertEqual(raw_drc[3], 0x37)
        self.assertEqual(len(raw_drc), 60)
        self.assertEqual(acp.read_i16_le(raw_drc, 19), -250)

    def test_parse_real_ini_and_apply_preset(self):
        ini_path = os.path.join(os.path.dirname(__file__), "dsp_3way_spec_matched.ini")
        self.assertTrue(os.path.exists(ini_path))
        with open(ini_path, "r", encoding="utf-8", errors="ignore") as f:
            profile = acp.parse_ini(f.read())
        self.assertEqual(profile.acp_version, "2.44.2")
        self.assertIsNotNone(profile.find_by_effect_id(0x98))
        self.assertIsNotNone(profile.find_by_effect_id(0x99))

        presets = acp.get_builtin_presets()
        self.assertGreaterEqual(len(presets), 4)
        spec = presets[0]
        self.assertLessEqual(spec.treble_gain_raw, acp.TREBLE_SAFE_MAX_GAIN)
        spec.treble_gain_raw = 4450
        spec.apply_to_profile(profile)
        out_text = acp.serialize_ini(profile)
        reparsed = acp.parse_ini(out_text)
        self.assertEqual(reparsed.find_by_effect_id(0x98).get_int("gain"), 4450)

    def test_export_c_source_and_parse_stream(self):
        presets = acp.get_builtin_presets()
        packets = presets[0].build_packets()
        self.assertEqual(len(packets), 21)
        c_code = acp.export_c_source("dsp_3way_acp_pro", packets)
        self.assertIn("//ACPWorkbench Version: 2.44.2", c_code)
        self.assertIn("const unsigned char dsp_3way_acp_pro[", c_code)
        self.assertIn("0x16 /*sync tail*/", c_code)

        stream = b"\x00\x11" + packets[0].to_bytes() + b"\x99" + packets[5].to_bytes() + b"\x77"
        found = acp.MvsiliconPacket.parse_stream(stream)
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0].effect_id, packets[0].effect_id)
        self.assertEqual(found[1].effect_id, packets[5].effect_id)

    def test_extended_dsp_blocks_exact_framing(self):
        ng = acp.build_noise_gate_packet(True, -65.0, 1, 5, 160).to_bytes()
        self.assertEqual(ng[2], 0x85)
        self.assertEqual(ng[3], 0x0B)
        self.assertEqual(acp.read_i16_le(ng, 7), -6500)

        mvbc = acp.build_mvbass_classic_packet(True, 58, 28).to_bytes()
        self.assertEqual(mvbc, bytes([0xA5, 0x5A, 0x87, 0x07, 0xFF, 0x01, 0x00, 0x3A, 0x00, 0x1C, 0x00, 0x16]))

        exc = acp.build_exciter_packet(True, 1100, 100, 35).to_bytes()
        self.assertEqual(exc, bytes([0xA5, 0x5A, 0x89, 0x09, 0xFF, 0x01, 0x00, 0x4C, 0x04, 0x64, 0x00, 0x23, 0x00, 0x16]))

        dly = acp.build_pcm_delay_packet(acp.EFFECT_BASS_DELAY, False, 50, 50, False).to_bytes()
        self.assertEqual(dly, bytes([0xA5, 0x5A, 0x9D, 0x09, 0xFF, 0x00, 0x00, 0x32, 0x00, 0x32, 0x00, 0x00, 0x00, 0x16]))

    def test_windows_usb_scanner_runs_safely(self):
        endpoints = acp.scan_windows_usb_endpoints()
        self.assertIsInstance(endpoints, list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
