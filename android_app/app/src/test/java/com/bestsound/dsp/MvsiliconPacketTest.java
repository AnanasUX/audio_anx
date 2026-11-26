package com.bestsound.dsp;

import com.bestsound.dsp.usb.MvsiliconPacket;
import org.junit.Test;
import java.util.List;
import static org.junit.Assert.*;

public class MvsiliconPacketTest {

    @Test
    public void testBassPhasePacketEncodingAndParsing() {
        MvsiliconPacket pkt0 = MvsiliconPacket.buildBassPhasePacket(false, false);
        byte[] raw0 = pkt0.toBytes();
        // Reference from dsp_punchy_bass_sweet_vocal.c: A5 5A 9A 05 FF 00 00 00 00 16
        assertArrayEquals(new byte[]{
                (byte) 0xA5, 0x5A, (byte) 0x9A, 0x05, (byte) 0xFF,
                0x00, 0x00, 0x00, 0x00, 0x16
        }, raw0);

        MvsiliconPacket pkt180 = MvsiliconPacket.buildBassPhasePacket(true, true);
        MvsiliconPacket parsed = MvsiliconPacket.parse(pkt180.toBytes());
        assertEquals(0x9A, parsed.getEffectId());
        assertEquals(1, MvsiliconPacket.readU16LE(parsed.getPayload(), 0));
        assertEquals(1, MvsiliconPacket.readU16LE(parsed.getPayload(), 2));
    }

    @Test
    public void testSpeakerGainLittleEndian() {
        // Treble gain 4350 = 0x10FE -> LE [0xFE, 0x10]
        MvsiliconPacket treb = MvsiliconPacket.buildSpeakerGainPacket(MvsiliconPacket.EFFECT_TREBLE_GAIN, true, false, 4350);
        byte[] raw = treb.toBytes();
        assertEquals(12, raw.length); // 2 + 1 + 1 + 1 + 6 + 1
        assertEquals(0x07, raw[3] & 0xFF);
        assertEquals((byte) 0xFE, raw[9]);
        assertEquals((byte) 0x10, raw[10]);
        assertEquals((byte) 0x16, raw[11]);

        // Mid gain 4600 = 0x11F8 -> LE [0xF8, 0x11]
        MvsiliconPacket mid = MvsiliconPacket.buildSpeakerGainPacket(MvsiliconPacket.EFFECT_MID_GAIN, true, false, 4600);
        byte[] midRaw = mid.toBytes();
        assertEquals((byte) 0xF8, midRaw[9]);
        assertEquals((byte) 0x11, midRaw[10]);
    }

    @Test
    public void testEq10AndFixedPointSignedConversions() {
        assertEquals(768, MvsiliconPacket.dbToEqFixed(3.0));
        assertEquals(-896, MvsiliconPacket.dbToEqFixed(-3.5));

        MvsiliconPacket tone = MvsiliconPacket.buildMusicBassMidTreble(2.0, 0.5, -1.5);
        byte[] raw = tone.toBytes();
        assertEquals((byte) 0x91, raw[2]);
        assertEquals(0x6B, raw[3] & 0xFF); // 1 + 106 = 107 = 0x6B
        assertEquals(112, raw.length);
        assertEquals(0x16, raw[raw.length - 1] & 0xFF);
    }

    @Test
    public void testDrcPacketAndThreshold() {
        assertEquals(-250, MvsiliconPacket.dbfsToDrcThreshold(-2.5));
        MvsiliconPacket drc = MvsiliconPacket.buildDrcPacket(
                MvsiliconPacket.EFFECT_MUSIC_DRC, true, 2, 4, 300, 2000, -2.5, 50, 2, 60);
        byte[] raw = drc.toBytes();
        assertEquals(0x37, raw[3] & 0xFF); // 55 = 0x37
        assertEquals(60, raw.length);
        // threshold1 at payload offset 14 -> frame offset 19
        assertEquals(-250, MvsiliconPacket.readI16LE(raw, 19));
    }

    @Test
    public void testParseStreamWithNoise() {
        byte[] valid1 = MvsiliconPacket.buildBassPhasePacket(true, false).toBytes();
        byte[] valid2 = MvsiliconPacket.buildSpeakerGainPacket(MvsiliconPacket.EFFECT_TREBLE_GAIN, true, false, 4096).toBytes();
        byte[] stream = new byte[3 + valid1.length + 2 + valid2.length + 1];
        stream[0] = 0x00; stream[1] = 0x11; stream[2] = 0x22;
        System.arraycopy(valid1, 0, stream, 3, valid1.length);
        stream[3 + valid1.length] = (byte) 0x99;
        System.arraycopy(valid2, 0, stream, 5 + valid1.length, valid2.length);

        List<MvsiliconPacket> parsed = MvsiliconPacket.parseStream(stream);
        assertEquals(2, parsed.size());
        assertEquals(0x9A, parsed.get(0).getEffectId());
        assertEquals(0x98, parsed.get(1).getEffectId());
    }
}
