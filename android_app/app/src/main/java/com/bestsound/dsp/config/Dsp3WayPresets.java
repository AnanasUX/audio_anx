package com.bestsound.dsp.config;

import com.bestsound.dsp.usb.MvsiliconPacket;
import com.bestsound.dsp.usb.MvsiliconPacket.EqBand;

import java.util.ArrayList;
import java.util.List;

/**
 * Hardware-matched 3-Way Presets for Quoc Doan Audio 70W x 2 (MVSilicon BP1048B2 / FW 0.3.4):
 * - Sub 5" JBL Boombox 4 in 5L enclosure (4 ohm)
 * - Mid Pioneer S-EV61V (6 ohm)
 * - Treble Ford JX7T-18808-BA (4 ohm 5W with 3uF cap)
 */
public final class Dsp3WayPresets {

    public static final String PRESET_3WAY_SPEC_MATCHED = "3-Way Spec Matched";
    public static final String PRESET_FACTORY_DYNAMIC_EQ = "Factory Style (DynamicEQ)";

    // Safety ceiling for Ford 4-ohm 5W Tweeter (3uF cap)
    public static final int TREBLE_SAFE_MAX_GAIN = 4600;

    public static final class PresetState {
        public final String name;
        public final double musicBassDb;
        public final double musicMidDb;
        public final double musicTrebleDb;
        public final int midGainRaw;
        public final int trebleGainRaw;
        public final boolean bassPhase180;
        public final boolean drcEnabled;
        public final double drcThresholdDbfs;
        public final List<MvsiliconPacket> packets;

        public PresetState(String name, double musicBassDb, double musicMidDb, double musicTrebleDb,
                           int midGainRaw, int trebleGainRaw, boolean bassPhase180,
                           boolean drcEnabled, double drcThresholdDbfs, List<MvsiliconPacket> packets) {
            this.name = name;
            this.musicBassDb = musicBassDb;
            this.musicMidDb = musicMidDb;
            this.musicTrebleDb = musicTrebleDb;
            this.midGainRaw = midGainRaw;
            this.trebleGainRaw = trebleGainRaw;
            this.bassPhase180 = bassPhase180;
            this.drcEnabled = drcEnabled;
            this.drcThresholdDbfs = drcThresholdDbfs;
            this.packets = packets;
        }
    }

    private Dsp3WayPresets() {}

