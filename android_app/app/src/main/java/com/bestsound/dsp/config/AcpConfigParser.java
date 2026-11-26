package com.bestsound.dsp.config;

import com.bestsound.dsp.usb.MvsiliconPacket;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Parser and Serializer for ACPWorkbench V2.44.2 (.ini) and C byte array (.c) files.
 * Reference format: dsp_punchy_bass_sweet_vocal.ini / .c (Firmware 0.3.4).
 */
public final class AcpConfigParser {

    public static final class AcpSection {
        public final String header;     // e.g. "0x95-Bass_SPK_Bass_EQ"
        public final int effectId;      // e.g. 0x95
        public final List<KeyValue> entries = new ArrayList<>();

        public AcpSection(String header, int effectId) {
            this.header = header;
            this.effectId = effectId;
        }

        public void put(String key, String value) {
            entries.add(new KeyValue(key, value));
        }

        public String get(String key, String defaultValue) {
            for (KeyValue kv : entries) {
                if (kv.key.equals(key)) return kv.value;
            }
            return defaultValue;
        }

        public int getInt(String key, int defaultValue) {
            String v = get(key, null);
            if (v == null) return defaultValue;
            try { return Integer.parseInt(v.trim()); } catch (NumberFormatException e) { return defaultValue; }
        }
    }

    public static final class KeyValue {
        public final String key;
        public final String value;

        public KeyValue(String key, String value) {
            this.key = key;
            this.value = value;
        }
    }

    public static final class AcpProfile {
        public String acpVersion = "2.44.2";
        public String commPort = "USB[0] :An Sound 3-Way";
        public final Map<String, AcpSection> sections = new LinkedHashMap<>();

        public void addSection(AcpSection section) {
            sections.put(section.header, section);
        }

        public AcpSection findByEffectId(int effectId) {
            for (AcpSection s : sections.values()) {
                if (s.effectId == effectId) return s;
            }
            return null;
        }
    }

    private AcpConfigParser() {}

    /**
     * Parses an ACPWorkbench .ini text into an AcpProfile object.
     */
    public static AcpProfile parseIni(String iniText) {
        AcpProfile profile = new AcpProfile();
        if (iniText == null) return profile;

        AcpSection current = null;
        String[] lines = iniText.split("\\r?\\n");
        for (String rawLine : lines) {
            String line = rawLine.trim();
            if (line.isEmpty()) continue;

            if (line.startsWith("#")) {
                if (line.startsWith("#ACPWorkbench Version:")) {
                    profile.acpVersion = line.substring("#ACPWorkbench Version:".length()).trim();
                } else if (line.startsWith("#Communication Port:")) {
                    profile.commPort = line.substring("#Communication Port:".length()).trim();
                }
                continue;
            }

            if (line.startsWith("[") && line.endsWith("]")) {
                String header = line.substring(1, line.length() - 1).trim();
                int effId = extractEffectId(header);
                current = new AcpSection(header, effId);
                profile.addSection(current);
                continue;
            }

            int eq = line.indexOf('=');
            if (eq > 0 && current != null) {
                String key = line.substring(0, eq).trim();
                String val = line.substring(eq + 1).trim();
                current.put(key, val);
            }
        }
        return profile;
    }

    private static int extractEffectId(String header) {
        int dash = header.indexOf('-');
        String hex = (dash > 0 ? header.substring(0, dash) : header).trim();
        if (hex.startsWith("0x") || hex.startsWith("0X")) {
            try {
                return Integer.parseInt(hex.substring(2), 16) & 0xFF;
            } catch (NumberFormatException ignored) {}
        }
        return -1;
    }

    /**
     * Serializes an AcpProfile back to ACPWorkbench V2.44.2 .ini format.
     */
    public static String serializeIni(AcpProfile profile) {
        StringBuilder sb = new StringBuilder();
        sb.append("#Audio Settings Configuration: 0\n");
        sb.append("#ACPWorkbench Version: ").append(profile.acpVersion).append('\n');
        sb.append("#Communication Port: ").append(profile.commPort).append('\n');
        sb.append("#Generated: An Sound 3-Way OTG Studio\n\n");

        for (AcpSection sec : profile.sections.values()) {
            sb.append('[').append(sec.header).append("]\n");
            for (KeyValue kv : sec.entries) {
                sb.append(kv.key).append(" = ").append(kv.value).append('\n');
            }
            sb.append('\n');
        }
        return sb.toString();
    }

    /**
     * Exports a list of MvsiliconPacket frames into MVSilicon C byte array source (.c):
     * //ACPWorkbench Version: 2.44.2
     * const unsigned char dsp[N] = { ... };
     */
    public static String exportCSource(String arrayName, List<MvsiliconPacket> packets) {
        int totalBytes = 0;
        List<byte[]> rawFrames = new ArrayList<>();
        for (MvsiliconPacket p : packets) {
            byte[] b = p.toBytes();
            rawFrames.add(b);
            totalBytes += b.length;
        }

        StringBuilder sb = new StringBuilder();
        sb.append("//ACPWorkbench Version: 2.44.2\n");
        sb.append("//Firmware: 0.3.4 | Target: Quoc Doan Audio 70Wx2 (3-Way)\n");
        sb.append(String.format(Locale.US, "const unsigned char %s[%d] = {\n\n", arrayName, totalBytes));

        for (int idx = 0; idx < rawFrames.size(); idx++) {
            byte[] frame = rawFrames.get(idx);
            MvsiliconPacket pkt = packets.get(idx);
            sb.append(String.format(Locale.US, "0x%02X, 0x%02X, /*sync head*/\n", frame[0] & 0xFF, frame[1] & 0xFF));
            sb.append(String.format(Locale.US, "0x%02X, /*Effect_ID*/\n", pkt.getEffectId()));
            sb.append(String.format(Locale.US, "0x%02X, /*length*/\n", frame[3] & 0xFF));
            sb.append(String.format(Locale.US, "0x%02X, /*all parameter*/\n", pkt.getParamMask()));

            for (int j = 5; j < frame.length - 1; j += 2) {
                if (j + 1 < frame.length - 1) {
                    sb.append(String.format(Locale.US, "0x%02X, 0x%02X, ", frame[j] & 0xFF, frame[j + 1] & 0xFF));
                } else {
                    sb.append(String.format(Locale.US, "0x%02X, ", frame[j] & 0xFF));
                }
                if (((j - 5) / 2 + 1) % 6 == 0) sb.append('\n');
            }
            sb.append('\n');
            if (idx < rawFrames.size() - 1) {
                sb.append("0x16, /*sync tail*/\n\n");
            } else {
                sb.append("0x16 /*sync tail*/\n");
            }
        }
        sb.append("};\n");
        return sb.toString();
    }
}
