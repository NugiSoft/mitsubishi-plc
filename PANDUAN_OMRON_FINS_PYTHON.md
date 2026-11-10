# Panduan Lengkap Komunikasi PLC Omron Menggunakan Protokol FINS & Python (`fins-master`)

Dokumen ini menjelaskan cara kerja komunikasi **PLC Omron** (seri CP1L, CP1H, CP1E, CJ2M, CS1) dengan **Python** menggunakan library `fins-master` ([`fins.py`](fins-master/fins.py)) serta aplikasi GUI [`omron_fins_gui.py`](omron_fins_gui.py).

---

## 1. Konsep Dasar Alamat Memori PLC Omron di Python

Berbeda dengan PLC Mitsubishi yang menggunakan penomoran berlanjut (seperti `M1501`), PLC Omron membagi memorinya dalam format **`Word.Bit`** (1 Word = 16 Bit, yaitu bit `.00` sampai `.15`).

Saat menggunakan [`fins.py`](fins-master/fins.py), setiap alamat PLC Omron selalu dipecah menjadi **3 bagian**:
1. **`memory_area_code`**: Jenis area memori di PLC Omron (`CIO`, `W`, `H`, `D`).
2. **`address_word`**: Nomor *Word* (angka di **depan** titik).
3. **`address_bit`**: Nomor *Bit* `0` s/d `15` (angka di **belakang** titik). Jika membaca/menulis *Word* utuh (16-bit), nilai ini selalu diisi `0`.

### Tabel Pemetaan Alamat (`W0.00`, `W0.01`, dan `100.00`)

| Alamat di CX-Programmer | Arti Area Memori | `memory_area_code` di `fins.py` | `address_word` (Angka Depan Titik) | `address_bit` (Angka Belakang Titik) | Fungsi pada Proyek Ini |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **`W0.00`** | Work Area Bit | `WR_BIT` (`'31'`) | `0` | `0` | Tombol **START** (Menyalakan `100.00`) |
| **`W0.01`** | Work Area Bit | `WR_BIT` (`'31'`) | `0` | `1` | Tombol **STOP** (Mematikan `100.00`) |
| **`100.00`** *(CIO 100.00)* | Core I/O Area Bit | `CIO_BIT` (`'30'`) | `100` | `0` | **Output Fisik / Lampu** |

---

## 2. Daftar Lengkap Kode Area Memori di `fins.py`

Jika Anda ingin menambahkan alamat lain (misal `H10.05` atau `D200`), gunakan konstanta yang sudah disediakan di [`fins-master/fins.py`](fins-master/fins.py):

| Jenis Memori Omron | Contoh Alamat di PLC | Konstanta Bit (`0`/`1`) di `fins.py` | Konstanta Word (Angka 16-bit) di `fins.py` |
| :--- | :--- | :--- | :--- |
| **CIO** *(Input/Output)* | `0.00`, `100.00` | `CIO_BIT` (`'30'`) | `CIO_WORD` (`'B0'`) |
| **W / WR** *(Work Relay)* | `W0.00`, `W0.01`, `W10.05` | `WR_BIT` (`'31'`) | `WR_WORD` (`'B1'`) |
| **H / HR** *(Holding Relay)* | `H0.00`, `H5.02` | `HR_BIT` (`'32'`) | `HR_WORD` (`'B2'`) |
| **A / AR** *(Auxiliary)* | `A100.00` | `AR_BIT` (`'33'`) | `AR_WORD` (`'B3'`) |
| **D / DM** *(Data Memory)* | `D0`, `D100`, `D500` | `DM_BIT` (`'02'`) | `DM_WORD` (`'82'`) |

---

## 3. Cara Membaca & Mengirim Data di Python (`fins.py`)

Berikut adalah penjelasan langkah demi langkah bagaimana kode Python berkomunikasi dengan PLC Omron:

### Langkah 1: Membuka Koneksi ke PLC Omron
Library [`fins-master/fins.py`](fins-master/fins.py) kini mendukung 4 mode koneksi yang bisa dipilih sesuai perangkat Anda:

```python
import sys
sys.path.insert(0, "fins-master")
from fins import FINS, CIO_BIT, WR_BIT, DM_WORD, UDPFinsConnection, SimulatedFinsConnection

# OPSI A: Jika menggunakan PLC Omron Fisik via Kabel LAN (Ethernet FINS/UDP Port 9600)
# - host      : IP Address PLC Omron (contoh: "192.168.250.1")
# - port      : Port standar FINS Omron adalah 9600
# - dest_node : Angka terakhir dari IP PLC (misal IP PLC 192.168.250.1 -> dest_node = 1)
# - src_node  : Angka terakhir dari IP Laptop/PC Anda (misal IP PC 192.168.250.10 -> src_node = 10)
conn = UDPFinsConnection(host="192.168.250.1", port=9600, dest_node=1, src_node=10)

# OPSI B: Jika ingin menguji di laptop tanpa PLC fisik (Mode Simulator)
# conn = SimulatedFinsConnection(auto_ladder=True)

# Bungkus objek koneksi ke dalam engine FINS
plc = FINS(conn)
```

---

### Langkah 2: Cara Membaca Status (`W0.00`, `W0.01`, dan `100.00`) dari PLC ke Python
Untuk membaca memori PLC, gunakan fungsi `memory_area_read()` (untuk banyak bit/word sekaligus) atau `memory_area_read_single()` (untuk 1 bit/word):

