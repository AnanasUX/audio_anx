package com.bestsound.dsp.usb;

import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.hardware.usb.UsbConstants;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbDeviceConnection;
import android.hardware.usb.UsbEndpoint;
import android.hardware.usb.UsbInterface;
import android.hardware.usb.UsbManager;
import android.os.Build;
import android.util.Log;

import java.util.HashMap;
import java.util.List;
import java.util.Locale;

/**
 * USB OTG Controller for MVSilicon BP1048B2 / ACPWorkbench protocol.
 * Supports USB CDC-ACM (Serial), USB HID Interrupt/Control, and raw Bulk endpoints.
 * Note: Type-C port on board has VBUS 5V disconnected; speaker battery must be powered ON before connecting.
 */
public class UsbOtgController {
    private static final String TAG = "UsbOtgController";
    private static final String ACTION_USB_PERMISSION = "com.bestsound.dsp.USB_OTG_PERMISSION";

    public interface OtgCallback {
        void onDeviceAttached(String name, int vid, int pid, String mode);
        void onDeviceDetached();
        void onPacketLog(String direction, String hexSummary);
        void onRxPacket(MvsiliconPacket packet);
        void onError(String message);
    }

    private final Context context;
    private final UsbManager usbManager;
    private OtgCallback callback;

    private UsbDevice activeDevice;
    private UsbDeviceConnection connection;
    private UsbInterface dataInterface;
    private UsbEndpoint epOut;
    private UsbEndpoint epIn;
    private String transportMode = "NONE";
    private volatile boolean rxRunning = false;
    private Thread rxThread;
    private boolean receiversRegistered = false;

