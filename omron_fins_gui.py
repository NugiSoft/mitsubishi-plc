"""
Program Monitoring & GUI Kontrol PLC Omron menggunakan Protokol FINS (fins-master)
Target Alamat:
- W0.00  (Work Area Bit 0.00) -> Tombol START (Menyalakan Output 100.00)
- W0.01  (Work Area Bit 0.01) -> Tombol STOP  (Mematikan Output 100.00)
- 100.00 (CIO Area Bit 100.00) -> Output Lampu / Relay Utama

Cara Menjalankan:
    python omron_fins_gui.py
"""

from datetime import datetime
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

# Tambahkan folder fins-master ke sys.path agar mengimpor fins.py dari folder fins-master
FINS_DIR = Path(__file__).resolve().parent / "fins-master"
if str(FINS_DIR) not in sys.path:
    sys.path.insert(0, str(FINS_DIR))

from fins import (  # noqa: E402
    CIO_BIT,
    FINS,
    WR_BIT,
    SimulatedFinsConnection,
    TCPFinsConnection,
    TCPHostLinkConnection,
    UDPFinsConnection,
)


class OmronFinsApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Omron FINS PLC Controller — W0.00 | W0.01 | CIO 100.00")
        self.root.geometry("820x640")
        self.root.minsize(760, 580)
        self.root.configure(bg="#1e293b")

        # State koneksi FINS
        self.connection = None
        self.plc: FINS | None = None
        self.is_connected = False
        self.stop_event = threading.Event()
        self.fins_lock = threading.Lock()
        self.polling_thread: threading.Thread | None = None

        # Nilai pembacaan terakhir dari PLC
        self.val_w000 = 0
        self.val_w001 = 0
        self.val_10000 = 0

        # Variabel UI
        self.mode_var = tk.StringVar(value="SIMULATOR (Tes Tanpa PLC Fisik)")
        self.ip_var = tk.StringVar(value="192.168.250.1")
        self.port_var = tk.StringVar(value="9600")
        self.da1_var = tk.StringVar(value="1")    # Node PLC (biasanya angka terakhir IP PLC)
        self.sa1_var = tk.StringVar(value="10")   # Node PC  (biasanya angka terakhir IP PC)
        self.direct_write_100_var = tk.BooleanVar(value=True)
        self.status_text_var = tk.StringVar(value="Status: Belum Terhubung")

        self._build_ui()
        self._bind_shortcuts()

        # Otomatis hubungkan ke mode Simulator saat pertama kali dibuka agar bisa langsung dicoba
        self.root.after(200, self.connect_plc)

    # ==========================================================================
    # PEMBUATAN TAMPILAN GUI
    # ==========================================================================
    def _build_ui(self):
        # Header
        header_frame = tk.Frame(self.root, bg="#0f172a", padx=16, pady=12)
        header_frame.pack(fill=tk.X)

        tk.Label(
            header_frame,
            text="OMRON PLC FINS MONITOR & CONTROL (W0.00 / W0.01 -> 100.00)",
            font=("Segoe UI", 14, "bold"),
            fg="#38bdf8",
            bg="#0f172a",
        ).pack(side=tk.LEFT)

        tk.Label(
            header_frame,
            textvariable=self.status_text_var,
            font=("Segoe UI", 10, "bold"),
            fg="#facc15",
            bg="#0f172a",
        ).pack(side=tk.RIGHT)

        # 1. Frame Konfigurasi Koneksi
        conn_frame = tk.LabelFrame(
            self.root,
            text=" 1. Pengaturan Koneksi FINS Omron ",
            font=("Segoe UI", 10, "bold"),
            fg="#e2e8f0",
            bg="#1e293b",
            padx=12,
            pady=10,
        )
        conn_frame.pack(fill=tk.X, padx=16, pady=(12, 6))

        tk.Label(conn_frame, text="Mode Koneksi:", fg="#cbd5e1", bg="#1e293b", font=("Segoe UI", 9)).grid(
            row=0, column=0, sticky="w", padx=4, pady=4
        )
        mode_combo = ttk.Combobox(
            conn_frame,
            textvariable=self.mode_var,
            state="readonly",
            width=34,
            values=[
                "SIMULATOR (Tes Tanpa PLC Fisik)",
                "FINS/UDP (Ethernet Omron Standar - Port 9600)",
                "FINS/TCP (Ethernet Omron - Port 9600)",
                "Host Link TCP (ASCII FINS - fins.py)",
            ],
        )
        mode_combo.grid(row=0, column=1, columnspan=3, sticky="w", padx=4, pady=4)

        self.btn_connect = tk.Button(
            conn_frame,
            text="🔌 Hubungkan / Reconnect",
            command=self.connect_plc,
            bg="#0284c7",
            fg="white",
            activebackground="#0369a1",
            activeforeground="white",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=4,
            cursor="hand2",
        )
        self.btn_connect.grid(row=0, column=4, columnspan=2, sticky="e", padx=8, pady=4)

        # Baris IP, Port, Node
        tk.Label(conn_frame, text="IP PLC:", fg="#cbd5e1", bg="#1e293b", font=("Segoe UI", 9)).grid(
            row=1, column=0, sticky="w", padx=4, pady=4
        )
        tk.Entry(conn_frame, textvariable=self.ip_var, width=16, font=("Consolas", 10)).grid(
            row=1, column=1, sticky="w", padx=4, pady=4
        )

        tk.Label(conn_frame, text="Port:", fg="#cbd5e1", bg="#1e293b", font=("Segoe UI", 9)).grid(
            row=1, column=2, sticky="w", padx=4, pady=4
        )
        tk.Entry(conn_frame, textvariable=self.port_var, width=8, font=("Consolas", 10)).grid(
            row=1, column=3, sticky="w", padx=4, pady=4
        )

        tk.Label(conn_frame, text="PLC Node (DA1):", fg="#cbd5e1", bg="#1e293b", font=("Segoe UI", 9)).grid(
            row=1, column=4, sticky="w", padx=4, pady=4
        )
        tk.Entry(conn_frame, textvariable=self.da1_var, width=5, font=("Consolas", 10)).grid(
            row=1, column=5, sticky="w", padx=4, pady=4
        )

        tk.Label(conn_frame, text="PC Node (SA1):", fg="#cbd5e1", bg="#1e293b", font=("Segoe UI", 9)).grid(
            row=1, column=6, sticky="w", padx=4, pady=4
        )
        tk.Entry(conn_frame, textvariable=self.sa1_var, width=5, font=("Consolas", 10)).grid(
            row=1, column=7, sticky="w", padx=4, pady=4
        )

        # 2. Frame Indikator Pembacaan Live (W0.00, W0.01, 100.00)
        monitor_frame = tk.LabelFrame(
            self.root,
            text=" 2. Status Pembacaan Memori PLC Secara Real-Time (FINS Read 0101) ",
            font=("Segoe UI", 10, "bold"),
            fg="#e2e8f0",
            bg="#1e293b",
            padx=12,
            pady=12,
        )
        monitor_frame.pack(fill=tk.X, padx=16, pady=6)

        for i in range(3):
            monitor_frame.columnconfigure(i, weight=1)

        self.card_w000 = self._create_indicator_card(
            monitor_frame, col=0, title="Input Bit W0.00", subtitle="Work Area (WR 0.00) - START"
        )
        self.card_w001 = self._create_indicator_card(
            monitor_frame, col=1, title="Input Bit W0.01", subtitle="Work Area (WR 0.01) - STOP"
        )
        self.card_10000 = self._create_indicator_card(
            monitor_frame, col=2, title="Output CIO 100.00", subtitle="CIO Area (100.00) - LAMPU/RELAY"
        )

        # 3. Frame Tombol Kontrol (W0.00 -> Nyalakan 100.00, W0.01 -> Matikan 100.00)
        ctrl_frame = tk.LabelFrame(
            self.root,
            text=" 3. Panel Kontrol Push Button (FINS Write 0102) ",
            font=("Segoe UI", 10, "bold"),
            fg="#e2e8f0",
            bg="#1e293b",
            padx=12,
            pady=12,
        )
        ctrl_frame.pack(fill=tk.X, padx=16, pady=6)

        ctrl_frame.columnconfigure(0, weight=1)
        ctrl_frame.columnconfigure(1, weight=1)

        # Tombol W0.00 (START -> Menyalakan 100.00)
        self.btn_w000 = tk.Button(
            ctrl_frame,
            text="🟢 TEKAN W0.00\n(NYALAKAN OUTPUT 100.00)",
            bg="#16a34a",
            fg="white",
            activebackground="#15803d",
            activeforeground="white",
            font=("Segoe UI", 11, "bold"),
            height=2,
            cursor="hand2",
        )
        self.btn_w000.grid(row=0, column=0, sticky="ew", padx=8, pady=6)
        self.btn_w000.bind("<ButtonPress-1>", lambda e: self.on_press_w000())
        self.btn_w000.bind("<ButtonRelease-1>", lambda e: self.on_release_w000())

        # Tombol W0.01 (STOP -> Mematikan 100.00)
        self.btn_w001 = tk.Button(
            ctrl_frame,
            text="🔴 TEKAN W0.01\n(MATIKAN OUTPUT 100.00)",
            bg="#dc2626",
            fg="white",
            activebackground="#b91c1c",
            activeforeground="white",
            font=("Segoe UI", 11, "bold"),
            height=2,
            cursor="hand2",
        )
        self.btn_w001.grid(row=0, column=1, sticky="ew", padx=8, pady=6)
        self.btn_w001.bind("<ButtonPress-1>", lambda e: self.on_press_w001())
        self.btn_w001.bind("<ButtonRelease-1>", lambda e: self.on_release_w001())

        chk_direct = tk.Checkbutton(
            ctrl_frame,
            text="Kirim juga perintah ON/OFF langsung ke Output CIO 100.00 (Centang jika di PLC belum dibuat program Ladder Self-Holding)",
            variable=self.direct_write_100_var,
            bg="#1e293b",
            fg="#cbd5e1",
            selectcolor="#0f172a",
            activebackground="#1e293b",
            activeforeground="white",
            font=("Segoe UI", 9),
        )
        chk_direct.grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 0))

        # 4. Log Aktivitas & Tombol Exit Program
        log_frame = tk.LabelFrame(
            self.root,
            text=" 4. Log Komunikasi FINS (Python <-> PLC Omron) ",
            font=("Segoe UI", 10, "bold"),
            fg="#e2e8f0",
            bg="#1e293b",
            padx=12,
            pady=8,
        )
        log_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=6)

        self.log_text = tk.Text(
            log_frame,
            height=6,
            bg="#0f172a",
            fg="#38bdf8",
            font=("Consolas", 9),
            state="disabled",
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Footer & Tombol Exit
        footer_frame = tk.Frame(self.root, bg="#1e293b", padx=16, pady=8)
        footer_frame.pack(fill=tk.X)

        tk.Label(
            footer_frame,
            text="💡 Pintasan Keyboard: Tekan [ESC] atau [Q] untuk keluar dari program dengan aman.",
            fg="#94a3b8",
            bg="#1e293b",
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT)

        self.btn_exit = tk.Button(
            footer_frame,
            text="🛑 EXIT / MATIKAN PROGRAM (ESC)",
            command=self.exit_program,
            bg="#e11d48",
            fg="white",
            activebackground="#9f1239",
            activeforeground="white",
            font=("Segoe UI", 10, "bold"),
            padx=16,
            pady=6,
            cursor="hand2",
        )
        self.btn_exit.pack(side=tk.RIGHT)

    def _create_indicator_card(self, parent, col: int, title: str, subtitle: str):
        card = tk.Frame(parent, bg="#0f172a", bd=1, relief=tk.RIDGE, padx=12, pady=10)
        card.grid(row=0, column=col, sticky="nsew", padx=6)

        tk.Label(card, text=title, font=("Segoe UI", 11, "bold"), fg="#f8fafc", bg="#0f172a").pack()
        tk.Label(card, text=subtitle, font=("Segoe UI", 8), fg="#94a3b8", bg="#0f172a").pack(pady=(0, 8))

        canvas = tk.Canvas(card, width=54, height=54, bg="#0f172a", highlightthickness=0)
        canvas.pack()
        circle_id = canvas.create_oval(5, 5, 49, 49, fill="#334155", outline="#64748b", width=2)

        val_label = tk.Label(card, text="0 (OFF)", font=("Consolas", 13, "bold"), fg="#94a3b8", bg="#0f172a")
        val_label.pack(pady=(6, 0))

        return {"canvas": canvas, "circle": circle_id, "label": val_label}

    def _update_indicator_card(self, card, value: int, active_color="#22c55e"):
        if value == 1:
            card["canvas"].itemconfig(card["circle"], fill=active_color, outline="#bbf7d0")
            card["label"].config(text="1 (ON)", fg=active_color)
        else:
            card["canvas"].itemconfig(card["circle"], fill="#334155", outline="#64748b")
            card["label"].config(text="0 (OFF)", fg="#94a3b8")

    def log_message(self, msg: str):
        now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{now}] {msg}\n"
        print(line.strip())

        def _append():
            if not self.root.winfo_exists():
                return
            self.log_text.configure(state="normal")
            self.log_text.insert(tk.END, line)
            self.log_text.see(tk.END)
            self.log_text.configure(state="disabled")

        self.root.after(0, _append)

    # ==========================================================================
    # KONEKSI & POLLING PEMBACAAN FINS (W0.00, W0.01, DAN 100.00)
    # ==========================================================================
    def connect_plc(self):
        self._close_current_connection()

        mode = self.mode_var.get()
        ip = self.ip_var.get().strip()
        try:
            port = int(self.port_var.get().strip())
            da1 = int(self.da1_var.get().strip())
            sa1 = int(self.sa1_var.get().strip())
        except ValueError:
            messagebox.showerror("Input Error", "Port, PLC Node (DA1), dan PC Node (SA1) harus berupa angka bulat!")
            return

        try:
            if mode.startswith("SIMULATOR"):
                self.connection = SimulatedFinsConnection(auto_ladder=True)
                self.plc = FINS(self.connection)
                self.is_connected = True
                self.status_text_var.set("Status: Terhubung (Mode Simulator Lokal)")
                self.log_message("✅ Terhubung ke Simulator FINS Omron (Siap uji W0.00, W0.01, dan 100.00).")
            elif mode.startswith("FINS/UDP"):
                self.connection = UDPFinsConnection(ip, port=port, dest_node=da1, src_node=sa1)
                self.plc = FINS(self.connection)
                self.is_connected = True
                self.status_text_var.set(f"Status: FINS/UDP {ip}:{port}")
                self.log_message(f"✅ Membuka koneksi FINS/UDP ke PLC Omron ({ip}:{port}, DA1={da1}, SA1={sa1})...")
            elif mode.startswith("FINS/TCP"):
                self.connection = TCPFinsConnection(ip, port=port)
                self.plc = FINS(self.connection)
                self.is_connected = True
                self.status_text_var.set(f"Status: FINS/TCP {ip}:{port}")
                self.log_message(f"✅ Membuka koneksi FINS/TCP ke PLC Omron ({ip}:{port})...")
            else:
                self.connection = TCPHostLinkConnection(ip, port=port)
                self.plc = FINS(self.connection)
                self.is_connected = True
                self.status_text_var.set(f"Status: HostLink TCP {ip}:{port}")
                self.log_message(f"✅ Membuka koneksi Host Link FINS TCP ke ({ip}:{port})...")

            if self.polling_thread is None or not self.polling_thread.is_alive():
                self.stop_event.clear()
                self.polling_thread = threading.Thread(target=self._poll_plc_worker, daemon=True)
                self.polling_thread.start()

        except Exception as e:
            self.is_connected = False
            self.status_text_var.set("Status: Gagal Terhubung")
            self.log_message(f"❌ Gagal inisialisasi koneksi FINS: {e}")

    def _poll_plc_worker(self):
        """Thread background untuk membaca W0.00, W0.01, dan CIO 100.00 dari PLC."""
        prev_states = (None, None, None)

        while not self.stop_event.is_set():
            if self.is_connected and self.plc is not None:
                try:
                    with self.fins_lock:
                        # 1. Baca W0.00 dan W0.01 sekaligus (2 bit mulai dari WR Word 0, Bit 0)
                        wr_bits = self.plc.memory_area_read(
                            WR_BIT, address_word=0, address_bit=0, num_items=2
                        )
                        # 2. Baca Output 100.00 (1 bit dari CIO Word 100, Bit 0)
                        cio_100_00 = self.plc.memory_area_read_single(
                            CIO_BIT, address_word=100, address_bit=0
                        )

                    if wr_bits is not None and len(wr_bits) >= 2 and cio_100_00 is not None:
                        self.val_w000 = 1 if wr_bits[0] else 0
                        self.val_w001 = 1 if wr_bits[1] else 0
                        self.val_10000 = 1 if cio_100_00 else 0

                        cur_states = (self.val_w000, self.val_w001, self.val_10000)
                        if cur_states != prev_states:
                            self.log_message(
                                f"📥 [READ PLC] W0.00={self.val_w000} | W0.01={self.val_w001} | 100.00={self.val_10000}"
                            )
                            prev_states = cur_states

                        self.root.after(0, self._refresh_indicators)
                except Exception as e:
                    self.log_message(f"⚠️ Error saat membaca PLC: {e}")
                    time.sleep(1.0)

            self.stop_event.wait(0.2)

    def _refresh_indicators(self):
        if not self.root.winfo_exists():
            return
        self._update_indicator_card(self.card_w000, self.val_w000, active_color="#22c55e")
        self._update_indicator_card(self.card_w001, self.val_w001, active_color="#ef4444")
        self._update_indicator_card(self.card_10000, self.val_10000, active_color="#38bdf8")

    # ==========================================================================
    # AKSI TOMBOL W0.00 (NYALAKAN 100.00) & W0.01 (MATIKAN 100.00)
    # ==========================================================================
    def on_press_w000(self):
        """Saat tombol W0.00 ditekan: Tulis W0.00 = 1 dan nyalakan 100.00 = 1."""
        if not self.is_connected or self.plc is None:
            return
        threading.Thread(target=self._write_w000_action, args=(1,), daemon=True).start()

    def on_release_w000(self):
        """Saat tombol W0.00 dilepas: Kembalikan push-button W0.00 = 0 (Output 100.00 tetap ON/Latch)."""
        if not self.is_connected or self.plc is None:
            return
        threading.Thread(target=self._write_w000_action, args=(0,), daemon=True).start()

    def _write_w000_action(self, bit_val: int):
        try:
            with self.fins_lock:
                # Tulis ke W0.00 (WR_BIT, word=0, bit=0)
                self.plc.memory_area_write(WR_BIT, address_word=0, address_bit=0, values=bit_val)
                # Jika tombol ditekan (bit_val == 1) dan opsi tulis langsung ke 100.00 aktif:
                if bit_val == 1 and self.direct_write_100_var.get():
                    self.plc.memory_area_write(CIO_BIT, address_word=100, address_bit=0, values=1)
            if bit_val == 1:
                self.log_message("📤 [WRITE PLC] Tombol W0.00 DITEKAN (W0.00=1) -> Menyalakan Output 100.00 (ON)")
            else:
                self.log_message("📤 [WRITE PLC] Tombol W0.00 DILEPAS (W0.00=0) -> Output 100.00 tetap Menyala (1)")
        except Exception as e:
            self.log_message(f"❌ Gagal menulis W0.00: {e}")

    def on_press_w001(self):
        """Saat tombol W0.01 ditekan: Tulis W0.01 = 1 dan matikan 100.00 = 0."""
        if not self.is_connected or self.plc is None:
            return
        threading.Thread(target=self._write_w001_action, args=(1,), daemon=True).start()

    def on_release_w001(self):
        """Saat tombol W0.01 dilepas: Kembalikan push-button W0.01 = 0 (Output 100.00 tetap OFF)."""
        if not self.is_connected or self.plc is None:
            return
        threading.Thread(target=self._write_w001_action, args=(0,), daemon=True).start()

    def _write_w001_action(self, bit_val: int):
        try:
            with self.fins_lock:
                # Tulis ke W0.01 (WR_BIT, word=0, bit=1)
                self.plc.memory_area_write(WR_BIT, address_word=0, address_bit=1, values=bit_val)
                # Jika tombol ditekan (bit_val == 1) dan opsi tulis langsung ke 100.00 aktif:
                if bit_val == 1 and self.direct_write_100_var.get():
                    self.plc.memory_area_write(CIO_BIT, address_word=100, address_bit=0, values=0)
            if bit_val == 1:
                self.log_message("📤 [WRITE PLC] Tombol W0.01 DITEKAN (W0.01=1) -> Mematikan Output 100.00 (OFF)")
            else:
                self.log_message("📤 [WRITE PLC] Tombol W0.01 DILEPAS (W0.01=0) -> Output 100.00 tetap Mati (0)")
        except Exception as e:
            self.log_message(f"❌ Gagal menulis W0.01: {e}")

    # ==========================================================================
    # FUNGSI EXIT / MEMATIKAN PROGRAM DENGAN AMAN
    # ==========================================================================
    def _bind_shortcuts(self):
        self.root.protocol("WM_DELETE_WINDOW", self.exit_program)
        self.root.bind("<Escape>", lambda e: self.exit_program())

    def _close_current_connection(self):
        self.is_connected = False
        if self.connection is not None and hasattr(self.connection, "close"):
            try:
                self.connection.close()
            except Exception:
                pass
        self.connection = None
        self.plc = None

    def exit_program(self):
        """Menghentikan thread polling, menutup socket FINS, dan keluar dari aplikasi."""
        print("\n🛑 Mematikan program Omron FINS GUI...")
        self.stop_event.set()
        self._close_current_connection()
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass
        print("✅ Program Omron FINS telah dimatikan dengan aman.")
        sys.exit(0)


if __name__ == "__main__":
    root = tk.Tk()
    app = OmronFinsApp(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        app.exit_program()
