# Panduan Implementasi Komunikasi PLC Mitsubishi Q03UDVCPU untuk Monitoring & Kontrol Multi-Robot (KUKA, Nachi, Hyundai)

Dokumen ini disusun sebagai panduan teknis bagi seluruh anggota tim untuk mengimplementasikan komunikasi antara **PC/Server (Python)** dengan **PLC Mitsubishi Q03UDVCPU** yang menjadi pusat pengumpul data (*concentrator*) dari berbagai robot industri (**KUKA, Nachi, Hyundai**).

---

## 1. Arsitektur Komunikasi Multi-Robot ke PLC Mitsubishi

Di lini produksi, meskipun terdapat berbagai merek robot (**KUKA, Nachi, Hyundai**), kita **tidak perlu membuat koneksi terpisah ke masing-masing robot** dari aplikasi monitoring apabila seluruh robot tersebut sudah terhubung ke **PLC Master Mitsubishi Q03UDVCPU** (melalui CC-Link, Profibus, Ethernet/IP, atau I/O Hardwire).

```text
+---------------+     +---------------+     +-----------------+
|  Robot KUKA   |     |  Robot NACHI  |     |  Robot HYUNDAI  |
+-------+-------+     +-------+-------+     +--------+--------+
        |                     |                      |
        +---------------------+----------------------+
                              | (CC-Link / I/O / Fieldbus)
                              v
             +--------------------------------+
             |  PLC Mitsubishi Q03UDVCPU      |
             |  - M1500..M1599 : Safety/Line  |
             |  - M1600..M1699 : Error KUKA   |
             |  - M1700..M1799 : Error NACHI  |
             |  - M1800..M1899 : Error HYUNDAI|
             |  - D1600..D1800 : Kode Numerik |
             +----------------+---------------+
                              |
                              | Ethernet TCP/IP (MC Protocol 3E Frame - Port 5002)
                              v
             +--------------------------------+
             |  Aplikasi Python               |
             |  (plc_real_monitor.py)         |
             |  - Baca ratusan alamat (Read)  |
             |  - Kirim sinyal Reset (Write)  |
             |  - Simpan History ke SQLite    |
             +--------------------------------+
```

---

## 2. Cara Menentukan & Mendefinisikan Alamat PLC (Contoh `M1501`) di Python

Di PLC Mitsubishi, memori dibagi menjadi 2 jenis utama:
1. **Bit Device (`M`, `B`, `X`, `Y`, `L`):** Hanya bernilai **`0` (OFF)** atau **`1` (ON)**. Cocok untuk status alarm indywidual (misal `M1501` = Emergency Stop).
2. **Word Device (`D`, `W`, `R`):** Menyimpan **angka 16-bit** (`-32768` s/d `32767` atau `0` s/d `65535`). Cocok untuk menyimpan **Nomor Kode Error Robot** (misal `D1600 = 204` artinya Error Servo KUKA No. 204).

---

### A. Konsep Dasar: Mengapa `M1501` Berada di Index `[1]` pada Batch Read?

Jika kita membaca ratusan alamat satu per satu ke PLC, komunikasi jaringan akan menjadi lambat. Oleh karena itu, kita menggunakan teknik **Batch Read** (membaca satu deret alamat sekaligus dalam 1 paket jaringan).

Misalkan kita memanggil:
```python
bits = plc.batchread_bitunits(headdevice="M1500", readsize=40)
```
Artinya Python meminta PLC mengirimkan **40 bit berurutan** dimulai dari **`M1500`** sampai **`M1539`**. Hasilnya disimpan di variabel `bits` berupa *List/Array* Python yang dimulai dari index `0`:

| Alamat di PLC | Rumus Index (`Nomor_M - Nomor_Head`) | Posisi di Array Python | Keterangan |
| :--- | :--- | :--- | :--- |
| `M1500` | `1500 - 1500 = 0` | `bits[0]` | Titik awal pembacaan (*Head Device*) |
| **`M1501`** | **`1501 - 1500 = 1`** | **`bits[1]`** | **Emergency Stop Pressed** |
| `M1502` | `1502 - 1500 = 2` | `bits[2]` | Safety Door Open |
| ... | ... | ... | ... |
| **`M1531`** | **`1531 - 1500 = 31`** | **`bits[31]`** | **Main Air Pressure Low** |
| `M1539` | `1539 - 1500 = 39` | `bits[39]` | Bit ke-40 (terakhir dalam paket ini) |

> **Rumus Cepat Menentukan Index:**
> $$\text{Index Python} = \text{Nomor Alamat Target} - \text{Nomor Alamat Awal (Head)}$$
> Contoh: Jika `headdevice="M1600"`, maka alamat `M1625` berada di `bits[1625 - 1600]` yaitu **`bits[25]`**.