```python
# 1. Membaca W0.00 dan W0.01 sekaligus (2 bit berurutan mulai dari W0.00)
#    address_word = 0, address_bit = 0, num_items = 2
wr_bits = plc.memory_area_read(WR_BIT, address_word=0, address_bit=0, num_items=2)
status_w000 = wr_bits[0]  # Nilai W0.00 (0 atau 1)
status_w001 = wr_bits[1]  # Nilai W0.01 (0 atau 1)

# 2. Membaca 1 alamat yaitu Output 100.00 (CIO Word 100, Bit 0)
status_100_00 = plc.memory_area_read_single(CIO_BIT, address_word=100, address_bit=0)

print(f"W0.00 = {status_w000} | W0.01 = {status_w001} | Output 100.00 = {status_100_00}")
```

---

### Langkah 3: Cara Mengirim Perintah (`W0.00` Menyalakan `100.00` & `W0.01` Mematikan `100.00`)
Untuk mengirim nilai ke PLC, gunakan fungsi `memory_area_write()`:

```python
# A. SAAT TOMBOL START (W0.00) DITEKAN:
# 1. Kirim nilai 1 (ON) ke W0.00
plc.memory_area_write(WR_BIT, address_word=0, address_bit=0, values=1)

# 2. Saat tombol dilepas, kembalikan W0.00 ke 0 (OFF) seperti Push Button fisik
plc.memory_area_write(WR_BIT, address_word=0, address_bit=0, values=0)


# B. SAAT TOMBOL STOP (W0.01) DITEKAN:
# 1. Kirim nilai 1 (ON) ke W0.01 untuk memutus arus ke 100.00
plc.memory_area_write(WR_BIT, address_word=0, address_bit=1, values=1)

# 2. Saat tombol dilepas, kembalikan W0.01 ke 0 (OFF)
plc.memory_area_write(WR_BIT, address_word=0, address_bit=1, values=0)
```

---

### Langkah 4: Cara Membuat Program Exit / Mematikan Koneksi dengan Aman
Saat aplikasi akan ditutup, kita wajib menghentikan siklus pembacaan (*polling*) dan menutup *socket* jaringan agar port `9600` tidak terkunci:

```python
def exit_program():
    # 1. Hentikan loop pembacaan background thread
    stop_event.set()
    
    # 2. Tutup koneksi socket UDP/TCP FINS
    if conn is not None:
        conn.close()
        
    # 3. Tutup jendela GUI dan keluar dari proses Python
    root.destroy()
    sys.exit(0)
```

---

## 4. Desain Ladder Diagram di CX-Programmer (Untuk PLC Omron Fisik)

Di dalam PLC Omron, agar `100.00` tetap menyala (*Self-Holding / Latching*) ketika tombol `W0.00` ditekan sesaat, dan mati ketika `W0.01` ditekan, buat 1 *rung* rangkaian standar berikut di **CX-Programmer**:

```text
   W0.00       W0.01       100.00
----| |----+----|/|----------( )----
           |
  100.00   |
----| |----+
```

- **Penjelasan Rangkaian:**
  1. Saat Python menekan **`W0.00`** (`W0.00 = 1`), arus mengalir menyalakan coil Output **`100.00`**.
  2. Kontak bantu `100.00` di bawah `W0.00` ikut menutup (*mengunci*), sehingga walaupun tombol `W0.00` dilepas (`W0.00 = 0`), output **`100.00` tetap menyala (`1`)**.
  3. Saat Python menekan **`W0.01`** (`W0.01 = 1`), kontak *Normally Closed* `|/| W0.01` terbuka dan memutus aliran arus, sehingga output **`100.00` langsung mati (`0`)**.

> **Tips di GUI [`omron_fins_gui.py`](omron_fins_gui.py):**
> Jika di PLC Omron Anda belum sempat dibuat program Ladder di atas, di dalam GUI sudah disediakan centang **"Kirim juga perintah ON/OFF langsung ke Output CIO 100.00"**. Dengan centang tersebut aktif, Python otomatis menyalakan/mematikan `100.00` secara langsung ketika Anda menekan tombol `W0.00` atau `W0.01`.

---

## 5. Cara Menjalankan & Menguji Aplikasi GUI (`omron_fins_gui.py`)

1. Buka terminal di VS Code dan jalankan:
   ```powershell
   python omron_fins_gui.py
   ```
2. **Pengujian Tanpa PLC (Mode Simulator Default):**
   - Begitu jendela terbuka, aplikasi langsung terhubung ke **Simulator Lokal**.
   - Klik tombol hijau **`🟢 TEKAN W0.00`** $\rightarrow$ perhatikan indikator **`W0.00`** berkedip hijau dan indikator **`Output CIO 100.00`** langsung menyala **`1 (ON)`**.
   - Klik tombol merah **`🔴 TEKAN W0.01`** $\rightarrow$ perhatikan indikator **`W0.01`** berkedip merah dan indikator **`Output CIO 100.00`** langsung mati **`0 (OFF)`**.
3. **Menghubungkan ke PLC Omron Sungguhan:**
   - Pada bagian **1. Pengaturan Koneksi FINS Omron**, ubah **Mode Koneksi** menjadi **`FINS/UDP (Ethernet Omron Standar - Port 9600)`**.
   - Masukkan **IP PLC** (contoh: `192.168.250.1`), **Port** (`9600`), **PLC Node (DA1)** = angka terakhir IP PLC (`1`), dan **PC Node (SA1)** = angka terakhir IP laptop Anda (misal `10`).
   - Klik tombol **`🔌 Hubungkan / Reconnect`**.
4. **Mematikan Program:**
   - Klik tombol **`🛑 EXIT / MATIKAN PROGRAM (ESC)`** di pojok kanan bawah atau tekan tombol **`ESC`** di keyboard.
