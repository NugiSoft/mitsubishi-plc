import json
import msvcrt
import subprocess
import sys
import threading

# Nama ProgID standar Mitsubishi MX OPC Server 6.10
OPC_PROG_ID = "Mitsubishi.MXOPC.6"

# Path PowerShell 32-bit (wajib karena MX OPC Server & OpcRcw berjalan di arsitektur 32-bit/x86)
PS32_PATH = r"C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe"

ps_script = r"""
$ErrorActionPreference = 'Stop'

$comnDll = "C:\Program Files (x86)\FANUC\ROBOGUIDE\bin\OpcRcw.Comn.dll"
$daDll   = "C:\Program Files (x86)\FANUC\ROBOGUIDE\bin\OpcRcw.Da.dll"

# Load assembly ke AppDomain runtime terlebih dahulu agar tipe OpcRcw.Da dikenali
[Reflection.Assembly]::LoadFrom($comnDll) | Out-Null
[Reflection.Assembly]::LoadFrom($daDll) | Out-Null

$refs = @($comnDll, $daDll)

$code = @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using OpcRcw.Da;

public class MxOpcReader {
    private static List<string> ReadEnum(IEnumString enumStr) {
        var list = new List<string>();
        if (enumStr == null) return list;
        string[] buf = new string[100];
        int fetched = 0;
        while (true) {
            enumStr.RemoteNext(buf.Length, buf, out fetched);
            if (fetched <= 0) break;
            for (int i = 0; i < fetched; i++) list.Add(buf[i]);
        }
        return list;
    }

    private static void BrowseBranch(IOPCBrowseServerAddressSpace browser, List<string> results, int depth) {
        if (depth > 5) return;
        try {
            IEnumString enumLeaves;
            browser.BrowseOPCItemIDs(OPCBROWSETYPE.OPC_LEAF, "", 0, 0, out enumLeaves);
            foreach (var leaf in ReadEnum(enumLeaves)) {
                string fullId;
                browser.GetItemID(leaf, out fullId);
                if (!string.IsNullOrEmpty(fullId) && !results.Contains(fullId)) results.Add(fullId);
            }
        } catch {}

        try {
            IEnumString enumBranches;
            browser.BrowseOPCItemIDs(OPCBROWSETYPE.OPC_BRANCH, "", 0, 0, out enumBranches);
            foreach (var branch in ReadEnum(enumBranches)) {
                if (branch.StartsWith("$") || branch.StartsWith("_") || branch.StartsWith("\\")) continue;
                try {
                    browser.ChangeBrowsePosition(OPCBROWSEDIRECTION.OPC_BROWSE_DOWN, branch);
                    BrowseBranch(browser, results, depth + 1);
                    browser.ChangeBrowsePosition(OPCBROWSEDIRECTION.OPC_BROWSE_UP, "");
                } catch {}
            }
        } catch {}
    }

    public static List<string> BrowseAll(object serverObj) {
        var list = new List<string>();
        if (serverObj == null) return list;
        try {
            var browser = (IOPCBrowseServerAddressSpace)serverObj;
            try {
                IEnumString enumFlat;
                browser.BrowseOPCItemIDs(OPCBROWSETYPE.OPC_FLAT, "", 0, 0, out enumFlat);
                foreach (var item in ReadEnum(enumFlat)) {
                    if (!list.Contains(item)) list.Add(item);
                }
            } catch {}
            if (list.Count == 0) {
                BrowseBranch(browser, list, 0);
            }
        } catch {}
        return list;
    }

    public static object AddGroup(object serverObj, out int serverGroupHandle) {
        var server = (IOPCServer)serverObj;
        Guid iidItemMgt = typeof(IOPCItemMgt).GUID;
        object groupObj;
        int revisedRate;
        server.AddGroup("PythonAlarmGroup", 1, 200, 1, IntPtr.Zero, IntPtr.Zero, 0, out serverGroupHandle, out revisedRate, ref iidItemMgt, out groupObj);
        return groupObj;
    }

    public static int[] AddItems(object groupObj, string[] itemIds, out int[] errors) {
        int count = itemIds.Length;
        int[] serverHandles = new int[count];
        errors = new int[count];
        for (int i = 0; i < count; i++) errors[i] = -1;

        IntPtr pResults = IntPtr.Zero;
        IntPtr pErrors = IntPtr.Zero;
        try {
            var itemMgt = (IOPCItemMgt)groupObj;
            var defs = new OPCITEMDEF[count];
            for (int i = 0; i < count; i++) {
                defs[i].szAccessPath = "";
                defs[i].szItemID = itemIds[i];
                defs[i].bActive = 1;
                defs[i].hClient = i + 1;
                defs[i].dwBlobSize = 0;
                defs[i].pBlob = IntPtr.Zero;
                defs[i].vtRequestedDataType = 0;
            }
            itemMgt.AddItems(count, defs, out pResults, out pErrors);

            if (pErrors != IntPtr.Zero) {
                Marshal.Copy(pErrors, errors, 0, count);
            }
            if (pResults != IntPtr.Zero) {
                IntPtr pos = pResults;
                int structSize = Marshal.SizeOf(typeof(OPCITEMRESULT));
                for (int i = 0; i < count; i++) {
                    var res = (OPCITEMRESULT)Marshal.PtrToStructure(pos, typeof(OPCITEMRESULT));
                    serverHandles[i] = res.hServer;
                    if (res.pBlob != IntPtr.Zero) Marshal.FreeCoTaskMem(res.pBlob);
                    pos = new IntPtr(pos.ToInt64() + structSize);
                }
            }
        } catch {
        } finally {
            if (pResults != IntPtr.Zero) Marshal.FreeCoTaskMem(pResults);
            if (pErrors != IntPtr.Zero) Marshal.FreeCoTaskMem(pErrors);
        }
        return serverHandles;
    }

    public static void ReadSync(object groupObj, bool fromDevice, int[] serverHandles, out object[] values, out short[] qualities, out int[] errors) {
        var syncIO = (IOPCSyncIO)groupObj;
        int count = serverHandles.Length;
        IntPtr pValues = IntPtr.Zero;
        IntPtr pErrors = IntPtr.Zero;
        syncIO.Read(fromDevice ? OPCDATASOURCE.OPC_DS_DEVICE : OPCDATASOURCE.OPC_DS_CACHE, count, serverHandles, out pValues, out pErrors);

        values = new object[count];
        qualities = new short[count];
        errors = new int[count];
        Marshal.Copy(pErrors, errors, 0, count);

        IntPtr pos = pValues;
        int structSize = Marshal.SizeOf(typeof(OPCITEMSTATE));
        for (int i = 0; i < count; i++) {
            var state = (OPCITEMSTATE)Marshal.PtrToStructure(pos, typeof(OPCITEMSTATE));
            values[i] = state.vDataValue;
            qualities[i] = state.wQuality;
            pos = new IntPtr(pos.ToInt64() + structSize);
        }
        if (pValues != IntPtr.Zero) Marshal.FreeCoTaskMem(pValues);
        if (pErrors != IntPtr.Zero) Marshal.FreeCoTaskMem(pErrors);
    }

    public static void Disconnect(object serverObj, object groupObj, int serverGroupHandle) {
        try {
            if (serverObj != null && serverGroupHandle != 0) {
                var server = (IOPCServer)serverObj;
                server.RemoveGroup(serverGroupHandle, 1);
            }
        } catch {}
        try {
            if (groupObj != null) Marshal.ReleaseComObject(groupObj);
        } catch {}
        try {
            if (serverObj != null) Marshal.ReleaseComObject(serverObj);
        } catch {}
    }
}
"@

Add-Type -ReferencedAssemblies $refs -TypeDefinition $code

function Format-BitValue($val) {
    if ($null -eq $val) { return $null }
    if ($val -is [Array]) {
        if ($val.Length -gt 0) { $val = $val[0] } else { return $null }
    }
    if ($val -is [bool]) {
        return $(if ($val) { 1 } else { 0 })
    }
    try {
        return [int]$val
    } catch {
        return "$val"
    }
}

$serverObj = $null
$groupObj = $null
$serverGroupHandle = 0

try {
    $progId = "Mitsubishi.MXOPC.6"
    $t = [Type]::GetTypeFromProgID($progId)
    if ($null -eq $t) {
        Write-Host "❌ ProgID $progId tidak ditemukan!"
        exit 1
    }

    $serverObj = [Activator]::CreateInstance($t)
    Write-Host "✅ Berhasil terhubung langsung ke $progId (Synchronous OPC DA)!"

    # 1. Browse semua tag yang terdaftar di MX OPC Server (Flat & Branch)
    $allTags = [MxOpcReader]::BrowseAll($serverObj)
    $userTags = @($allTags | Where-Object { $_ -notlike "\*" -and $_ -notlike "$*" -and $_ -notlike "_*" })
    if ($userTags.Count -gt 0) {
        Write-Host ("📋 Daftar Tag yang ditemukan di MX OPC Server: " + ($userTags -join ", "))
    } else {
        Write-Host "⚠️ Belum ada user tag di Address Space aktif MX OPC (pastikan sudah klik File -> Make Active di MX Configurator)."
    }

    # 2. Tentukan kandidat nama Tag untuk M1501 (Tag002) dan M1531 (Tag003)
    $emgCandidates = @(
        "Dev01.Group001.Tag002",
        "Dev01.Tag002",
        "Dev01.M1501",
        "PLC1.M1501"
    )
    $airCandidates = @(
        "Dev01.Group001.Tag003",
        "Dev01.Tag003",
        "Dev01.M1531",
        "PLC1.M1531"
    )

    foreach ($bt in $userTags) {
        if ($bt -match "Tag002|1501" -and $emgCandidates -notcontains $bt) {
            $emgCandidates = @($bt) + $emgCandidates
        }
        if ($bt -match "Tag003|1531" -and $airCandidates -notcontains $bt) {
            $airCandidates = @($bt) + $airCandidates
        }
    }

    $groupObj = [MxOpcReader]::AddGroup($serverObj, [ref]$serverGroupHandle)

    $selectedEmg = $null
    $selectedAir = $null
    $emgHandle = 0
    $airHandle = 0

    foreach ($cand in $emgCandidates) {
        $errs = $null
        $handles = [MxOpcReader]::AddItems($groupObj, @($cand), [ref]$errs)
        if ($errs[0] -eq 0 -and $handles[0] -ne 0) {
            $selectedEmg = $cand
            $emgHandle = $handles[0]
            break
        }
    }

    foreach ($cand in $airCandidates) {
        $errs = $null
        $handles = [MxOpcReader]::AddItems($groupObj, @($cand), [ref]$errs)
        if ($errs[0] -eq 0 -and $handles[0] -ne 0) {
            $selectedAir = $cand
            $airHandle = $handles[0]
            break
        }
    }

    if ($null -eq $selectedEmg -or $null -eq $selectedAir) {
        Write-Host "❌ Gagal menambahkan Tag M1501/M1531 ke OPC Group."
        Write-Host "   Pastikan di MX Configurator Anda sudah klik menu: File -> Make Active pada database 2.mdb, lalu klik tombol Run (Hijau)!"
        exit 1
    }

    Write-Host "✅ Tag aktif digunakan: Emergency = [$selectedEmg], Air Pressure = [$selectedAir]"
    Write-Host "Mulai memonitor secara Synchronous (OPC_DS_DEVICE)..."

    $handlesToRead = @([int]$emgHandle, [int]$airHandle)

    while ($true) {
        $vals = $null
        $quals = $null
        $readErrs = $null

        # Baca langsung dari Device (PLC / GX Simulator2) secara Synchronous
        [MxOpcReader]::ReadSync($groupObj, $true, $handlesToRead, [ref]$vals, [ref]$quals, [ref]$readErrs)

        $vEmg = Format-BitValue $vals[0]
        $vAir = Format-BitValue $vals[1]

        $payload = @{
            emg_tag  = $selectedEmg
            emg_val  = $vEmg
            emg_qual = [int]$quals[0]
            emg_err  = [int]$readErrs[0]
            air_tag  = $selectedAir
            air_val  = $vAir
            air_qual = [int]$quals[1]
            air_err  = [int]$readErrs[1]
        } | ConvertTo-Json -Compress

        Write-Host $payload
        Start-Sleep -Milliseconds 500
    }
} catch {
    Write-Host "❌ Error OPC DA: $($_.Exception.Message)"
    exit 1
} finally {
    [MxOpcReader]::Disconnect($serverObj, $groupObj, $serverGroupHandle)
}
"""

