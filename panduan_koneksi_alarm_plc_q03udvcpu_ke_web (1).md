# Dokumentasi Proyek: Sistem Monitoring & History Alarm PLC Mitsubishi Q03UDVCPU ke Web

Dokumentasi ini berisi panduan lengkap untuk menghubungkan PLC **Mitsubishi Q03UDVCPU** melalui *Built-in Ethernet Port* ke aplikasi Web menggunakan Python (`pymcprotocol` & `FastAPI`) serta database SQLite untuk pencatatan riwayat (*history*) alarm.

## 1. Catatan Evaluasi Library Python

Berdasarkan evaluasi terhadap repositori `BHpighong/python-mc-protocol`, library tersebut **tidak direkomendasikan** untuk proyek ini karena:

1. **Hanya Generator String:** Tidak memiliki engine TCP/IP socket untuk mengirim/menerima data.

2. **Perbedaan Frame:** Menggunakan **3C Frame (Serial RS-232/485)**, sedangkan Ethernet Q03UDVCPU membutuhkan **3E Frame (SLMP)**.

3. **Solusi:** Gunakan library standar **`pymcprotocol`** dari PyPI yang sudah mendukung penuh **3E Frame Binary** untuk seri Q03UDVCPU.

## 2. Konfigurasi PLC Q03UDVCPU di GX Works2

Secara *default*, port Ethernet Q03UDVCPU hanya membuka jalur untuk GX Works2 dan HMI (GOT). Ikuti langkah berikut untuk membuka jalur komunikasi ke Python:

1. Buka project Anda di **GX Works2**.

2. Di panel navigasi kiri, masuk ke **Parameter** $\rightarrow$ **PLC Parameter**.

3. Pilih tab **Built-in Ethernet Port Setting**.

4. **Pengaturan IP Address:**

   * **IP Address:** Contoh `192.168.3.39` (Sesuaikan dengan segmen jaringan PC/Server Anda).

   * **Subnet Mask:** `255.255.255.0`.

5. **Communication Data Code:**

   * Pilih **`Binary Code`** (Wajib sesuai dengan *default* `pymcprotocol`).

6. **Pengaturan Open Setting:**

   * Klik tombol **Open Setting** di bagian bawah.

   * Pada baris kosong (misal **Connection 1**), masukkan konfigurasi berikut:

     * **Protocol:** `TCP`

     * **Open System:** `MC Protocol`

     * **Host Station Port No.:**

       * Ketik **`138A`** jika tampilan input GX Works2 dalam mode **Hexadecimal**.

       * Ketik **`5002`** jika tampilan input GX Works2 dalam mode **Decimal**.

       > **Catatan Penting:** `138A` (Hex) bernilai sama dengan `5002` (Decimal). Di script Python nanti, kita selalu menuliskan nilai Decimal (`5002`).

7. Klik **End** $\rightarrow$ klik **Check** (pastikan *No Error*) $\rightarrow$ klik **End**.

8. **Write ke PLC & Reset:**

   * Lakukan **Online** $\rightarrow$ **Write to PLC** (centang bagian **Parameter**).

   * **WAJIB:** Matikan dan nyalakan ulang (*Power Cycle*) PLC atau lakukan *Remote Reset* agar parameter port Ethernet aktif.

## 3. Persiapan Environment di VS Code

Buka terminal di VS Code dan instal *package* Python yang dibutuhkan:

```
pip install pymcprotocol fastapi uvicorn


```

Struktur folder proyek yang disarankan di VS Code:

```
project-alarm-plc/
│
├── test_connection.py   # Script untuk tes koneksi awal ke Q03UDVCPU
├── app.py               # Server Backend (Polling PLC + SQLite History + REST API)
├── index.html           # Tampilan Web Dashboard sederhana
└── README.md            # Dokumentasi proyek ini


```

## 4. Tahap 1: Script Tes Koneksi (`test_connection.py`)

Buat file bernama `test_connection.py` untuk menguji apakah PC sudah berhasil membaca alamat `M1501` (Emergency) dan `M1531` (Air Pressure) dari Q03UDVCPU.

```
import pymcprotocol

# Inisialisasi 3E Frame (Standar Ethernet untuk Q03UDVCPU)
plc = pymcprotocol.Type3E()

PLC_IP = "192.168.3.39"  # Ganti dengan IP Q03UDVCPU Anda
PLC_PORT = 5002          # Port Decimal yang sesuai dengan Open Setting (138A Hex)

try:
    plc.connect(PLC_IP, PLC_PORT)
    print("✅ Berhasil terhubung ke Mitsubishi Q03UDVCPU!")

    # Batch read dari M1500 sepanjang 40 bit (M1500 s/d M1539)
    bits = plc.batchread_bitunits(headdevice="M1500", readsize=40)
    
    print(f"Status M1501 (Emergency Stop) : {bits[1]}")
    print(f"Status M1531 (Air Pressure)   : {bits[31]}")

    plc.close()
except Exception as e:
    print(f"❌ Gagal terhubung ke PLC: {e}")


```

