"""
Program Monitoring & Kontrol Alarm PLC Mitsubishi Q03UDVCPU (Multi-Robot: KUKA, Nachi, Hyundai)
Menggunakan komunikasi Built-in Ethernet (MC Protocol 3E Frame - pymcprotocol)

Fitur Utama:
1. Definisi Alamat Mudah: Cukup tulis alamat seperti "M1501" (tanpa perlu hitung index manual).
2. Multi-Block Batch Read: Membaca ratusan alamat alarm lintas grup (General, KUKA, Nachi, Hyundai) dengan cepat.
3. Pembacaan Word Register (D): Membaca kode error numerik dari robot jika disimpan di register D.
4. Pengiriman Data (Write Bit & Word): Fungsi siap pakai untuk mengirim sinyal (misal Reset Error) dari Python ke PLC.
5. Pencatatan History SQLite (Rising & Falling Edge) + REST API FastAPI (Opsional).
6. Penghentian Program Aman: Tekan [Q], [ESC], atau [Ctrl+C] kapan saja untuk mematikan program.
"""

import msvcrt
import sqlite3
import sys
import threading
import time
from datetime import datetime

try:
    import pymcprotocol
except ImportError:
    print("❌ Library 'pymcprotocol' belum terinstal. Jalankan: pip install pymcprotocol")
    sys.exit(1)

# ==============================================================================
# 1. KONFIGURASI KONEKSI PLC MITSUBISHI Q03UDVCPU
# ==============================================================================
PLC_IP = "192.168.3.39"   # Ganti dengan IP Address PLC Q03UDVCPU di pabrik
PLC_PORT = 5002           # Port Decimal sesuai Open Setting GX Works2 (5002 Dec = 138A Hex)
POLL_INTERVAL = 0.2       # Siklus pembacaan: 0.2 detik (200 ms)
DB_FILE = "alarm_history_multirobot.db"

# ==============================================================================
# 2. DAFTAR ALAMAT ALARM BIT (M) — CUKUP TULIS ALAMAT "Mxxxx"
# ==============================================================================
# Anda dan tim cukup menambahkan alamat M di bawah ini tanpa perlu menghitung
# index secara manual. Sistem otomatis mengelompokkan pembacaan (Batch Read).
ALARM_DEFINITIONS = {
    # --- GRUP 1: ALARM UMUM LINE / SAFETY PLC ---
    "M1501": {"robot": "MAIN_PLC", "code": "ALM-001", "name": "Emergency Stop Line Pressed", "severity": "CRITICAL"},
    "M1502": {"robot": "MAIN_PLC", "code": "ALM-002", "name": "Safety Door Interlock Open", "severity": "CRITICAL"},
    "M1531": {"robot": "MAIN_PLC", "code": "ALM-031", "name": "Main Air Pressure Low", "severity": "WARNING"},

    # --- GRUP 2: ALARM ROBOT KUKA (Contoh blok M1600 - M1699) ---
    "M1600": {"robot": "KUKA", "code": "KUKA-E01", "name": "KUKA Emergency Stop", "severity": "CRITICAL"},
    "M1601": {"robot": "KUKA", "code": "KUKA-E02", "name": "KUKA Servo Drive Fault", "severity": "CRITICAL"},
    "M1602": {"robot": "KUKA", "code": "KUKA-E03", "name": "KUKA Collision Detection Triggered", "severity": "CRITICAL"},
    "M1603": {"robot": "KUKA", "code": "KUKA-W01", "name": "KUKA Gripper Sensor Timeout", "severity": "WARNING"},

    # --- GRUP 3: ALARM ROBOT NACHI (Contoh blok M1700 - M1799) ---
    "M1700": {"robot": "NACHI", "code": "NACHI-E01", "name": "Nachi Robot Major Alarm", "severity": "CRITICAL"},
    "M1701": {"robot": "NACHI", "code": "NACHI-E02", "name": "Nachi Encoder Battery Low", "severity": "WARNING"},
    "M1702": {"robot": "NACHI", "code": "NACHI-E03", "name": "Nachi Overtravel Limit", "severity": "CRITICAL"},

    # --- GRUP 4: ALARM ROBOT HYUNDAI (Contoh blok M1800 - M1899) ---
    "M1800": {"robot": "HYUNDAI", "code": "HD-E01", "name": "Hyundai Robot Controller Fault", "severity": "CRITICAL"},
    "M1801": {"robot": "HYUNDAI", "code": "HD-E02", "name": "Hyundai Welding / Tool Error", "severity": "WARNING"},
    "M1802": {"robot": "HYUNDAI", "code": "HD-E03", "name": "Hyundai Communication Heartbeat Lost", "severity": "CRITICAL"},
}

