package com.bestsound.dsp.ui;

import android.app.Activity;
import android.os.Environment;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import android.widget.Toast;

import com.bestsound.dsp.config.AcpConfigParser;
import com.bestsound.dsp.config.Dsp3WayPresets;
import com.bestsound.dsp.usb.MvsiliconPacket;
import com.bestsound.dsp.usb.UsbOtgController;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/**
 * UI Bridge connecting the USB OTG MVSilicon Engine & 3-Way Presets to the WebView DSP Console.
 */
public class DspOtgBridge {
    private final Activity activity;
    private final WebView webView;
    private final UsbOtgController otgController;

    private Dsp3WayPresets.PresetState currentPreset = Dsp3WayPresets.buildSpecMatchedPreset();
    private double curBassDb = 0.0, curMidDb = 0.0, curTrebleDb = 0.0;
    private int curMidGain = 4600, curTrebleGain = 4350;
    private boolean curPhase180 = false;
    private boolean curDrcEnabled = true;

    public DspOtgBridge(Activity activity, WebView webView, UsbOtgController otgController) {
        this.activity = activity;
        this.webView = webView;
        this.otgController = otgController;

        this.otgController.setCallback(new UsbOtgController.OtgCallback() {
            @Override
            public void onDeviceAttached(String name, int vid, int pid, String mode) {
                String safeName = name.replace("'", "");
                emitJs(String.format(Locale.US,
                        "if(window.onOtgStatus) window.onOtgStatus(true, '%s', '0x%04X', '0x%04X', '%s');",
                        safeName, vid, pid, mode));
            }

            @Override
            public void onDeviceDetached() {
                emitJs("if(window.onOtgStatus) window.onOtgStatus(false, 'Chưa kết nối', '--', '--', 'NONE');");
            }

            @Override
            public void onPacketLog(String direction, String hexSummary) {
                String safe = hexSummary.replace("'", "");
                emitJs("if(window.onOtgLog) window.onOtgLog('" + direction + "', '" + safe + "');");
            }

            @Override
            public void onRxPacket(MvsiliconPacket packet) {
                emitJs(String.format(Locale.US,
                        "if(window.onOtgLog) window.onOtgLog('RX_PARSED', 'Effect 0x%02X (%d bytes)');",
                        packet.getEffectId(), packet.getPayload().length));
            }

            @Override
            public void onError(String message) {
                String safe = message.replace("'", "");
                emitJs("if(window.onOtgLog) window.onOtgLog('ERR', '" + safe + "');");
            }
        });
    }

    private void emitJs(String js) {
        activity.runOnUiThread(() -> {
            if (webView != null) webView.evaluateJavascript(js, null);
        });
    }

    @JavascriptInterface
    public void connectUsbOtg() {
        otgController.scanAndConnect();
    }

    @JavascriptInterface
    public void disconnectUsbOtg() {
        otgController.disconnect();
    }

    @JavascriptInterface
    public boolean isUsbOtgConnected() {
        return otgController.isConnected();
    }

    @JavascriptInterface
    public void setMusicTone(double bassDb, double midDb, double trebleDb) {
        curBassDb = bassDb;
        curMidDb = midDb;
        curTrebleDb = trebleDb;
        MvsiliconPacket pkt = MvsiliconPacket.buildMusicBassMidTreble(bassDb, midDb, trebleDb);
        otgController.sendPacket(pkt);
    }

    @JavascriptInterface
    public void setMidGain(int gainRaw) {
        curMidGain = gainRaw;
        MvsiliconPacket pkt = MvsiliconPacket.buildSpeakerGainPacket(MvsiliconPacket.EFFECT_MID_GAIN, true, false, gainRaw);
        otgController.sendPacket(pkt);
    }