Jalankan di terminal VS Code:

```
python test_connection.py


```

## 5. Tahap 2: Kode Backend & Database History (`app.py`)

Kode ini menggunakan logika **Rising & Falling Edge Detection** agar alarm hanya dicatat satu kali ke database saat mulai aktif (`0` $\rightarrow$ `1`), dan otomatis diperbarui waktu selesainya saat kondisi kembali normal (`1` $\rightarrow$ `0`).

Buat file bernama `app.py`:

```
import sqlite3
import threading
import time
from datetime import datetime
import pymcprotocol
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="PLC Q03UDVCPU Alarm Monitor")

# Izinkan akses CORS dari Frontend Web
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= KONFIGURASI PLC & ALARM =================
PLC_IP = "192.168.3.39"  # Sesuaikan dengan IP PLC Q03UDVCPU
PLC_PORT = 5002          # Sesuaikan dengan Host Station Port (Decimal)
START_BIT = "M1500"
READ_LENGTH = 50         # Membaca M1500 s/d M1549 sekaligus dalam 1 paket

# Mapping index relatif terhadap M1500
# Rumus index = Nomor Alamat M - 1500
ALARM_MAP = {
    1:  {"address": "M1501", "name": "Emergency Stop Pressed"},
    31: {"address": "M1531", "name": "Air Pressure Low"},
    # Tambahkan alamat alarm lain di sini jika ada:
    # 32: {"address": "M1532", "name": "Servo Drive Fault"},
}

previous_states = {idx: 0 for idx in ALARM_MAP.keys()}
active_alarms_live = {}

# ================= SETUP DATABASE SQLITE =================
def init_db():
    conn = sqlite3.connect("alarm_history.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alarm_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT,
            alarm_name TEXT,
            status TEXT,
            triggered_at TEXT,
            cleared_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def log_alarm_triggered(address, name):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect("alarm_history.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO alarm_logs (address, alarm_name, status, triggered_at, cleared_at)
        VALUES (?, ?, 'ACTIVE', ?, NULL)
    """, (address, name, now))
    conn.commit()
    conn.close()
    print(f"[ALARM ON] {address} ({name}) pada {now}")

def log_alarm_cleared(address):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect("alarm_history.db")
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE alarm_logs
        SET status = 'CLEARED', cleared_at = ?
        WHERE address = ? AND status = 'ACTIVE'
    """, (now, address))
    conn.commit()
    conn.close()
    print(f"[ALARM OFF] {address} kembali normal pada {now}")

# ================= WORKER THREAD POLLING PLC =================
def plc_polling_worker():
    plc = pymcprotocol.Type3E()
    
    while True:
        try:
            if not plc._is_connected:
                print(f"Menghubungkan ke Q03UDVCPU ({PLC_IP}:{PLC_PORT})...")
                plc.connect(PLC_IP, PLC_PORT)
                print("✅ Terhubung ke PLC Q03UDVCPU!")

            # Batch Read Bit
            bit_values = plc.batchread_bitunits(headdevice=START_BIT, readsize=READ_LENGTH)

            for idx, info in ALARM_MAP.items():
                current_val = bit_values[idx]
                prev_val = previous_states[idx]

                # Deteksi Rising Edge (0 -> 1 : Alarm Aktif)
                if current_val == 1 and prev_val == 0:
                    log_alarm_triggered(info["address"], info["name"])
                    active_alarms_live[info["address"]] = {
                        "name": info["name"],
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }

                # Deteksi Falling Edge (1 -> 0 : Alarm Normal/Reset)
                elif current_val == 0 and prev_val == 1:
                    log_alarm_cleared(info["address"])
                    active_alarms_live.pop(info["address"], None)

                previous_states[idx] = current_val

            time.sleep(0.2)  # Siklus baca setiap 200 milidetik

        except Exception as e:
            print(f"⚠️ Koneksi PLC terputus / Error: {e}")
            try:
                plc.close()
            except:
                pass
            time.sleep(3)  # Tunggu 3 detik sebelum mencoba reconnect otomatis

# ================= ENDPOINT REST API =================
@app.on_event("startup")
def startup_event():
    init_db()
    t = threading.Thread(target=plc_polling_worker, daemon=True)
    t.start()

@app.get("/api/alarms/active")
def get_active_alarms():
    """Endpoint untuk mengambil daftar alarm yang sedang menyala saat ini"""
    return {
        "has_alarm": len(active_alarms_live) > 0,
        "active_alarms": active_alarms_live
    }

@app.get("/api/alarms/history")
def get_alarm_history():
    """Endpoint untuk mengambil 100 riwayat alarm terakhir dari SQLite"""
    conn = sqlite3.connect("alarm_history.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM alarm_logs ORDER BY id DESC LIMIT 100")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


```