---

### B. Cara Otomatis (Tanpa Perlu Menghitung Index Manual) untuk Banyak Robot

Ketika jumlah kode error mencapai puluhan atau ratusan (gabungan KUKA, Nachi, Hyundai), menghitung index secara manual rawan salah.

Pada program baru **`plc_real_monitor.py`**, kita sudah membuat fungsi otomatis **`build_read_blocks()`**. Rekan-rekan tim **cukup menuliskan nama alamat aslinya** (`"M1501"`, `"M1600"`, `"M1702"`, dst.) di dalam dictionary `ALARM_DEFINITIONS`:

```python
ALARM_DEFINITIONS = {
    # --- GRUP 1: ALARM UMUM LINE / SAFETY PLC ---
    "M1501": {"robot": "MAIN_PLC", "code": "ALM-001", "name": "Emergency Stop Line Pressed", "severity": "CRITICAL"},
    "M1531": {"robot": "MAIN_PLC", "code": "ALM-031", "name": "Main Air Pressure Low", "severity": "WARNING"},

    # --- GRUP 2: ALARM ROBOT KUKA ---
    "M1600": {"robot": "KUKA", "code": "KUKA-E01", "name": "KUKA Emergency Stop", "severity": "CRITICAL"},
    "M1601": {"robot": "KUKA", "code": "KUKA-E02", "name": "KUKA Servo Drive Fault", "severity": "CRITICAL"},

    # --- GRUP 3: ALARM ROBOT NACHI ---
    "M1700": {"robot": "NACHI", "code": "NACHI-E01", "name": "Nachi Robot Major Alarm", "severity": "CRITICAL"},

    # --- GRUP 4: ALARM ROBOT HYUNDAI ---
    "M1800": {"robot": "HYUNDAI", "code": "HD-E01", "name": "Hyundai Robot Controller Fault", "severity": "CRITICAL"},
}
```

**Bagaimana Python Memproses Dictionary di Atas Secara Otomatis?**
1. Fungsi `build_read_blocks()` memisahkan huruf `"M"` dan angka `1501` menggunakan `int(addr[1:])`.
2. Alamat-alamat yang berdekatan otomatis dikelompokkan ke dalam satu blok *Batch Read* (maksimal rentang 120 bit per blok) agar pembacaan tetap sangat cepat walaupun alamat antar robot berjauhan (misal `M1500` dengan `M1800`).
3. Selisih index (`offset_index`) dihitung otomatis oleh program di balik layar.

---

### C. Cara Membaca Kode Error Numerik Robot dari Register `D` (Word)

Seringkali kontroller robot (seperti KUKA KRC4, Nachi FD, atau Hyundai Hi5) mengirimkan **16-bit Error Code** ke dalam satu *Data Register (`D`)* di PLC.
Misalnya:
- `D1600` menyimpan nomor error Robot KUKA (`0` = Normal, `105` = Mastering Lost, `204` = Motor Overload).

Cara membacanya di Python:
```python
# Membaca 1 register Word dari D1600
word_vals = plc.batchread_wordunits(headdevice="D1600", readsize=1)
kode_error_kuka = word_vals[0]  # Berisi angka bulat (misal: 0, 105, 204)

# Kamus penerjemah kode angka menjadi deskripsi error KUKA
KAMUS_ERROR_KUKA = {
    105: "KUKA Mastering Axis Lost",
    204: "KUKA Servo Motor Overload",
    310: "KUKA External Emergency Stop",
}

if kode_error_kuka > 0:
    pesan = KAMUS_ERROR_KUKA.get(kode_error_kuka, f"Unknown KUKA Error ({kode_error_kuka})")
    print(f"⚠️ Robot KUKA Error [{kode_error_kuka}]: {pesan}")
```

---

## 3. Cara Mengirim Data (Write) dari Python ke PLC Mitsubishi

Selain membaca status error, Python juga dapat **mengirim perintah (Write)** ke PLC, misalnya:
- Mengirim sinyal **Reset Alarm Robot** (`M2000`) dari tombol di layar PC.
- Mengirim sinyal **Buzzer Stop / Acknowledge** (`M2001`).
- Mengirim angka parameter / nomor program ke register **`D`**.

### A. Mengirim Sinyal Bit (`0` atau `1`) — `batchwrite_bitunits`

```python
# 1. Menyalakan Bit M2000 menjadi ON (1)
plc.batchwrite_bitunits(headdevice="M2000", values=[1])

# 2. Mematikan Bit M2000 menjadi OFF (0)
plc.batchwrite_bitunits(headdevice="M2000", values=[0])

# 3. Menulis beberapa Bit berurutan sekaligus (M2000=1, M2001=0, M2002=1)
plc.batchwrite_bitunits(headdevice="M2000", values=[1, 0, 1])
```