print(f"Mencoba connect ke: {OPC_PROG_ID} menggunakan Synchronous OPC DA (OpcRcw.Da)...")
print("💡 Tekan tombol [Q], [ESC], atau [Ctrl+C] kapan saja untuk mematikan program.\n")

stop_event = threading.Event()

proc = subprocess.Popen(
    [PS32_PATH, "-NoProfile", "-Command", ps_script],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1,
)


def shutdown_program(reason="Monitoring dihentikan oleh pengguna."):
    """Mematikan proses PowerShell 32-bit dan keluar dari program dengan bersih."""
    if not stop_event.is_set():
        stop_event.set()
        print(f"\n🛑 {reason}")
        print("Memutuskan koneksi MX OPC Server dan mematikan program...")
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:
        pass


def keyboard_listener():
    while not stop_event.is_set():
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            # 'q', 'Q', atau ESC (\x1b)
            if ch in ("q", "Q", "\x1b"):
                key_name = "ESC" if ch == "\x1b" else ch.upper()
                shutdown_program(f"Tombol [{key_name}] ditekan — mematikan program.")
                break
        stop_event.wait(0.1)


kb_thread = threading.Thread(target=keyboard_listener, daemon=True)
kb_thread.start()

try:
    for line in proc.stdout:
        if stop_event.is_set():
            break
        line = line.strip()
        if not line:
            continue
        if line.startswith("{") and line.endswith("}"):
            data = json.loads(line)
            q_emg = data["emg_qual"]
            status_str = "GOOD (192)" if q_emg == 192 else f"QUALITY={q_emg}"
            print(
                f"[{status_str}] "
                f"{data['emg_tag']} (M1501): {data['emg_val']} | "
                f"{data['air_tag']} (M1531): {data['air_val']}"
            )
        else:
            print(line)
except KeyboardInterrupt:
    shutdown_program("Ctrl+C ditekan — mematikan program.")
finally:
    shutdown_program()
    print("✅ Program telah dimatikan dengan aman.")
    sys.exit(0)


