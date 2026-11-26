package com.bestsound.dsp;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.AudioDeviceCallback;
import android.media.AudioDeviceInfo;
import android.media.AudioManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.view.View;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.TextView;
import android.widget.Toast;

import com.bestsound.dsp.ui.DspOtgBridge;
import com.bestsound.dsp.usb.UsbOtgController;

import java.io.File;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.Set;

public class MainActivity extends Activity implements UsbDspManager.DspCallback, BluetoothDspManager.BluetoothCallback {

    private static final int REQUEST_BT_PERMISSIONS = 101;
    private static final int REQUEST_ENABLE_BT = 102;
    private static final int REQUEST_AUDIO_PERMISSION = 103;

    private UsbDspManager usbDspManager;
    private BluetoothDspManager bluetoothDspManager;
    private NativeKaraokeEngine nativeKaraokeEngine;
    private UsbOtgController otgController;

    // Dual-Tab Views
    private Button btnTabQuick;
    private Button btnTabStudio;
    private ScrollView scrollViewQuick;
    private WebView webViewStudio;

    private View viewStatusDot;
    private TextView tvStatus;
    private TextView tvBassVal;
    private TextView tvTrebleVal;
    private TextView tvMVBassVal;
    private TextView tvLog;
    private ProgressBar progressBar;
    private Button btnConnectUsb;
    private Button btnConnectBt;

    private SeekBar sbBass;
    private SeekBar sbTreble;
    private SeekBar sbMVBass;

    // 8-Band Frequency Tuners
    private SeekBar sbFreq62, sbFreq85, sbFreq125, sbFreq165;
    private SeekBar sbFreq500, sbFreq1k, sbFreq2_5k, sbFreq8k;
    private TextView tvFreq62Val, tvFreq85Val, tvFreq125Val, tvFreq165Val;
    private TextView tvFreq500Val, tvFreq1kVal, tvFreq2_5kVal, tvFreq8kVal;
    private Button btnOpenWebStudio;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        usbDspManager = new UsbDspManager(this);
        usbDspManager.setCallback(this);

        bluetoothDspManager = new BluetoothDspManager(this);
        bluetoothDspManager.setCallback(this);

        otgController = new UsbOtgController(this);

        nativeKaraokeEngine = KaraokeForegroundService.getEngine(this);
        nativeKaraokeEngine.setMeterCallback((db, latencyMs) -> runOnUiThread(() -> {
            if (webViewStudio != null) {
                String dbStr = String.format(Locale.US, "%.1f", db);
                String latStr = String.format(Locale.US, "%.1f", latencyMs);
                webViewStudio.evaluateJavascript("if (typeof onNativeVocalMeter === 'function') { onNativeVocalMeter(" + dbStr + ", " + latStr + "); }", null);
            }
        }));
        KaraokeForegroundService.setStateListener(() -> runOnUiThread(() -> {
            if (webViewStudio != null) {
                webViewStudio.evaluateJavascript("if (typeof onNativeKaraokeStopped === 'function') { onNativeKaraokeStopped(); }", null);
            }
        }));