    public static PresetState buildSpecMatchedPreset() {
        List<MvsiliconPacket> pkts = new ArrayList<>();

        // 0x91: Music:Bass-Mid-Treb (flat neutral reference)
        pkts.add(MvsiliconPacket.buildMusicBassMidTreble(0.0, 0.0, 0.0));

        // 0x95: Bass SPK:Bass EQ (Sub 5" JBL Boombox 4 in 5L box)
        // HPF 60Hz 4th-order (two cascaded 2nd-order Butterworth HPFs), LPF 150Hz 4th-order,
        // PEQ boost 62Hz/85Hz + 5L box resonance anti-boom cut @ 165Hz (-3.5 dB)
        List<EqBand> bassBands = new ArrayList<>();
        bassBands.add(new EqBand(true, MvsiliconPacket.FILTER_HPF, 60, 0.707, 0.0));
        bassBands.add(new EqBand(true, MvsiliconPacket.FILTER_HPF, 60, 0.707, 0.0));
        bassBands.add(new EqBand(true, MvsiliconPacket.FILTER_LPF, 150, 0.707, 0.0));
        bassBands.add(new EqBand(true, MvsiliconPacket.FILTER_LPF, 150, 0.707, 0.0));
        bassBands.add(new EqBand(true, MvsiliconPacket.FILTER_PEAKING, 62, 0.90, 3.5));
        bassBands.add(new EqBand(true, MvsiliconPacket.FILTER_PEAKING, 85, 1.10, 4.0));
        bassBands.add(new EqBand(true, MvsiliconPacket.FILTER_PEAKING, 165, 2.40, -3.5));
        pkts.add(MvsiliconPacket.buildEq10Packet(MvsiliconPacket.EFFECT_BASS_EQ, true, 0.0, bassBands));

        // 0x97: Mid SPK:Mid EQ (Pioneer S-EV61V 6-ohm)
        List<EqBand> midBands = new ArrayList<>();
        midBands.add(new EqBand(true, MvsiliconPacket.FILTER_HPF, 175, 0.707, 0.0));
        midBands.add(new EqBand(true, MvsiliconPacket.FILTER_LPF, 8200, 0.707, 0.0));
        midBands.add(new EqBand(true, MvsiliconPacket.FILTER_PEAKING, 500, 1.20, 1.5));
        midBands.add(new EqBand(true, MvsiliconPacket.FILTER_PEAKING, 2500, 1.60, 2.0));
        pkts.add(MvsiliconPacket.buildEq10Packet(MvsiliconPacket.EFFECT_MID_EQ, true, 0.0, midBands));

        // 0x99: Mid Gain (~4600 for 6-ohm Pioneer)
        pkts.add(MvsiliconPacket.buildSpeakerGainPacket(MvsiliconPacket.EFFECT_MID_GAIN, true, false, 4600));

        // 0x96: Treble SPK:Treble EQ (Ford JX7T-18808-BA 4-ohm 5W w/ 3uF cap -> HPF 8800Hz)
        List<EqBand> trebBands = new ArrayList<>();
        trebBands.add(new EqBand(true, MvsiliconPacket.FILTER_HPF, 8800, 0.707, 0.0));
        trebBands.add(new EqBand(true, MvsiliconPacket.FILTER_HPF, 8800, 0.707, 0.0));
        trebBands.add(new EqBand(true, MvsiliconPacket.FILTER_HIGH_SHELF, 12000, 0.80, 1.5));
        pkts.add(MvsiliconPacket.buildEq10Packet(MvsiliconPacket.EFFECT_TREBLE_EQ, true, 0.0, trebBands));

        // 0x98: Treble Gain (Safe ~4350 for 5W tweeter)
        pkts.add(MvsiliconPacket.buildSpeakerGainPacket(MvsiliconPacket.EFFECT_TREBLE_GAIN, true, false, 4350));

        // 0x9A: Bass Phase (0 deg)
        pkts.add(MvsiliconPacket.buildBassPhasePacket(true, false));

        // 0x9B (Bass DRC), 0x9C (Mid DRC), 0x93 (Music DRC) -> -2.5 dBFS anti-clip
        pkts.add(MvsiliconPacket.buildDrcPacket(MvsiliconPacket.EFFECT_BASS_DRC, true, 0, 4, 137, 20000, -2.5, 50, 2, 80));
        pkts.add(MvsiliconPacket.buildDrcPacket(MvsiliconPacket.EFFECT_MID_DRC, true, 0, 1, 319, 2000, -2.5, 50, 2, 80));
        pkts.add(MvsiliconPacket.buildDrcPacket(MvsiliconPacket.EFFECT_MUSIC_DRC, true, 2, 4, 300, 2000, -2.5, 50, 2, 60));

        return new PresetState(PRESET_3WAY_SPEC_MATCHED, 0.0, 0.0, 0.0, 4600, 4350, false, true, -2.5, pkts);
    }

