package com.bestsound.dsp.usb;

import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;

/**
 * MVSilicon ACPWorkbench (v2.44.2 / Firmware 0.3.4) Frame Builder & Parser.
 * Frame format:
 *   [0xA5, 0x5A] + [Effect_ID] + [Length] + [Param_Mask = 0xFF] + [Payload LE] + [0x16]
 * Where Length = 1 (Param_Mask) + Payload.length.
 */
public final class MvsiliconPacket {

    public static final byte SYNC_HEAD_0 = (byte) 0xA5;
    public static final byte SYNC_HEAD_1 = (byte) 0x5A;
    public static final byte SYNC_TAIL = (byte) 0x16;
    public static final byte ALL_PARAM_MASK = (byte) 0xFF;

    // Target Effect IDs for 3-Way Quoc Doan Audio 70W x 2
    public static final int EFFECT_MUSIC_BASS_MID_TREB = 0x91;
    public static final int EFFECT_MUSIC_DRC           = 0x93;
    public static final int EFFECT_BASS_EQ             = 0x95;
    public static final int EFFECT_TREBLE_EQ           = 0x96;
    public static final int EFFECT_MID_EQ              = 0x97;
    public static final int EFFECT_TREBLE_GAIN         = 0x98;
    public static final int EFFECT_MID_GAIN            = 0x99;
    public static final int EFFECT_BASS_PHASE          = 0x9A;
    public static final int EFFECT_BASS_DRC            = 0x9B;
    public static final int EFFECT_MID_DRC             = 0x9C;

    // EQ Filter Types (ACPWorkbench)
    public static final int FILTER_PEAKING   = 0;
    public static final int FILTER_LOW_SHELF = 1;
    public static final int FILTER_HIGH_SHELF= 2;
    public static final int FILTER_LPF       = 3;
    public static final int FILTER_HPF       = 4;

    private final int effectId;
    private final int paramMask;
    private final byte[] payload;

    public MvsiliconPacket(int effectId, int paramMask, byte[] payload) {
        this.effectId = effectId & 0xFF;
        this.paramMask = paramMask & 0xFF;
        this.payload = payload != null ? payload.clone() : new byte[0];
    }

    public int getEffectId() { return effectId; }
    public int getParamMask() { return paramMask; }
    public byte[] getPayload() { return payload.clone(); }

    /**
     * Serializes the packet into wire bytes:
     * [0xA5, 0x5A, Effect_ID, Length, Param_Mask, ...Payload(LE), 0x16]
     */
    public byte[] toBytes() {
        int lengthField = 1 + payload.length;
        byte[] frame = new byte[6 + payload.length];
        frame[0] = SYNC_HEAD_0;
        frame[1] = SYNC_HEAD_1;
        frame[2] = (byte) (effectId & 0xFF);
        frame[3] = (byte) (lengthField & 0xFF);
        frame[4] = (byte) (paramMask & 0xFF);
        System.arraycopy(payload, 0, frame, 5, payload.length);
        frame[frame.length - 1] = SYNC_TAIL;
        return frame;
    }

    /**
     * Parses a raw frame back into an MvsiliconPacket. Validates sync bytes and length.
     */
    public static MvsiliconPacket parse(byte[] raw) {
        if (raw == null || raw.length < 6) {
            throw new IllegalArgumentException("Frame too short");
        }
        if (raw[0] != SYNC_HEAD_0 || raw[1] != SYNC_HEAD_1) {
            throw new IllegalArgumentException("Invalid sync head");
        }
        if (raw[raw.length - 1] != SYNC_TAIL) {
            throw new IllegalArgumentException("Invalid sync tail");
        }
        int effectId = raw[2] & 0xFF;
        int lengthField = raw[3] & 0xFF;
        if (lengthField + 5 != raw.length) {
            throw new IllegalArgumentException("Length mismatch: field=" + lengthField + ", total=" + raw.length);
        }
        int paramMask = raw[4] & 0xFF;
        byte[] payload = Arrays.copyOfRange(raw, 5, raw.length - 1);
        return new MvsiliconPacket(effectId, paramMask, payload);
    }

