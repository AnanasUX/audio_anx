# An Sound Audio DSP Suite — MVSilicon BP1048B2 (3-Way & Karaoke)

Hệ thống phần mềm điều khiển, tinh chỉnh và đồng bộ cấu hình DSP cho mạch công suất tích hợp **MVSilicon BP1048B2** (Firmware `0.3.4`, Effect `2.45.5`, chuẩn **ACPWorkbench V2.44.2**), tối ưu chuyên biệt cho cấu hình loa **3-Way Quốc Doàn Audio 70W x 2**.

---

## 1. Thông số phần cứng mục tiêu (3-Way Spec)
| Kênh | Củ loa / Đặc tính | Cấu hình bảo vệ & Phân tần chuẩn |
| :--- | :--- | :--- |
| **Subwoofer** | 5" JBL Boombox 4 (thùng 5L) | HPF `60 Hz` (LR24) · LPF `150 Hz` (LR24) · Notch `110 Hz` chống ù thùng 5L · `DRC -3.0 dBFS` |
| **Mid** | Pioneer S-EV61V `6Ω` | HPF `150 Hz` (LR24) · `Mid Gain = 4600` (`0x99`) · `DRC -3.0 dBFS` (`0x9C`) |
| **Treble** | Ford JX7T-18808-BA `4Ω 5W` (tụ `3µF`) | HPF `9500 Hz` (LR24) · **Giới hạn an toàn `Treble Gain <= 4600` (`0x98`)** |
| **Lưu ý Type-C** | Cổng Type-C mạch bỏ chân 5V VBUS | **Bật nguồn pin của loa trước** rồi mới cắm cáp Type-C vào PC hoặc điện thoại OTG |

---

## 2. Ứng dụng PC: An Sound ACP Pro PC (`An_Sound_ACP_Pro_PC.py`)
Chạy trực tiếp trên Windows với **Python 3.11+ chuẩn (không cần cài thư viện ngoài)**, giao diện Pro Audio Dark Studio mở độc lập bằng **Google Chrome (`--app`)**.

* **File chính:**
  * `An_Sound_ACP_Pro_PC.py` — Backend Win32 USB HID/COM (`hid.dll`, `setupapi.dll`, `kernel32.dll`), HTTP API server, bộ mã hóa khung `[0xA5, 0x5A, Effect_ID, Length, 0xFF, Payload_LE, 0x16]` cho **21 khối DSP (`0x81`–`0x9D`)**, đồng bộ `ACPWorkbench.ini` & khởi chạy `ACPWorkbench_V2.44.2.exe`.
  * `acp_pro_ui.html` — Giao diện Web-Desktop HiDPI:
    * **Equalizer (PEQ 10-Band):** Đồ thị kéo thả trực tiếp các điểm `1–10`, cuộn chuột chỉnh `Q`, so sánh `A | B`, `↺ Flat`, `Ctrl+Z` (Undo) / `Ctrl+Y` (Redo) tới 60 bước.
    * **3-Way Crossover, MVBass (`0x87/0x88`), Exciter (`0x89`), Noise Gate (`0x85`), Delay (`0x9D`), DRC (`0x93/0x9B/0x9C`), Input Gains (`0x81–0x84, 0x92`).**
    * **Board Info & Smart Auto-Tune:** Khai thác sâu toàn bộ thông số `.INI` (`0x00`–`0xFC`) và 3 chế độ Auto-Tune 1-Click.
    * **✨ Gemini DSP AI:** Kết nối Gemini API (`AIza...` / `AQ....`), Ollama local, hoặc **Chrome Gemini + Neon Check**; trò chuyện tự nhiên và chỉ áp dụng thông số đề xuất khi người dùng bấm **`✅ Áp dụng cấu hình này`**.
  * `Launch_An_Sound_ACP_Pro_PC.bat` — File chạy nhanh trên Windows.
  * `test_an_sound_acp_pro_pc.py` — Bộ kiểm thử `unittest` (7/7 tests passed).

---

## 3. Ứng dụng Android USB OTG (`android_app/`)
Hỗ trợ 2 flavor APK đã build và ký v2 (`apksigner`):
* `An_Sound_DSP.apk` (`dspStudio` — điều khiển DSP MVSilicon qua cáp USB OTG Type-C → Type-C):
  * `usb/MvsiliconPacket.java` & `usb/UsbOtgController.java`: Đóng gói/giải mã khung `0xA5 0x5A ... 0x16`, hỗ trợ CDC-ACM (`115200 8N1`), USB HID và Bulk fallback.
  * `config/AcpConfigParser.java` & `config/Dsp3WayPresets.java`: Parse/serialize `.ini` ACPWorkbench V2.44.2, xuất mảng hex `.c`, tích hợp preset `3-Way Spec Matched` và `Factory Style (DynamicEQ)`.
  * `ui/DspOtgBridge.java` & `assets/otg/index.html`: Giao diện điều khiển 3-Way OTG + cảnh báo `Treble Gain > 4600`.
* `An_Sound_Karaoke.apk` (`karaokeLive`).

---

## 4. Các Preset `.INI` chuẩn 3-Way kèm theo
* `dsp_3way_spec_matched.ini` — Cấu hình cân bằng chuẩn theo thông số củ loa.
* `dsp_factory_style_3way.ini` — Phong cách DynamicEQ nghe nhỏ đầy tiếng.
* `dsp_3way_bright_treble_final.ini` — Tăng độ tơi sáng dải cao trong ngưỡng an toàn.
* `dsp_punchy_bass_sweet_vocal.ini` / `.c` — Trầm gọn chắc lực, trung âm ngọt.

---

## 5. Lệnh kiểm thử & Build
```powershell
# 1. Chạy ứng dụng PC
python An_Sound_ACP_Pro_PC.py

# 2. Chạy unit test ứng dụng PC
python -m unittest -v test_an_sound_acp_pro_pc.py

# 3. Chạy unit test & build APK Android
gradle -p android_app testDspStudioDebugUnitTest testKaraokeLiveDebugUnitTest
gradle -p android_app assembleDebug
```