### B. Mengirim Sinyal Tombol Sesaat (*Momentary Pulse*) untuk Reset Error

Di program Ladder PLC, tombol *Reset* biasanya membutuhkan sinyal pulsa (**ON sebentar lalu kembali OFF** agar tidak tertahan ON terus-menerus). Di `plc_real_monitor.py`, gunakan fungsi `pulse_bit_to_plc()`:

```python
def pulse_bit_to_plc(plc, address, duration_sec=0.5):
    plc.batchwrite_bitunits(headdevice=address, values=[1])  # Tekan (ON)
    time.sleep(duration_sec)                                 # Tahan 0.5 detik
    plc.batchwrite_bitunits(headdevice=address, values=[0])  # Lepas (OFF)
```

### C. Mengirim Nilai Angka ke Register Word (`D`) — `batchwrite_wordunits`

```python
# 1. Mengirim 1 nilai angka (misal angka 55) ke register D2000
plc.batchwrite_wordunits(headdevice="D2000", values=[55])

# 2. Mengirim 3 nilai angka sekaligus ke D2000, D2001, dan D2002
#    Hasil: D2000 = 10, D2001 = 20, D2002 = 30
plc.batchwrite_wordunits(headdevice="D2000", values=[10, 20, 30])
```

---

## 4. Pengaturan Wajib di GX Works2 untuk PLC Sungguhan (Q03UDVCPU)

Agar program `plc_real_monitor.py` dapat terhubung ke PLC fisik Q03UDVCPU tanpa MX OPC:

1. Buka project PLC di **GX Works2**.
2. Masuk ke **Parameter** $\rightarrow$ **PLC Parameter** $\rightarrow$ tab **Built-in Ethernet Port Setting**.
3. Catat atau atur **IP Address** PLC (misal `192.168.3.39`, Subnet `255.255.255.0`).
4. Pada **Communication Data Code**, pilih **`Binary Code`**.
5. Klik tombol **Open Setting**, lalu isi satu baris koneksi kosong:
   - **Protocol:** `TCP`
   - **Open System:** `MC Protocol`
   - **Host Station Port No.:**
     - Isi **`138A`** jika input GX Works2 dalam format **Hexadecimal**.
     - Isi **`5002`** jika input GX Works2 dalam format **Decimal**.
     *(Keduanya bernilai sama: `138A` Hex = `5002` Decimal).*
6. Klik **End** $\rightarrow$ **Write to PLC** (centang Parameter) $\rightarrow$ **Reset / Power Cycle PLC** (Wajib dimatikan dan dinyalakan ulang agar port `5002` terbuka).

---

## 5. Cara Menjalankan Program (`plc_real_monitor.py`)

1. Pastikan library sudah terinstal di environment Python Anda:
   ```powershell
   pip install pymcprotocol
   ```
2. Buka file `plc_real_monitor.py` dan sesuaikan `PLC_IP` dengan IP PLC Q03UDVCPU di lapangan:
   ```python
   PLC_IP = "192.168.3.39"
   PLC_PORT = 5002
   ```
3. Tambahkan daftar alamat alarm untuk masing-masing robot (KUKA, Nachi, Hyundai) pada bagian `ALARM_DEFINITIONS`.
4. Jalankan program dari terminal:
   ```powershell
   python plc_real_monitor.py
   ```
5. **Kontrol Saat Program Berjalan:**
   - Tekan **`R`** di keyboard: Mengirim pulsa sinyal Reset (`M2000`) ke PLC.
   - Tekan **`Q`**, **`ESC`**, atau **`Ctrl + C`**: Memutuskan koneksi socket PLC dan mematikan program dengan aman.

---

## 6. Ringkasan File di Dalam Proyek Ini

| Nama File | Fungsi & Kapan Digunakan |
| :--- | :--- |
| **`cek-koneksi.py`** | Digunakan saat pengujian lokal menggunakan **MX OPC Server 6.10** & **GX Simulator2** di laptop. |
| **`plc_real_monitor.py`** | Digunakan untuk koneksi langsung ke **PLC Fisik Mitsubishi Q03UDVCPU** via kabel LAN/Ethernet (`pymcprotocol`) dengan dukungan multi-robot (KUKA, Nachi, Hyundai), fungsi Write/Reset, dan database SQLite. |
| **`PANDUAN_IMPLEMENTASI_PLC_MULTI_ROBOT.md`** | Dokumentasi panduan teknis ini untuk dibagikan kepada rekan-rekan tim. |