Untuk menjalankan server backend di terminal VS Code:

```
uvicorn app:app --reload --host 0.0.0.0 --port 8000


```

## 6. Tahap 3: Contoh Tampilan Web (`index.html`)

Buat file `index.html` untuk memantau pop-up alert merah saat alarm aktif dan melihat tabel riwayat alarm secara langsung:

```
<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8">
  <title>Monitoring Alarm Robot - PLC Q03UDVCPU</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; background: #f4f6f9; }
    .alert-box {
      display: none;
      background: #dc3545;
      color: white;
      padding: 16px;
      border-radius: 6px;
      margin-bottom: 20px;
      font-weight: bold;
    }
    table { width: 100%; border-collapse: collapse; background: white; }
    th, td { padding: 10px; border: 1px solid #ddd; text-align: left; }
    th { background: #212529; color: white; }
    .status-active { color: #dc3545; font-weight: bold; }
    .status-cleared { color: #198754; font-weight: bold; }
  </style>
</head>
<body>

  <h2>Monitoring Alarm Robot (Mitsubishi Q03UDVCPU)</h2>

  <!-- Banner Pop-up saat ada alarm aktif -->
  <div id="alarmBanner" class="alert-box"></div>

  <h3>Riwayat Alarm (History)</h3>
  <table>
    <thead>
      <tr>
        <th>ID</th>
        <th>Alamat</th>
        <th>Nama Alarm</th>
        <th>Status</th>
        <th>Waktu Muncul</th>
        <th>Waktu Normal</th>
      </tr>
    </thead>
    <tbody id="historyTable"></tbody>
  </table>

  <script>
    const API_BASE = "http://localhost:8000";

    async function fetchAlarms() {
      try {
        // 1. Cek Alarm Aktif
        const resActive = await fetch(`${API_BASE}/api/alarms/active`);
        const dataActive = await resActive.json();
        const banner = document.getElementById("alarmBanner");

        if (dataActive.has_alarm) {
          banner.style.display = "block";
          const items = Object.entries(dataActive.active_alarms)
            .map(([addr, info]) => `⚠️ [${addr}] ${info.name} (Sejak: ${info.time})`)
            .join("<br>");
          banner.innerHTML = items;
        } else {
          banner.style.display = "none";
        }

        // 2. Ambil Tabel History
        const resHistory = await fetch(`${API_BASE}/api/alarms/history`);
        const dataHistory = await resHistory.json();
        const tbody = document.getElementById("historyTable");

        tbody.innerHTML = dataHistory.map(row => `
          <tr>
            <td>${row.id}</td>
            <td>${row.address}</td>
            <td>${row.alarm_name}</td>
            <td class="${row.status === 'ACTIVE' ? 'status-active' : 'status-cleared'}">${row.status}</td>
            <td>${row.triggered_at}</td>
            <td>${row.cleared_at || '-'}</td>
          </tr>
        `).join("");

      } catch (err) {
        console.error("Gagal mengambil data dari server:", err);
      }
    }

    // Perbarui data setiap 1 detik
    setInterval(fetchAlarms, 1000);
    fetchAlarms();
  </script>
</body>
</html>


```

## 7. Daftar Periksa Troubleshooting (Jika Gagal Koneksi)

1. **Ping Test:** Buka CMD/Terminal dan jalankan `ping <IP_PLC>`. Pastikan *Reply* sebelum menjalankan script Python.

2. **Konversi Hex vs Decimal di GX Works2:** Pastikan port di GX Works2 (`138A` Hex) sudah sesuai dengan port di Python (`5002` Dec).

3. **Power Cycle PLC:** Parameter *Open Setting* Ethernet pada Q03UDVCPU tidak akan berubah sebelum CPU di-*reset* atau dimatikan-nyalakan ulang.

4. **Konflik Port dengan HMI:** Jika ada HMI (GOT/Weintek) yang juga terhubung via Ethernet, pastikan *Connection Line* di menu *Open Setting* GX Works2 menggunakan nomor port yang berbeda dari HMI.