        initViews();
        setupListeners();
        setupWebView();
        checkAudioPermission();
        configureAudioRouting();
        setupAudioDeviceListener();
        switchTab(true); // Default to the new Figma Make Dark Studio UI!
    }

    private void checkAudioPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQUEST_AUDIO_PERMISSION);
            }
        }
    }

    private void initViews() {
        btnTabQuick = findViewById(R.id.btnTabQuick);
        btnTabStudio = findViewById(R.id.btnTabStudio);
        scrollViewQuick = findViewById(R.id.scrollViewQuick);
        webViewStudio = findViewById(R.id.webViewStudio);

        btnConnectBt = findViewById(R.id.btnConnectBt);
        btnConnectUsb = findViewById(R.id.btnConnect);
        viewStatusDot = findViewById(R.id.viewStatusDot);
        tvStatus = findViewById(R.id.tvStatus);
        tvBassVal = findViewById(R.id.tvBassVal);
        tvTrebleVal = findViewById(R.id.tvTrebleVal);
        tvMVBassVal = findViewById(R.id.tvMVBassVal);
        tvLog = findViewById(R.id.tvLog);
        progressBar = findViewById(R.id.progressBar);

        sbBass = findViewById(R.id.sbBass);
        sbTreble = findViewById(R.id.sbTreble);
        sbMVBass = findViewById(R.id.sbMVBass);

        // 8-Band Views
        sbFreq62 = findViewById(R.id.sbFreq62);
        sbFreq85 = findViewById(R.id.sbFreq85);
        sbFreq125 = findViewById(R.id.sbFreq125);
        sbFreq165 = findViewById(R.id.sbFreq165);
        sbFreq500 = findViewById(R.id.sbFreq500);
        sbFreq1k = findViewById(R.id.sbFreq1k);
        sbFreq2_5k = findViewById(R.id.sbFreq2_5k);
        sbFreq8k = findViewById(R.id.sbFreq8k);

        tvFreq62Val = findViewById(R.id.tvFreq62Val);
        tvFreq85Val = findViewById(R.id.tvFreq85Val);
        tvFreq125Val = findViewById(R.id.tvFreq125Val);
        tvFreq165Val = findViewById(R.id.tvFreq165Val);
        tvFreq500Val = findViewById(R.id.tvFreq500Val);
        tvFreq1kVal = findViewById(R.id.tvFreq1kVal);
        tvFreq2_5kVal = findViewById(R.id.tvFreq2_5kVal);
        tvFreq8kVal = findViewById(R.id.tvFreq8kVal);

        btnOpenWebStudio = findViewById(R.id.btnOpenWebStudio);
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void setupWebView() {
        WebSettings ws = webViewStudio.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setAllowFileAccess(true);
        ws.setMediaPlaybackRequiresUserGesture(false);

        webViewStudio.setWebViewClient(new WebViewClient());
        webViewStudio.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(final PermissionRequest request) {
                runOnUiThread(() -> request.grant(request.getResources()));
            }
        });

        webViewStudio.addJavascriptInterface(new AndroidDspBridge(), "AndroidDsp");
        webViewStudio.addJavascriptInterface(new DspOtgBridge(this, webViewStudio, otgController), "OtgDsp");
        if (getPackageName().contains("karaoke")) {
            webViewStudio.loadUrl("file:///android_asset/karaoke/index.html");
        } else {
            webViewStudio.loadUrl("file:///android_asset/otg/index.html");
        }
    }

    public class AndroidDspBridge {
        @JavascriptInterface
        public void updateBand(int bandIndex, double f0, double gainDb, double q) {
            byte[] packet;
            if (bandIndex < 4) {
                int filterIdx = 3 + bandIndex; // Filter 3: 62Hz, 4: 85Hz, 5: 125Hz, 6: 165Hz
                packet = DspProfiles.updateBassFilterGain(filterIdx, gainDb);
            } else {
                int filterIdx = 1 + (bandIndex - 4); // Filter 1: 500Hz, 2: 1kHz, 3: 2.5kHz, 5: 8kHz
                if (bandIndex == 7) filterIdx = 5;
                packet = DspProfiles.updateTrebleFilterGain(filterIdx, gainDb);
            }
            sendPacket(packet);
            runOnUiThread(() -> {
                tvLog.setText(String.format(Locale.US, "Studio PEQ Band %d (%d Hz, %+.1f dB)", bandIndex + 1, (int) Math.round(f0), gainDb));
                syncNativeSeekbars(bandIndex, gainDb);
            });
        }

        @JavascriptInterface
        public void applyPreset(String name) {
            runOnUiThread(() -> {
                if (name.contains("B&O") || name.contains("bo-8ohm") || name.contains("Signature")) {
                    sendFullProfile(DspProfiles.PROFILE_BO_8OHM_24V, "B&O 8-Ohm 24V");
                    sbBass.setProgress(7200);
                    sbTreble.setProgress(8000);
                    sbMVBass.setProgress(28);
                } else if (name.contains("JBL") || name.contains("Boombox") || name.contains("boombox")) {
                    sendFullProfile(DspProfiles.PROFILE_BO_8OHM_24V, "JBL Boombox");
                    sendPacket(DspProfiles.buildSubGainPacket(8000));
                    sendPacket(DspProfiles.buildMVBassPacket(65, 40));
                    sbBass.setProgress(8000);
                    sbMVBass.setProgress(40);
                } else if (name.contains("Vocal") || name.contains("vocal")) {
                    sendFullProfile(DspProfiles.PROFILE_BO_8OHM_24V, "Sweet Vocal");
                    sendPacket(DspProfiles.buildSubGainPacket(6000));
                    sendPacket(DspProfiles.buildTrebleGainPacket(8500));
                    sbBass.setProgress(6000);
                    sbTreble.setProgress(8500);
                } else {
                    sendFullProfile(DspProfiles.PROFILE_ORIGINAL, "Original Reset");
                    sbBass.setProgress(4096);
                    sbTreble.setProgress(4096);
                    sbMVBass.setProgress(0);
                }
            });
        }

        @JavascriptInterface
        public void setMasterPreamp(double gainDb) {
            int linearGain = (int) Math.round(4096.0 * Math.pow(10.0, gainDb / 20.0));
            sendPacket(DspProfiles.buildSubGainPacket(linearGain));
        }

        @JavascriptInterface
        public void connectUsb() {
            runOnUiThread(() -> usbDspManager.connect());
        }

        @JavascriptInterface
        public void connectBluetooth() {
            runOnUiThread(() -> handleBluetoothConnectClick());
        }

        @JavascriptInterface
        public boolean isConnected() {
            return usbDspManager.isConnected() || bluetoothDspManager.isConnected();
        }

        @JavascriptInterface
        public void toast(String msg) {
            runOnUiThread(() -> Toast.makeText(MainActivity.this, msg, Toast.LENGTH_SHORT).show());
        }

        @JavascriptInterface
        public boolean isBluetoothOutputConnected() {
            return MainActivity.this.isBluetoothOutputConnected();
        }

        @JavascriptInterface
        public void refreshAudioRouting() {
            runOnUiThread(MainActivity.this::configureAudioRouting);
        }

        @JavascriptInterface
        public boolean startNativeKaraoke() {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M &&
                checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                runOnUiThread(() -> {
                    requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQUEST_AUDIO_PERMISSION);
                    Toast.makeText(MainActivity.this, "Vui lòng cấp quyền Micro để hát Karaoke!", Toast.LENGTH_SHORT).show();
                });
                return false;
            }
            if (Build.VERSION.SDK_INT >= 33 &&
                checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                runOnUiThread(() -> requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 104));
            }
            configureAudioRouting();
            Intent svcIntent = new Intent(MainActivity.this, KaraokeForegroundService.class);
            svcIntent.setAction(KaraokeForegroundService.ACTION_START);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(svcIntent);
            } else {
                startService(svcIntent);
            }
            return true;
        }

        @JavascriptInterface
        public void stopNativeKaraoke() {
            Intent svcIntent = new Intent(MainActivity.this, KaraokeForegroundService.class);
            svcIntent.setAction(KaraokeForegroundService.ACTION_STOP);
            startService(svcIntent);
        }

        @JavascriptInterface
        public boolean isNativeKaraokeRunning() {
            return KaraokeForegroundService.isRunning();
        }

        @JavascriptInterface
        public void setKaraokeParams(float micGain, float toneDb, float echoMix, int echoDelayMs, float echoFb, float reverbMix, float reverbSize, float dryLevel, float nearFieldLevel, boolean lowCut, boolean antiHowl, boolean hwAec) {
            NativeKaraokeEngine eng = KaraokeForegroundService.getEngine(MainActivity.this);
            eng.setMicGain(micGain);
            eng.setToneDb(toneDb);
            eng.setEchoMix(echoMix);
            eng.setEchoDelayMs(echoDelayMs);
            eng.setEchoFeedback(echoFb);
            eng.setReverbMix(reverbMix);
            eng.setReverbSize(reverbSize);
            eng.setDryLevel(dryLevel);
            eng.setNearFieldLevel(nearFieldLevel);
            eng.setLowCutEnabled(lowCut);
            eng.setAntiHowlEnabled(antiHowl);
            eng.setHwAecEnabled(hwAec);
        }

        @JavascriptInterface
        public void setKaraokeEqAndFx(float bassDb, float midDb, float trebleDb, float stereoChorus) {
            NativeKaraokeEngine eng = KaraokeForegroundService.getEngine(MainActivity.this);
            eng.setBassDb(bassDb);
            eng.setMidDb(midDb);
            eng.setTrebleDb(trebleDb);
            eng.setStereoChorus(stereoChorus);
        }

        @JavascriptInterface
        public void setAudioRoute(String outputRoute, boolean forceBuiltInMic) {
            NativeKaraokeEngine eng = KaraokeForegroundService.getEngine(MainActivity.this);
            eng.setPreferredOutputRoute(outputRoute);
            eng.setForceBuiltInMic(forceBuiltInMic);
        }

        @JavascriptInterface
        public void setGateThresholdDb(float db) {
            NativeKaraokeEngine eng = KaraokeForegroundService.getEngine(MainActivity.this);
            eng.setGateThresholdDb(db);
        }

        @JavascriptInterface
        public boolean startWavRecording() {
            NativeKaraokeEngine eng = KaraokeForegroundService.getEngine(MainActivity.this);
            if (!eng.isRunning()) return false;
            File musicDir = getExternalFilesDir(Environment.DIRECTORY_MUSIC);
            String stamp = new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(new Date());
            File outFile = new File(musicDir, "Ansound_Karaoke_" + stamp + ".wav");
            return eng.startWavRecording(outFile);
        }

        @JavascriptInterface
        public String stopWavRecording() {
            NativeKaraokeEngine eng = KaraokeForegroundService.getEngine(MainActivity.this);
            String path = eng.stopWavRecording();
            return path != null ? ("file://" + path) : "";
        }

        @JavascriptInterface
        public void openYouTubeKaraoke(String query) {
            runOnUiThread(() -> {
                try {
                    String q = (query != null && !query.trim().isEmpty()) ? query.trim() + " karaoke" : "nhac karaoke beat";
                    Intent ytIntent = new Intent(Intent.ACTION_VIEW, Uri.parse("https://www.youtube.com/results?search_query=" + Uri.encode(q)));
                    startActivity(ytIntent);
                } catch (Exception e) {
                    Toast.makeText(MainActivity.this, "Không mở được YouTube: " + e.getMessage(), Toast.LENGTH_SHORT).show();
                }
            });
        }
    }

    private void syncNativeSeekbars(int bandIndex, double gainDb) {
        int progress = (int) Math.round((gainDb / 0.1) + 120);
        progress = Math.max(0, Math.min(240, progress));

        switch (bandIndex) {
            case 0: sbFreq62.setProgress(progress); break;
            case 1: sbFreq85.setProgress(progress); break;
            case 2: sbFreq125.setProgress(progress); break;
            case 3: sbFreq165.setProgress(progress); break;
            case 4: sbFreq500.setProgress(progress); break;
            case 5: sbFreq1k.setProgress(progress); break;
            case 6: sbFreq2_5k.setProgress(progress); break;
            case 7: sbFreq8k.setProgress(progress); break;
        }
    }

    private void switchTab(boolean showStudio) {
        if (showStudio) {
            scrollViewQuick.setVisibility(View.GONE);
            webViewStudio.setVisibility(View.VISIBLE);
            btnTabStudio.setBackgroundTintList(getColorStateList(R.color.accent_blue));
            btnTabQuick.setBackgroundTintList(getColorStateList(R.color.bg_card));
        } else {
            webViewStudio.setVisibility(View.GONE);
            scrollViewQuick.setVisibility(View.VISIBLE);
            btnTabQuick.setBackgroundTintList(getColorStateList(R.color.accent_blue));
            btnTabStudio.setBackgroundTintList(getColorStateList(R.color.bg_card));
        }
    }

    private void setupListeners() {
        btnTabQuick.setOnClickListener(v -> switchTab(false));
        btnTabStudio.setOnClickListener(v -> switchTab(true));
        btnOpenWebStudio.setOnClickListener(v -> switchTab(true));

        btnConnectBt.setOnClickListener(v -> handleBluetoothConnectClick());
        btnConnectUsb.setOnClickListener(v -> usbDspManager.connect());

        findViewById(R.id.btnPresetBO8Ohm).setOnClickListener(v -> {
            sendFullProfile(DspProfiles.PROFILE_BO_8OHM_24V, "B&O 8-Ohm 24V (Bass Đầm - Treble Sáng - Vocal Ngọt)");
            sbBass.setProgress(7200);
            sbTreble.setProgress(8000);
            sbMVBass.setProgress(28);
        });

        findViewById(R.id.btnPresetBoombox).setOnClickListener(v -> {
            sendFullProfile(DspProfiles.PROFILE_BO_8OHM_24V, "JBL Boombox (Heavy Kick)");
            sendPacket(DspProfiles.buildSubGainPacket(8000));
            sendPacket(DspProfiles.buildMVBassPacket(65, 40));
            sbBass.setProgress(8000);
            sbMVBass.setProgress(40);
        });

        findViewById(R.id.btnPresetVocal).setOnClickListener(v -> {
            sendFullProfile(DspProfiles.PROFILE_BO_8OHM_24V, "Sweet Vocal");
            sendPacket(DspProfiles.buildSubGainPacket(6000));
            sendPacket(DspProfiles.buildTrebleGainPacket(8500));
            sbBass.setProgress(6000);
            sbTreble.setProgress(8500);
        });

        findViewById(R.id.btnPresetOriginal).setOnClickListener(v -> {
            sendFullProfile(DspProfiles.PROFILE_ORIGINAL, "Cấu hình gốc (Original)");
            sbBass.setProgress(4096);
            sbTreble.setProgress(4096);
            sbMVBass.setProgress(0);
        });

        sbBass.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                double db = 20.0 * Math.log10(Math.max(1, progress) / 4096.0);
                tvBassVal.setText(String.format(Locale.US, "%+.1f dB (%d)", db, progress));
            }

            @Override
            public void onStartTrackingTouch(SeekBar seekBar) {}

            @Override
            public void onStopTrackingTouch(SeekBar seekBar) {
                sendPacket(DspProfiles.buildSubGainPacket(seekBar.getProgress()));
                tvLog.setText("Đã áp dụng Sub Bass Gain: " + seekBar.getProgress());
            }
        });

        sbTreble.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                double db = 20.0 * Math.log10(Math.max(1, progress) / 4096.0);
                tvTrebleVal.setText(String.format(Locale.US, "%+.1f dB (%d)", db, progress));
            }

            @Override
            public void onStartTrackingTouch(SeekBar seekBar) {}

            @Override
            public void onStopTrackingTouch(SeekBar seekBar) {
                sendPacket(DspProfiles.buildTrebleGainPacket(seekBar.getProgress()));
                tvLog.setText("Đã áp dụng Treble Gain: " + seekBar.getProgress());
            }
        });

        sbMVBass.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                tvMVBassVal.setText(progress + "%");
            }

            @Override
            public void onStartTrackingTouch(SeekBar seekBar) {}

            @Override
            public void onStopTrackingTouch(SeekBar seekBar) {
                sendPacket(DspProfiles.buildMVBassPacket(58, seekBar.getProgress()));
                tvLog.setText("Đã áp dụng MVBass: " + seekBar.getProgress() + "%");
            }
        });

        // 8-Band Frequency Tuners Listeners
        setupBandListener(sbFreq62, tvFreq62Val, true, 3, "Sub-Bass 62Hz");
        setupBandListener(sbFreq85, tvFreq85Val, true, 4, "Kick 85Hz");
        setupBandListener(sbFreq125, tvFreq125Val, true, 5, "Mid-Bass 125Hz");
        setupBandListener(sbFreq165, tvFreq165Val, true, 6, "Cắt Ù 165Hz");

        setupBandListener(sbFreq500, tvFreq500Val, false, 1, "Vocal Body 500Hz");
        setupBandListener(sbFreq1k, tvFreq1kVal, false, 2, "Lead Vocal 1kHz");
        setupBandListener(sbFreq2_5k, tvFreq2_5kVal, false, 3, "Vocal Nữ 2.5kHz");
        setupBandListener(sbFreq8k, tvFreq8kVal, false, 5, "Treble Dome 8kHz");
    }

    private void setupBandListener(SeekBar sb, TextView tv, boolean isBass, int filterIdx, String label) {
        sb.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                double db = (progress - 120) * 0.1;
                tv.setText(String.format(Locale.US, "%+.1f dB", db));
            }

            @Override
            public void onStartTrackingTouch(SeekBar seekBar) {}

            @Override
            public void onStopTrackingTouch(SeekBar seekBar) {
                double db = (seekBar.getProgress() - 120) * 0.1;
                byte[] packet;
                if (isBass) {
                    packet = DspProfiles.updateBassFilterGain(filterIdx, db);
                } else {
                    packet = DspProfiles.updateTrebleFilterGain(filterIdx, db);
                }
                sendPacket(packet);
                tvLog.setText("Đã đẩy dải tần " + label + ": " + String.format(Locale.US, "%+.1f dB", db));
            }
        });
    }

    private void handleBluetoothConnectClick() {
        if (!bluetoothDspManager.isBluetoothSupported()) {
            Toast.makeText(this, "Điện thoại này không hỗ trợ Bluetooth!", Toast.LENGTH_SHORT).show();
            return;
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            if (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{
                        Manifest.permission.BLUETOOTH_CONNECT,
                        Manifest.permission.BLUETOOTH_SCAN
                }, REQUEST_BT_PERMISSIONS);
                return;
            }
        }

        if (!bluetoothDspManager.isBluetoothEnabled()) {
            Intent enableBtIntent = new Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE);
            startActivityForResult(enableBtIntent, REQUEST_ENABLE_BT);
            return;
        }

        showPairedDeviceDialog();
    }

    private void showPairedDeviceDialog() {
        Set<BluetoothDevice> pairedDevices = bluetoothDspManager.getPairedDevices();
        if (pairedDevices.isEmpty()) {
            Toast.makeText(this, "Chưa ghép nối với loa Bluetooth! Vào cài đặt điện thoại ghép nối trước.", Toast.LENGTH_LONG).show();
            return;
        }

        final List<BluetoothDevice> deviceList = new ArrayList<>(pairedDevices);
        String[] deviceNames = new String[deviceList.size()];
        for (int i = 0; i < deviceList.size(); i++) {
            BluetoothDevice dev = deviceList.get(i);
            @SuppressLint("MissingPermission")
            String name = dev.getName() != null ? dev.getName() : dev.getAddress();
            deviceNames[i] = name;
        }

        new AlertDialog.Builder(this)
                .setTitle("Chọn loa Best Sound / Bluetooth")
                .setItems(deviceNames, (dialog, which) -> {
                    BluetoothDevice selected = deviceList.get(which);
                    tvLog.setText("Đang kết nối Bluetooth tới: " + deviceNames[which] + "...");
                    bluetoothDspManager.connect(selected);
                })
                .setNegativeButton("Hủy", null)
                .show();
    }

    private void sendPacket(byte[] packet) {
        if (bluetoothDspManager.isConnected()) {
            bluetoothDspManager.sendPacket(packet);
        } else if (usbDspManager.isConnected()) {
            usbDspManager.sendPacket(packet);
        } else {
            Toast.makeText(this, "Chưa kết nối loa qua Bluetooth hoặc USB OTG!", Toast.LENGTH_SHORT).show();
        }
    }

    private void sendFullProfile(byte[] fullProfileBytes, String profileName) {
        progressBar.setVisibility(View.VISIBLE);
        progressBar.setProgress(0);
        tvLog.setText("Đang nạp toàn bộ profile: " + profileName);

        if (bluetoothDspManager.isConnected()) {
            bluetoothDspManager.sendFullProfile(fullProfileBytes, profileName);
        } else if (usbDspManager.isConnected()) {
            usbDspManager.sendFullProfile(fullProfileBytes, profileName);
        } else {
            progressBar.setVisibility(View.GONE);
            Toast.makeText(this, "Chưa kết nối loa qua Bluetooth hoặc USB OTG!", Toast.LENGTH_SHORT).show();
        }
    }

    @Override
    public void onDeviceConnected(String deviceName) {
        viewStatusDot.setBackgroundColor(getResources().getColor(R.color.status_green));
        tvStatus.setText("ĐÃ KẾT NỐI (USB OTG): " + deviceName);
        tvLog.setText("Sẵn sàng giao tiếp với chip MVSilicon BP1048B2 qua USB OTG.");
    }

    @Override
    public void onDeviceDisconnected() {
        if (!bluetoothDspManager.isConnected()) {
            viewStatusDot.setBackgroundColor(getResources().getColor(R.color.status_red));
            tvStatus.setText("Mất kết nối USB với loa!");
        }
    }

    @Override
    public void onBtConnected(String deviceName) {
        viewStatusDot.setBackgroundColor(getResources().getColor(R.color.status_green));
        tvStatus.setText("ĐÃ KẾT NỐI (BLUETOOTH): " + deviceName);
        tvLog.setText("Sẵn sàng giao tiếp không dây với loa qua Bluetooth SPP.");
    }

    @Override
    public void onBtDisconnected() {
        if (!usbDspManager.isConnected()) {
            viewStatusDot.setBackgroundColor(getResources().getColor(R.color.status_red));
            tvStatus.setText("Mất kết nối Bluetooth với loa!");
        }
    }

    @Override
    public void onTransmissionProgress(int currentPacket, int totalPackets) {
        progressBar.setVisibility(View.VISIBLE);
        progressBar.setMax(totalPackets);
        progressBar.setProgress(currentPacket);
        tvLog.setText(String.format(Locale.US, "Đang nạp gói tin USB: %d/%d", currentPacket, totalPackets));
    }

    @Override
    public void onBtTransmissionProgress(int currentPacket, int totalPackets) {
        progressBar.setVisibility(View.VISIBLE);
        progressBar.setMax(totalPackets);
        progressBar.setProgress(currentPacket);
        tvLog.setText(String.format(Locale.US, "Đang nạp gói tin Bluetooth: %d/%d", currentPacket, totalPackets));
    }

    @Override
    public void onTransmissionComplete(String message) {
        progressBar.setVisibility(View.GONE);
        tvLog.setText("✓ " + message);
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
    }

    @Override
    public void onBtTransmissionComplete(String message) {
        progressBar.setVisibility(View.GONE);
        tvLog.setText("✓ " + message);
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
    }

    @Override
    public void onError(String error) {
        progressBar.setVisibility(View.GONE);
        tvLog.setText("Lỗi: " + error);
        Toast.makeText(this, error, Toast.LENGTH_LONG).show();
    }

    @Override
    public void onBtError(String error) {
        progressBar.setVisibility(View.GONE);
        tvLog.setText("Lỗi: " + error);
        Toast.makeText(this, error, Toast.LENGTH_LONG).show();
    }

    @Override
    protected void onResume() {
        super.onResume();
        configureAudioRouting();
    }

    private void setupAudioDeviceListener() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            AudioManager am = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
            if (am != null) {
                am.registerAudioDeviceCallback(new AudioDeviceCallback() {
                    @Override
                    public void onAudioDevicesAdded(AudioDeviceInfo[] addedDevices) {
                        configureAudioRouting();
                    }

                    @Override
                    public void onAudioDevicesRemoved(AudioDeviceInfo[] removedDevices) {
                        configureAudioRouting();
                    }
                }, null);
            }
        }
    }

    public void configureAudioRouting() {
        try {
            AudioManager am = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
            if (am != null) {
                // Ensure MODE_NORMAL so media & audio graph streams over Bluetooth A2DP stereo at full fidelity
                am.setMode(AudioManager.MODE_NORMAL);
                // Explicitly stop Bluetooth SCO handsfree profile to ensure phone's built-in mic is ALWAYS used
                am.stopBluetoothSco();
                am.setBluetoothScoOn(false);

                boolean isBt = isBluetoothOutputConnected();
                // If no bluetooth, output through phone speaker
                am.setSpeakerphoneOn(!isBt);

                notifyJsAudioRouteChanged();
            }
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    public boolean isBluetoothOutputConnected() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            AudioManager am = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
            if (am != null) {
                AudioDeviceInfo[] devices = am.getDevices(AudioManager.GET_DEVICES_OUTPUTS);
                for (AudioDeviceInfo dev : devices) {
                    int type = dev.getType();
                    if (type == AudioDeviceInfo.TYPE_BLUETOOTH_A2DP ||
                        type == AudioDeviceInfo.TYPE_BLE_SPEAKER ||
                        type == AudioDeviceInfo.TYPE_BLE_HEADSET) {
                        return true;
                    }
                }
            }
        }
        return false;
    }

    private void notifyJsAudioRouteChanged() {
        runOnUiThread(() -> {
            try {
                boolean isBt = isBluetoothOutputConnected();
                String js = "if (typeof onAudioRouteChanged === 'function') { onAudioRouteChanged(" + isBt + "); }";
                if (webViewStudio != null) {
                    webViewStudio.evaluateJavascript(js, null);
                }
            } catch (Exception ignored) {}
        });
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        // Keep KaraokeForegroundService running in background when activity is closed or screen is off
        if (otgController != null) otgController.destroy();
        usbDspManager.destroy();
        bluetoothDspManager.destroy();
    }
}