    public static PresetState buildFactoryDynamicEqPreset() {
        List<MvsiliconPacket> pkts = new ArrayList<>();

        // 0x91: DynamicEQ warm punchy boost
        pkts.add(MvsiliconPacket.buildMusicBassMidTreble(2.0, 0.5, 1.5));

        // 0x95: Bass EQ
        List<EqBand> bassBands = new ArrayList<>();
        bassBands.add(new EqBand(true, MvsiliconPacket.FILTER_HPF, 55, 0.707, 0.0));
        bassBands.add(new EqBand(true, MvsiliconPacket.FILTER_HPF, 55, 0.707, 0.0));
        bassBands.add(new EqBand(true, MvsiliconPacket.FILTER_LPF, 160, 0.707, 0.0));
        bassBands.add(new EqBand(true, MvsiliconPacket.FILTER_LPF, 160, 0.707, 0.0));
        bassBands.add(new EqBand(true, MvsiliconPacket.FILTER_PEAKING, 65, 0.85, 4.5));
        bassBands.add(new EqBand(true, MvsiliconPacket.FILTER_PEAKING, 165, 2.20, -2.5));
        pkts.add(MvsiliconPacket.buildEq10Packet(MvsiliconPacket.EFFECT_BASS_EQ, true, 0.0, bassBands));

        // 0x97 & 0x99: Mid
        List<EqBand> midBands = new ArrayList<>();
        midBands.add(new EqBand(true, MvsiliconPacket.FILTER_HPF, 165, 0.707, 0.0));
        midBands.add(new EqBand(true, MvsiliconPacket.FILTER_LPF, 8500, 0.707, 0.0));
        midBands.add(new EqBand(true, MvsiliconPacket.FILTER_PEAKING, 1000, 1.20, 2.0));
        pkts.add(MvsiliconPacket.buildEq10Packet(MvsiliconPacket.EFFECT_MID_EQ, true, 0.0, midBands));
        pkts.add(MvsiliconPacket.buildSpeakerGainPacket(MvsiliconPacket.EFFECT_MID_GAIN, true, false, 4750));

        // 0x96 & 0x98: Treble (9000Hz HPF, safe 4500)
        List<EqBand> trebBands = new ArrayList<>();
        trebBands.add(new EqBand(true, MvsiliconPacket.FILTER_HPF, 9000, 0.707, 0.0));
        trebBands.add(new EqBand(true, MvsiliconPacket.FILTER_HPF, 9000, 0.707, 0.0));
        trebBands.add(new EqBand(true, MvsiliconPacket.FILTER_HIGH_SHELF, 11000, 0.75, 2.0));
        pkts.add(MvsiliconPacket.buildEq10Packet(MvsiliconPacket.EFFECT_TREBLE_EQ, true, 0.0, trebBands));
        pkts.add(MvsiliconPacket.buildSpeakerGainPacket(MvsiliconPacket.EFFECT_TREBLE_GAIN, true, false, 4500));

        // 0x9A: Phase 0 deg
        pkts.add(MvsiliconPacket.buildBassPhasePacket(true, false));

        // DRC @ -2.0 dBFS
        pkts.add(MvsiliconPacket.buildDrcPacket(MvsiliconPacket.EFFECT_BASS_DRC, true, 0, 4, 137, 20000, -2.0, 50, 2, 60));
        pkts.add(MvsiliconPacket.buildDrcPacket(MvsiliconPacket.EFFECT_MID_DRC, true, 0, 1, 319, 2000, -2.0, 50, 2, 60));
        pkts.add(MvsiliconPacket.buildDrcPacket(MvsiliconPacket.EFFECT_MUSIC_DRC, true, 2, 4, 300, 2000, -2.0, 50, 2, 60));

        return new PresetState(PRESET_FACTORY_DYNAMIC_EQ, 2.0, 0.5, 1.5, 4750, 4500, false, true, -2.0, pkts);
    }

    public static AcpConfigParser.AcpProfile toIniProfile(PresetState state) {
        AcpConfigParser.AcpProfile profile = new AcpConfigParser.AcpProfile();

        AcpConfigParser.AcpSection fw = new AcpConfigParser.AcpSection("0x00-Firmware_Version", 0x00);
        fw.put("firmware_type", "48");
        fw.put("firmware_version", "0.3.4");
        fw.put("effect_version", "2.45.5");
        profile.addSection(fw);

        AcpConfigParser.AcpSection tone = new AcpConfigParser.AcpSection("0x91-Music_Bass_Mid_Treb", 0x91);
        tone.put("enable", "1");
        tone.put("bass_gain", String.valueOf(MvsiliconPacket.dbToEqFixed(state.musicBassDb)));
        tone.put("mid_gain", String.valueOf(MvsiliconPacket.dbToEqFixed(state.musicMidDb)));
        tone.put("treble_gain", String.valueOf(MvsiliconPacket.dbToEqFixed(state.musicTrebleDb)));
        profile.addSection(tone);

        AcpConfigParser.AcpSection tg = new AcpConfigParser.AcpSection("0x98-Treble_SPK_Treble_Gain", 0x98);
        tg.put("enable", "1");
        tg.put("mute", "0");
        tg.put("gain", String.valueOf(state.trebleGainRaw));
        profile.addSection(tg);

        AcpConfigParser.AcpSection mg = new AcpConfigParser.AcpSection("0x99-Mid_SPK_Mid_Gain", 0x99);
        mg.put("enable", "1");
        mg.put("mute", "0");
        mg.put("gain", String.valueOf(state.midGainRaw));
        profile.addSection(mg);

        AcpConfigParser.AcpSection ph = new AcpConfigParser.AcpSection("0x9A-Bass_SPK_Bass_Phase", 0x9A);
        ph.put("enable", "1");
        ph.put("phase_difference", state.bassPhase180 ? "1" : "0");
        profile.addSection(ph);

        AcpConfigParser.AcpSection drc = new AcpConfigParser.AcpSection("0x93-Music_DRC", 0x93);
        drc.put("enable", state.drcEnabled ? "1" : "0");
        drc.put("threshold", String.valueOf(MvsiliconPacket.dbfsToDrcThreshold(state.drcThresholdDbfs)));
        profile.addSection(drc);

        return profile;
    }
}