    /**
     * Extracts all valid frames from a noisy/chunked RX byte stream.
     */
    public static List<MvsiliconPacket> parseStream(byte[] stream) {
        List<MvsiliconPacket> list = new ArrayList<>();
        if (stream == null) return list;
        int i = 0;
        while (i <= stream.length - 6) {
            if (stream[i] == SYNC_HEAD_0 && stream[i + 1] == SYNC_HEAD_1) {
                int len = stream[i + 3] & 0xFF;
                int totalLen = len + 5;
                if (len >= 1 && i + totalLen <= stream.length && stream[i + totalLen - 1] == SYNC_TAIL) {
                    byte[] slice = Arrays.copyOfRange(stream, i, i + totalLen);
                    list.add(parse(slice));
                    i += totalLen;
                    continue;
                }
            }
            i++;
        }
        return list;
    }

    // --- Little-Endian & Fixed-Point Conversion Helpers ---

    public static void writeU16LE(ByteArrayOutputStream out, int value) {
        out.write(value & 0xFF);
        out.write((value >> 8) & 0xFF);
    }

    public static void writeI16LE(ByteArrayOutputStream out, int value) {
        writeU16LE(out, value & 0xFFFF);
    }

    public static void writeU32LE(ByteArrayOutputStream out, long value) {
        out.write((int) (value & 0xFF));
        out.write((int) ((value >> 8) & 0xFF));
        out.write((int) ((value >> 16) & 0xFF));
        out.write((int) ((value >> 24) & 0xFF));
    }

    public static int readI16LE(byte[] buf, int offset) {
        int lo = buf[offset] & 0xFF;
        int hi = buf[offset + 1]; // signed
        return (hi << 8) | lo;
    }

    public static int readU16LE(byte[] buf, int offset) {
        return ((buf[offset + 1] & 0xFF) << 8) | (buf[offset] & 0xFF);
    }

    /** EQ gain in ACPWorkbench uses Q8 fixed-point: 1.0 dB = 256 (0x0100) */
    public static int dbToEqFixed(double db) {
        return (int) Math.round(db * 256.0);
    }

    public static double eqFixedToDb(int fixed) {
        return fixed / 256.0;
    }

    /** Q factor in ACPWorkbench uses Q10 fixed-point: Q=1.0 -> 1024, Butterworth 0.707 -> 724 */
    public static int qToFixed(double q) {
        return (int) Math.round(q * 1024.0);
    }

    /** DRC threshold in ACPWorkbench uses 0.01 dBFS units: -2.0 dBFS -> -200 */
    public static int dbfsToDrcThreshold(double dbfs) {
        return (int) Math.round(dbfs * 100.0);
    }

    // --- High-Level Packet Builders for Target Effect IDs ---

    public static final class EqBand {
        public final boolean enable;
        public final int type;
        public final int f0Hz;
        public final double q;
        public final double gainDb;

        public EqBand(boolean enable, int type, int f0Hz, double q, double gainDb) {
            this.enable = enable;
            this.type = type;
            this.f0Hz = f0Hz;
            this.q = q;
            this.gainDb = gainDb;
        }
    }

    /**
     * Builds 10-band EQ frame (Length = 0x6B = 107 bytes):
     * Used for 0x91 (Music:Bass-Mid-Treb), 0x95 (Bass EQ), 0x96 (Treble EQ), 0x97 (Mid EQ).
     */
    public static MvsiliconPacket buildEq10Packet(int effectId, boolean enable, double pregainDb, List<EqBand> bands) {
        ByteArrayOutputStream out = new ByteArrayOutputStream(106);
        writeU16LE(out, enable ? 1 : 0);
        writeI16LE(out, dbToEqFixed(pregainDb));
        writeU16LE(out, 0); // calculation_type = 0
        for (int i = 0; i < 10; i++) {
            if (bands != null && i < bands.size()) {
                EqBand b = bands.get(i);
                writeU16LE(out, b.enable ? 1 : 0);
                writeU16LE(out, b.type);
                writeU16LE(out, b.f0Hz);
                writeU16LE(out, qToFixed(b.q));
                writeI16LE(out, dbToEqFixed(b.gainDb));
            } else {
                writeU16LE(out, 0);
                writeU16LE(out, 0);
                writeU16LE(out, 1000);
                writeU16LE(out, 724);
                writeI16LE(out, 0);
            }
        }
        return new MvsiliconPacket(effectId, ALL_PARAM_MASK, out.toByteArray());
    }

