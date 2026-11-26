package com.bestsound.dsp;

import com.bestsound.dsp.config.AcpConfigParser;
import com.bestsound.dsp.config.Dsp3WayPresets;
import com.bestsound.dsp.usb.MvsiliconPacket;

import org.junit.Test;

import java.util.Collections;
import java.util.List;

import static org.junit.Assert.*;

public class AcpConfigParserTest {

    private static final String SAMPLE_INI =
            "#ACPWorkbench Version: 2.44.2\n" +
            "#Communication Port: COM3\n" +
            "[0x98-Treble Gain]\n" +
            "gain = 4096\n" +
            "[0x9A-Bass Phase]\n" +
            "invert = 0\n";

    @Test
    public void parseAndSerializeIni_roundTripsSectionsAndKeys() {
        AcpConfigParser.AcpProfile profile = AcpConfigParser.parseIni(SAMPLE_INI);
        assertEquals("2.44.2", profile.acpVersion);
        assertEquals("COM3", profile.commPort);

        AcpConfigParser.AcpSection treble = profile.findByEffectId(0x98);
        assertNotNull(treble);
        assertEquals(0x98, treble.effectId);
        assertEquals(4096, treble.getInt("gain", -1));

        AcpConfigParser.AcpSection phase = profile.findByEffectId(0x9A);
        assertNotNull(phase);
        assertEquals(0, phase.getInt("invert", -1));

        String serialized = AcpConfigParser.serializeIni(profile);
        AcpConfigParser.AcpProfile reparsed = AcpConfigParser.parseIni(serialized);
        assertEquals(4096, reparsed.findByEffectId(0x98).getInt("gain", -1));
        assertEquals(0, reparsed.findByEffectId(0x9A).getInt("invert", -1));
    }

    @Test
    public void exportCSource_producesValidMvsiliconHexArray() {
        MvsiliconPacket pkt = MvsiliconPacket.buildBassPhasePacket(true, true);
        String cCode = AcpConfigParser.exportCSource("dsp_test", Collections.singletonList(pkt));

        assertTrue(cCode.contains("const unsigned char dsp_test[10] = {"));
        assertTrue(cCode.contains("0xA5, 0x5A, /*sync head*/"));
        assertTrue(cCode.contains("0x9A, /*Effect_ID*/"));
        assertTrue(cCode.contains("0x05, /*length*/"));
        assertTrue(cCode.contains("0xFF, /*all parameter*/"));
        assertTrue(cCode.contains("0x16 /*sync tail*/"));
        assertTrue(cCode.trim().endsWith("};"));
    }

    @Test
    public void specMatchedPreset_matches3WayHardwareSafetyLimits() {
        Dsp3WayPresets.PresetState spec = Dsp3WayPresets.buildSpecMatchedPreset();
        assertNotNull(spec.name);
        assertTrue(spec.trebleGainRaw <= Dsp3WayPresets.TREBLE_SAFE_MAX_GAIN);
        assertTrue(spec.drcEnabled);
        assertTrue(spec.drcThresholdDbfs <= -2.0 && spec.drcThresholdDbfs >= -3.0);
        assertNotNull(spec.packets);
        assertFalse(spec.packets.isEmpty());

        AcpConfigParser.AcpProfile profile = Dsp3WayPresets.toIniProfile(spec);
        assertNotNull(profile.findByEffectId(0x98));
        assertNotNull(profile.findByEffectId(0x99));
        assertNotNull(profile.findByEffectId(0x9A));
        assertEquals(spec.trebleGainRaw, profile.findByEffectId(0x98).getInt("gain", -1));
    }

    @Test
    public void factoryDynamicEqPreset_hasValidPacketsAndIniSnapshot() {
        Dsp3WayPresets.PresetState factory = Dsp3WayPresets.buildFactoryDynamicEqPreset();
        assertNotNull(factory.name);
        assertNotNull(factory.packets);
        assertFalse(factory.packets.isEmpty());

        List<MvsiliconPacket> packets = factory.packets;
        for (MvsiliconPacket p : packets) {
            byte[] frame = p.toBytes();
            assertEquals((byte) 0xA5, frame[0]);
            assertEquals((byte) 0x5A, frame[1]);
            assertEquals((byte) 0x16, frame[frame.length - 1]);
        }

        AcpConfigParser.AcpProfile profile = Dsp3WayPresets.toIniProfile(factory);
        String serialized = AcpConfigParser.serializeIni(profile);
        assertTrue(serialized.contains("#ACPWorkbench"));
        assertTrue(serialized.contains("0x98"));
    }
}