# ==============================================================================
# 3. DAFTAR REGISTER WORD (D) UNTUK KODE ERROR NUMERIK ROBOT (OPSIONAL)
# ==============================================================================
# Jika PLC menyimpan nomor kode error spesifik dari robot di Data Register (D):
# Nilai 0 = Normal (Tidak ada error), Nilai > 0 = Kode Error Aktif
ROBOT_ERROR_REGISTERS = {
    "D1600": {"robot": "KUKA",    "description": "KUKA Active Error Code Number"},
    "D1700": {"robot": "NACHI",   "description": "Nachi Active Error Code Number"},
    "D1800": {"robot": "HYUNDAI", "description": "Hyundai Active Error Code Number"},
}


# ==============================================================================
# 4. OTOMATISASI PEMBAGIAN BLOK BATCH READ (AUTOMATIC ADDRESS MAPPER)
# ==============================================================================
def build_read_blocks(alarm_dict, max_span=120):
    """
    Mengelompokkan daftar alamat seperti 'M1501', 'M1531', 'M1600' menjadi
    beberapa blok pembacaan berdekatan (Batch Read) secara otomatis.

    Cara Kerja Rumus Index:
    - Setiap alamat dipisahkan huruf device ('M') dan angkanya (1501).
    - Jika sebuah blok dimulai dari head_address = 'M1500', maka:
      index = nomor_alamat - 1500 (contoh: M1501 -> 1501 - 1500 = index 1).
    """
    parsed = []
    for addr, meta in alarm_dict.items():
        dev_type = addr[0].upper()
        dev_num = int(addr[1:])
        parsed.append((dev_type, dev_num, addr, meta))

    parsed.sort(key=lambda x: (x[0], x[1]))

    blocks = []
    current_block = None

    for dev_type, dev_num, addr, meta in parsed:
        # Bulatkan alamat awal ke kelipatan 10 terdekat ke bawah (misal 1501 -> 1500)
        base_num = (dev_num // 10) * 10
        if (
            current_block is None
            or current_block["dev_type"] != dev_type
            or (dev_num - current_block["start_num"]) >= max_span
        ):
            current_block = {
                "dev_type": dev_type,
                "start_num": base_num,
                "head_device": f"{dev_type}{base_num}",
                "end_num": dev_num,
                "items": {},
            }
            blocks.append(current_block)

        # Rumus otomatis menentukan posisi index di dalam array hasil batchread:
        offset_index = dev_num - current_block["start_num"]
        current_block["items"][offset_index] = {"address": addr, **meta}
        if dev_num > current_block["end_num"]:
            current_block["end_num"] = dev_num

    for b in blocks:
        b["read_size"] = (b["end_num"] - b["start_num"]) + 1

    return blocks


READ_BLOCKS = build_read_blocks(ALARM_DEFINITIONS)
previous_bit_states = {addr: 0 for addr in ALARM_DEFINITIONS}
previous_word_states = {addr: 0 for addr in ROBOT_ERROR_REGISTERS}
active_alarms_live = {}
plc_lock = threading.Lock()


# ==============================================================================
# 5. FUNGSI MENGIRIM DATA DARI PYTHON KE PLC (WRITE BIT & WRITE WORD)
# ==============================================================================
def write_bit_to_plc(plc_client, device_address: str, value: int):
    """
    Mengirim nilai Bit (0 atau 1) ke alamat PLC (misal 'M2000' untuk Reset Alarm).
    Contoh pemakaian:
        write_bit_to_plc(plc, "M2000", 1)  # Nyalakan bit M2000 (ON)
        write_bit_to_plc(plc, "M2000", 0)  # Matikan bit M2000 (OFF)
    """
    bit_val = 1 if value else 0
    with plc_lock:
        plc_client.batchwrite_bitunits(headdevice=device_address, values=[bit_val])
    print(f"📤 [WRITE BIT] Berhasil mengirim nilai {bit_val} ke alamat {device_address}")


def pulse_bit_to_plc(plc_client, device_address: str, duration_sec: float = 0.5):
    """
    Mengirim sinyal tombol sesaat / Momentary Pulse (ON lalu OFF otomatis)
    Sangat berguna untuk sinyal Reset Error Robot atau Acknowledge Alarm.
    """
    write_bit_to_plc(plc_client, device_address, 1)
    time.sleep(duration_sec)
    write_bit_to_plc(plc_client, device_address, 0)


def write_word_to_plc(plc_client, device_address: str, values: list[int]):
    """
    Mengirim nilai angka 16-bit (Word) ke register PLC (misal 'D2000').
    Contoh pemakaian:
        write_word_to_plc(plc, "D2000", [105])        # Tulis 1 register (D2000 = 105)
        write_word_to_plc(plc, "D2000", [10, 20, 30]) # Tulis 3 register berurutan (D2000..D2002)
    """
    with plc_lock:
        plc_client.batchwrite_wordunits(headdevice=device_address, values=values)
    print(f"📤 [WRITE WORD] Berhasil mengirim {values} mulai dari alamat {device_address}")


# ==============================================================================
# 6. SETUP DATABASE SQLITE UNTUK HISTORY ALARM
# ==============================================================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alarm_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            robot TEXT,
            alarm_code TEXT,
            address TEXT,
            alarm_name TEXT,
            severity TEXT,
            status TEXT,
            triggered_at TEXT,
            cleared_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def log_alarm_triggered(address, info):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO alarm_logs (robot, alarm_code, address, alarm_name, severity, status, triggered_at, cleared_at)
        VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, NULL)
        """,
        (info["robot"], info["code"], address, info["name"], info["severity"], now),
    )
    conn.commit()
    conn.close()
    print(f"🚨 [ALARM ON]  [{info['robot']}] {address} ({info['code']} - {info['name']}) pada {now}")


def log_alarm_cleared(address, info):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE alarm_logs
        SET status = 'CLEARED', cleared_at = ?
        WHERE address = ? AND status = 'ACTIVE'
        """,
        (now, address),
    )
    conn.commit()
    conn.close()
    print(f"✅ [ALARM OFF] [{info['robot']}] {address} ({info['name']}) kembali NORMAL pada {now}")