    /**
     * Builds 0x91 (Music:Bass-Mid-Treb) 3-band quick tone frame (-6dB to +6dB).
     * Band 1: Bass (60Hz Low-Shelf / Peaking), Band 2: Mid (500Hz), Band 3: Treble (10000Hz).
     */
    public static MvsiliconPacket buildMusicBassMidTreble(double bassDb, double midDb, double trebleDb) {
        List<EqBand> bands = new ArrayList<>();
        bands.add(new EqBand(true, FILTER_PEAKING, 65, 0.90, bassDb));
        bands.add(new EqBand(true, FILTER_PEAKING, 800, 0.85, midDb));
        bands.add(new EqBand(true, FILTER_HIGH_SHELF, 8500, 0.707, trebleDb));
        return buildEq10Packet(EFFECT_MUSIC_BASS_MID_TREB, true, 0.0, bands);
    }

    /**
     * Builds 0x98 (Treble Gain) or 0x99 (Mid Gain) frame (Length = 0x07).
     * Safe treble gain for Ford 4ohm 5W (3uF cap): ~4096-4600.
     */
    public static MvsiliconPacket buildSpeakerGainPacket(int effectId, boolean enable, boolean mute, int gainRaw) {
        ByteArrayOutputStream out = new ByteArrayOutputStream(6);
        writeU16LE(out, enable ? 1 : 0);
        writeU16LE(out, mute ? 1 : 0);
        writeU16LE(out, Math.max(0, Math.min(16384, gainRaw)));
        return new MvsiliconPacket(effectId, ALL_PARAM_MASK, out.toByteArray());
    }

    /**
     * Builds 0x9A (Bass Phase) frame (Length = 0x05):
     * phase180 = false -> 0 deg, phase180 = true -> 180 deg inverted.
     */
    public static MvsiliconPacket buildBassPhasePacket(boolean enable, boolean phase180) {
        ByteArrayOutputStream out = new ByteArrayOutputStream(4);
        writeU16LE(out, enable ? 1 : 0);
        writeU16LE(out, phase180 ? 1 : 0);
        return new MvsiliconPacket(EFFECT_BASS_PHASE, ALL_PARAM_MASK, out.toByteArray());
    }

    /**
     * Builds 4-band DRC/Limiter frame (Length = 0x37 = 55 bytes):
     * Used for 0x93 (Music:DRC), 0x9B (Bass DRC), 0x9C (Mid DRC).
     */
    public static MvsiliconPacket buildDrcPacket(
            int effectId, boolean enable, int mode, int type,
            int fc1Hz, int fc2Hz,
            double thresholdDbfs, int ratio, int attackMs, int releaseMs) {
        ByteArrayOutputStream out = new ByteArrayOutputStream(54);
        writeU16LE(out, enable ? 1 : 0);
        writeU16LE(out, mode);
        writeU16LE(out, type);
        writeU16LE(out, 724); // ql = 0.707
        writeU16LE(out, 724); // qh = 0.707
        writeU16LE(out, fc1Hz);
        writeU16LE(out, fc2Hz);

        int th = dbfsToDrcThreshold(thresholdDbfs);
        for (int b = 0; b < 4; b++) writeI16LE(out, th);
        for (int b = 0; b < 4; b++) writeU16LE(out, ratio);
        for (int b = 0; b < 4; b++) writeU16LE(out, attackMs);
        for (int b = 0; b < 4; b++) writeU16LE(out, releaseMs);
        for (int b = 0; b < 4; b++) writeU16LE(out, 4096); // pregain = 0x1000 (0 dB)

        return new MvsiliconPacket(effectId, ALL_PARAM_MASK, out.toByteArray());
    }

    public static String toHexString(byte[] data) {
        if (data == null || data.length == 0) return "";
        StringBuilder sb = new StringBuilder(data.length * 3);
        for (int i = 0; i < data.length; i++) {
            if (i > 0) sb.append(' ');
            sb.append(String.format(Locale.US, "%02X", data[i] & 0xFF));
        }
        return sb.toString();
    }
}