    @JavascriptInterface
    public void setTrebleGain(int gainRaw) {
        curTrebleGain = gainRaw;
        MvsiliconPacket pkt = MvsiliconPacket.buildSpeakerGainPacket(MvsiliconPacket.EFFECT_TREBLE_GAIN, true, false, gainRaw);
        otgController.sendPacket(pkt);
    }

    @JavascriptInterface
    public void setBassPhase(boolean phase180) {
        curPhase180 = phase180;
        MvsiliconPacket pkt = MvsiliconPacket.buildBassPhasePacket(true, phase180);
        otgController.sendPacket(pkt);
    }

    @JavascriptInterface
    public void setDrcEnabled(boolean enabled) {
        curDrcEnabled = enabled;
        double th = currentPreset.drcThresholdDbfs;
        otgController.sendPacket(MvsiliconPacket.buildDrcPacket(MvsiliconPacket.EFFECT_BASS_DRC, enabled, 0, 4, 137, 20000, th, 50, 2, 80));
        otgController.sendPacket(MvsiliconPacket.buildDrcPacket(MvsiliconPacket.EFFECT_MID_DRC, enabled, 0, 1, 319, 2000, th, 50, 2, 80));
        otgController.sendPacket(MvsiliconPacket.buildDrcPacket(MvsiliconPacket.EFFECT_MUSIC_DRC, enabled, 2, 4, 300, 2000, th, 50, 2, 60));
    }

    @JavascriptInterface
    public String applyPreset(String presetKey) {
        if ("factory".equals(presetKey)) {
            currentPreset = Dsp3WayPresets.buildFactoryDynamicEqPreset();
        } else {
            currentPreset = Dsp3WayPresets.buildSpecMatchedPreset();
        }
        curBassDb = currentPreset.musicBassDb;
        curMidDb = currentPreset.musicMidDb;
        curTrebleDb = currentPreset.musicTrebleDb;
        curMidGain = currentPreset.midGainRaw;
        curTrebleGain = currentPreset.trebleGainRaw;
        curPhase180 = currentPreset.bassPhase180;
        curDrcEnabled = currentPreset.drcEnabled;

        for (MvsiliconPacket pkt : currentPreset.packets) {
            otgController.sendPacket(pkt);
        }
        return String.format(Locale.US,
                "{\"name\":\"%s\",\"bass\":%.1f,\"mid\":%.1f,\"treble\":%.1f,\"midGain\":%d,\"trebleGain\":%d,\"phase180\":%b,\"drc\":%b}",
                currentPreset.name, curBassDb, curMidDb, curTrebleDb, curMidGain, curTrebleGain, curPhase180, curDrcEnabled);
    }

    @JavascriptInterface
    public String exportConfig(String format) {
        Dsp3WayPresets.PresetState snapshot = new Dsp3WayPresets.PresetState(
                currentPreset.name, curBassDb, curMidDb, curTrebleDb,
                curMidGain, curTrebleGain, curPhase180, curDrcEnabled,
                currentPreset.drcThresholdDbfs, currentPreset.packets);

        String content;
        String ext;
        if ("c".equalsIgnoreCase(format)) {
            content = AcpConfigParser.exportCSource("dsp", snapshot.packets);
            ext = "c";
        } else {
            content = AcpConfigParser.serializeIni(Dsp3WayPresets.toIniProfile(snapshot));
            ext = "ini";
        }

        try {
            File dir = activity.getExternalFilesDir(Environment.DIRECTORY_DOCUMENTS);
            if (dir != null && !dir.exists()) dir.mkdirs();
            File out = new File(dir, "ansound_3way_preset." + ext);
            try (FileOutputStream fos = new FileOutputStream(out)) {
                fos.write(content.getBytes(StandardCharsets.UTF_8));
            }
            activity.runOnUiThread(() ->
                    Toast.makeText(activity, "Đã xuất file: " + out.getName(), Toast.LENGTH_SHORT).show());
            return out.getAbsolutePath();
        } catch (Exception e) {
            return "ERROR: " + e.getMessage();
        }
    }
}