    private final BroadcastReceiver usbReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context ctx, Intent intent) {
            String action = intent.getAction();
            if (ACTION_USB_PERMISSION.equals(action)) {
                synchronized (UsbOtgController.this) {
                    UsbDevice dev = intent.getParcelableExtra(UsbManager.EXTRA_DEVICE);
                    if (intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false) && dev != null) {
                        openDevice(dev);
                    } else if (callback != null) {
                        callback.onError("Từ chối quyền truy cập USB OTG.");
                    }
                }
            } else if (UsbManager.ACTION_USB_DEVICE_ATTACHED.equals(action)) {
                scanAndConnect();
            } else if (UsbManager.ACTION_USB_DEVICE_DETACHED.equals(action)) {
                UsbDevice dev = intent.getParcelableExtra(UsbManager.EXTRA_DEVICE);
                if (dev != null && activeDevice != null && dev.getDeviceId() == activeDevice.getDeviceId()) {
                    disconnect();
                }
            }
        }
    };

    public UsbOtgController(Context context) {
        this.context = context.getApplicationContext();
        this.usbManager = (UsbManager) this.context.getSystemService(Context.USB_SERVICE);
        registerReceivers();
    }

    public void setCallback(OtgCallback cb) {
        this.callback = cb;
    }

    public boolean isConnected() {
        return connection != null && epOut != null;
    }

    public String getTransportMode() {
        return transportMode;
    }

    private void registerReceivers() {
        if (receiversRegistered) return;
        IntentFilter filter = new IntentFilter(ACTION_USB_PERMISSION);
        filter.addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED);
        filter.addAction(UsbManager.ACTION_USB_DEVICE_DETACHED);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            context.registerReceiver(usbReceiver, filter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            context.registerReceiver(usbReceiver, filter);
        }
        receiversRegistered = true;
    }

    public void scanAndConnect() {
        if (usbManager == null) {
            if (callback != null) callback.onError("Thiết bị không hỗ trợ USB OTG.");
            return;
        }
        HashMap<String, UsbDevice> devices = usbManager.getDeviceList();
        if (devices == null || devices.isEmpty()) {
            if (callback != null) {
                callback.onError("Chưa thấy loa USB OTG. Hãy bật nguồn pin loa trước rồi cắm cáp Type-C -> Type-C.");
            }
            return;
        }

        // Prefer MVSilicon / CDC / HID audio device
        UsbDevice chosen = null;
        for (UsbDevice dev : devices.values()) {
            chosen = dev;
            if (hasCompatibleEndpoint(dev)) break;
        }
        if (chosen == null) return;

        if (usbManager.hasPermission(chosen)) {
            openDevice(chosen);
        } else {
            int flags = Build.VERSION.SDK_INT >= Build.VERSION_CODES.S
                    ? PendingIntent.FLAG_MUTABLE
                    : PendingIntent.FLAG_UPDATE_CURRENT;
            PendingIntent pi = PendingIntent.getBroadcast(context, 0, new Intent(ACTION_USB_PERMISSION), flags);
            usbManager.requestPermission(chosen, pi);
        }
    }

    private boolean hasCompatibleEndpoint(UsbDevice dev) {
        for (int i = 0; i < dev.getInterfaceCount(); i++) {
            UsbInterface intf = dev.getInterface(i);
            int cls = intf.getInterfaceClass();
            if (cls == UsbConstants.USB_CLASS_CDC_DATA ||
                cls == UsbConstants.USB_CLASS_COMM ||
                cls == UsbConstants.USB_CLASS_HID ||
                cls == UsbConstants.USB_CLASS_VENDOR_SPEC) {
                return true;
            }
        }
        return false;
    }

    private synchronized void openDevice(UsbDevice dev) {
        disconnect();
        UsbDeviceConnection conn = usbManager.openDevice(dev);
        if (conn == null) {
            if (callback != null) callback.onError("Không mở được kết nối USB (kiểm tra nguồn pin loa).");
            return;
        }

        // 1. Try CDC-ACM Data Interface first (Bulk IN/OUT)
        UsbInterface selectedIntf = null;
        UsbEndpoint out = null;
        UsbEndpoint in = null;
        String mode = "RAW_BULK";

        for (int i = 0; i < dev.getInterfaceCount(); i++) {
            UsbInterface intf = dev.getInterface(i);
            int cls = intf.getInterfaceClass();
            UsbEndpoint candOut = null, candIn = null;
            for (int e = 0; e < intf.getEndpointCount(); e++) {
                UsbEndpoint ep = intf.getEndpoint(e);
                if (ep.getType() == UsbConstants.USB_ENDPOINT_XFER_BULK ||
                    ep.getType() == UsbConstants.USB_ENDPOINT_XFER_INT) {
                    if (ep.getDirection() == UsbConstants.USB_DIR_OUT) candOut = ep;
                    else if (ep.getDirection() == UsbConstants.USB_DIR_IN) candIn = ep;
                }
            }
            if (candOut != null) {
                selectedIntf = intf;
                out = candOut;
                in = candIn;
                if (cls == UsbConstants.USB_CLASS_CDC_DATA) {
                    mode = "CDC_SERIAL";
                    break;
                } else if (cls == UsbConstants.USB_CLASS_HID) {
                    mode = "USB_HID";
                }
            }
        }

        if (selectedIntf == null || out == null || !conn.claimInterface(selectedIntf, true)) {
            conn.close();
            if (callback != null) callback.onError("Không tìm thấy endpoint giao tiếp dữ liệu trên bo mạch.");
            return;
        }

        // Configure CDC Line Coding (115200 8N1) & DTR/RTS if CDC-ACM
        if ("CDC_SERIAL".equals(mode)) {
            configureCdcSerial(conn);
        }

        this.activeDevice = dev;
        this.connection = conn;
        this.dataInterface = selectedIntf;
        this.epOut = out;
        this.epIn = in;
        this.transportMode = mode;

        String devName = dev.getProductName() != null ? dev.getProductName() : dev.getDeviceName();
        if (callback != null) {
            callback.onDeviceAttached(devName, dev.getVendorId(), dev.getProductId(), mode);
        }

        startRxLoop();
    }

    private void configureCdcSerial(UsbDeviceConnection conn) {
        try {
            // SET_LINE_CODING: 115200 baud (0x0001C200 LE), 1 stop bit, no parity, 8 data bits
            byte[] lineCoding = new byte[]{
                    (byte) 0x00, (byte) 0xC2, (byte) 0x01, (byte) 0x00,
                    0x00, 0x00, 0x08
            };
            conn.controlTransfer(0x21, 0x20, 0, 0, lineCoding, lineCoding.length, 500);
            // SET_CONTROL_LINE_STATE: DTR=1, RTS=1
            conn.controlTransfer(0x21, 0x22, 0x03, 0, null, 0, 500);
        } catch (Exception e) {
            Log.w(TAG, "CDC control transfer optional warning", e);
        }
    }

    private void startRxLoop() {
        if (epIn == null) return;
        rxRunning = true;
        rxThread = new Thread(() -> {
            byte[] rxBuf = new byte[Math.max(64, epIn.getMaxPacketSize())];
            while (rxRunning && connection != null) {
                try {
                    int n = connection.bulkTransfer(epIn, rxBuf, rxBuf.length, 250);
                    if (n > 0) {
                        byte[] chunk = new byte[n];
                        System.arraycopy(rxBuf, 0, chunk, 0, n);
                        if (callback != null) {
                            callback.onPacketLog("RX", formatShortHex(chunk));
                            List<MvsiliconPacket> frames = MvsiliconPacket.parseStream(chunk);
                            for (MvsiliconPacket p : frames) {
                                callback.onRxPacket(p);
                            }
                        }
                    }
                } catch (Exception e) {
                    if (rxRunning && callback != null) {
                        callback.onError("Mất kết nối RX USB: " + e.getMessage());
                    }
                    break;
                }
            }
        }, "MvsiliconUsbRxThread");
        rxThread.start();
    }

    public boolean sendPacket(MvsiliconPacket packet) {
        if (packet == null) return false;
        return sendRaw(packet.toBytes());
    }

    public synchronized boolean sendRaw(byte[] data) {
        if (connection == null || epOut == null || data == null || data.length == 0) {
            return false;
        }
        try {
            int maxPkt = Math.max(64, epOut.getMaxPacketSize());
            int offset = 0;
            while (offset < data.length) {
                int len = Math.min(maxPkt, data.length - offset);
                byte[] chunk = new byte[len];
                System.arraycopy(data, offset, chunk, 0, len);
                int sent = connection.bulkTransfer(epOut, chunk, len, 600);
                if (sent < 0) {
                    if (callback != null) callback.onError("Lỗi ghi gói tin USB OTG (sent=" + sent + ")");
                    return false;
                }
                offset += sent;
            }
            if (callback != null) {
                callback.onPacketLog("TX", formatShortHex(data));
            }
            return true;
        } catch (Exception e) {
            if (callback != null) callback.onError("Lỗi truyền USB: " + e.getMessage());
            return false;
        }
    }

    private String formatShortHex(byte[] data) {
        int show = Math.min(data.length, 16);
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < show; i++) {
            if (i > 0) sb.append(' ');
            sb.append(String.format(Locale.US, "%02X", data[i] & 0xFF));
        }
        if (data.length > show) sb.append(" ... (").append(data.length).append("B)");
        return sb.toString();
    }

    public synchronized void disconnect() {
        rxRunning = false;
        if (rxThread != null) {
            try { rxThread.join(250); } catch (InterruptedException ignored) {}
            rxThread = null;
        }
        if (connection != null) {
            try {
                if (dataInterface != null) connection.releaseInterface(dataInterface);
                connection.close();
            } catch (Exception ignored) {}
            connection = null;
        }
        dataInterface = null;
        epOut = null;
        epIn = null;
        activeDevice = null;
        transportMode = "NONE";
        if (callback != null) callback.onDeviceDetached();
    }

    public void destroy() {
        disconnect();
        if (receiversRegistered) {
            try { context.unregisterReceiver(usbReceiver); } catch (Exception ignored) {}
            receiversRegistered = false;
        }
    }
}
