# mitsubishi-plc

Repositori sistem monitoring & kontrol alarm **PLC Mitsubishi Q03UDVCPU** untuk lini produksi **Multi-Robot (KUKA, Nachi, Hyundai)** menggunakan Python.

## Daftar File Utama

- **[`plc_real_monitor.py`](plc_real_monitor.py)** — Program utama untuk koneksi langsung ke **PLC Fisik Mitsubishi Q03UDVCPU** melalui *Built-in Ethernet* (`pymcprotocol` - MC Protocol 3E Frame). Mendukung pembacaan banyak alamat otomatis (*Multi-Block Batch Read*), pembacaan register Word (`D`), pengiriman sinyal Write/Reset (`M` & `D`), serta pencatatan riwayat alarm ke SQLite.
- **[`cek-koneksi.py`](cek-koneksi.py)** — Script pengujian koneksi lokal menggunakan **Mitsubishi MX OPC Server 6.10** (`Mitsubishi.MXOPC.6`) dan **GX Simulator2** melalui *Synchronous OPC DA*.
- **[`PANDUAN_IMPLEMENTASI_PLC_MULTI_ROBOT.md`](PANDUAN_IMPLEMENTASI_PLC_MULTI_ROBOT.md)** — Dokumentasi lengkap cara menentukan/mendefinisikan alamat PLC (seperti `M1501`, `M1531`, `D1600`) di Python, cara mengirim data (Write Bit/Word), dan panduan implementasi untuk tim.
- **[`omron_fins_gui.py`](omron_fins_gui.py)** — Aplikasi GUI kontrol & monitoring **PLC Omron (FINS)** untuk membaca & mengontrol `W0.00` (Start), `W0.01` (Stop), dan Output `100.00` (`CIO 100.00`).
- **[`PANDUAN_OMRON_FINS_PYTHON.md`](PANDUAN_OMRON_FINS_PYTHON.md)** — Dokumentasi lengkap komunikasi PLC Omron menggunakan protokol FINS (`fins-master`).
- **[`panduan_koneksi_alarm_plc_q03udvcpu_ke_web (1).md`](panduan_koneksi_alarm_plc_q03udvcpu_ke_web%20(1).md)** — Dokumentasi integrasi backend FastAPI & tampilan Web Dashboard.

## Cara Menjalankan

1. Instal dependensi:
   ```bash
   pip install pymcprotocol fastapi uvicorn
   ```
2. Untuk pengujian dengan **PLC Fisik Q03UDVCPU**:
   ```bash
   python plc_real_monitor.py
   ```
3. Untuk pengujian dengan **MX OPC Server & Simulator**:
   ```bash
   python cek-koneksi.py
   ```
   *(Tekan `Q`, `ESC`, atau `Ctrl+C` kapan saja untuk mematikan program dengan aman).*