# ==============================================================================
# 7. ENGINE UTAMA POLLING PLC & KEYBOARD LISTENER
# ==============================================================================
stop_event = threading.Event()
plc_instance = pymcprotocol.Type3E()


def keyboard_listener():
    """Mendengarkan tombol Q, ESC, atau R (Contoh kirim sinyal Reset ke M2000)."""
    while not stop_event.is_set():
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ("q", "Q", "\x1b"):
                key_name = "ESC" if ch == "\x1b" else ch.upper()
                print(f"\n🛑 Tombol [{key_name}] ditekan — mematikan program...")
                stop_event.set()
                break
            elif ch in ("r", "R"):
                # Contoh fitur kirim sinyal Reset dari keyboard ke PLC (alamat M2000)
                if plc_instance._is_connected:
                    print("\n🔄 Mengirim pulsa Reset Alarm ke PLC (M2000)...")
                    try:
                        pulse_bit_to_plc(plc_instance, "M2000", 0.3)
                    except Exception as e:
                        print(f"⚠️ Gagal mengirim sinyal Reset: {e}")
                else:
                    print("\n⚠️ Belum terhubung ke PLC, tidak dapat mengirim Reset.")
        stop_event.wait(0.1)


def run_plc_monitor():
    init_db()

    print("=" * 75)
    print(" SISTEM MONITORING ALARM PLC MITSUBISHI Q03UDVCPU (KUKA, NACHI, HYUNDAI)")
    print("=" * 75)
    print(f"Target PLC : {PLC_IP}:{PLC_PORT} (MC Protocol 3E Frame Binary)")
    print(f"Total Bit  : {len(ALARM_DEFINITIONS)} alamat dalam {len(READ_BLOCKS)} blok pembacaan:")
    for idx, b in enumerate(READ_BLOCKS, 1):
        print(f"  - Blok {idx}: Head={b['head_device']}, Jumlah Baca={b['read_size']} bit ({len(b['items'])} tag aktif)")
    print("-" * 75)
    print("💡 Kontrol Keyboard:")
    print("   - Tekan [Q] atau [ESC] atau [Ctrl+C] : Mematikan program dengan aman")
    print("   - Tekan [R]                          : Contoh kirim sinyal Reset ke M2000")
    print("=" * 75)

    kb_thread = threading.Thread(target=keyboard_listener, daemon=True)
    kb_thread.start()

    try:
        while not stop_event.is_set():
            try:
                if not plc_instance._is_connected:
                    print(f"⏳ Menghubungkan ke PLC Q03UDVCPU ({PLC_IP}:{PLC_PORT})...")
                    with plc_lock:
                        plc_instance.connect(PLC_IP, PLC_PORT)
                    print("✅ Berhasil terhubung ke PLC Mitsubishi Q03UDVCPU!")

                # 1. Baca semua blok Bit Alarm (M)
                for block in READ_BLOCKS:
                    with plc_lock:
                        bits = plc_instance.batchread_bitunits(
                            headdevice=block["head_device"],
                            readsize=block["read_size"],
                        )

                    for offset_idx, info in block["items"].items():
                        addr = info["address"]
                        current_val = int(bits[offset_idx])
                        prev_val = previous_bit_states[addr]

                        # Deteksi Rising Edge (0 -> 1 : Alarm baru menyala)
                        if current_val == 1 and prev_val == 0:
                            log_alarm_triggered(addr, info)
                            active_alarms_live[addr] = {
                                **info,
                                "triggered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            }

                        # Deteksi Falling Edge (1 -> 0 : Alarm sudah di-reset/normal)
                        elif current_val == 0 and prev_val == 1:
                            log_alarm_cleared(addr, info)
                            active_alarms_live.pop(addr, None)

                        previous_bit_states[addr] = current_val

                # 2. Baca Word Register (D) untuk Kode Error Numerik Robot
                for d_addr, d_meta in ROBOT_ERROR_REGISTERS.items():
                    with plc_lock:
                        word_vals = plc_instance.batchread_wordunits(headdevice=d_addr, readsize=1)
                    err_code_num = int(word_vals[0])
                    prev_code_num = previous_word_states[d_addr]

                    if err_code_num != prev_code_num:
                        if err_code_num > 0:
                            print(
                                f"🔢 [ROBOT CODE] [{d_meta['robot']}] {d_addr} berubah menjadi "
                                f"Kode Error: {err_code_num} ({d_meta['description']})"
                            )
                        else:
                            print(f"✅ [ROBOT CODE] [{d_meta['robot']}] {d_addr} kembali ke 0 (Normal)")
                        previous_word_states[d_addr] = err_code_num

                stop_event.wait(POLL_INTERVAL)

            except Exception as e:
                if stop_event.is_set():
                    break
                print(f"⚠️ Koneksi PLC terputus / gagal membaca: {e}")
                try:
                    with plc_lock:
                        plc_instance.close()
                except Exception:
                    pass
                print("   Mencoba hubungkan ulang dalam 3 detik... (Tekan [Q] untuk keluar)")
                stop_event.wait(3.0)

    except KeyboardInterrupt:
        print("\n🛑 Ctrl+C ditekan — mematikan program...")
    finally:
        stop_event.set()
        try:
            if plc_instance._is_connected:
                with plc_lock:
                    plc_instance.close()
                print("🔌 Koneksi socket PLC telah ditutup.")
        except Exception:
            pass
        print("✅ Program telah dimatikan dengan aman.")


if __name__ == "__main__":
    run_plc_monitor()
