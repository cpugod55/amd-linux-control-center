#!/usr/bin/env python3
"""AMDGPU discovery, telemetry/capability probing, and validated sysfs I/O.

Extracted from the main application in v0.94.3 without intentional behavior changes.
"""
import glob
import os
import re
import shutil
import subprocess

PROFILE_APPLY_HELPER_LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile_apply_helper.py")
PROFILE_APPLY_HELPER_SYSTEM = "/usr/local/libexec/amd-linux-control-center-profile-helper"
PROFILE_APPLY_HELPER = (
    PROFILE_APPLY_HELPER_SYSTEM
    if os.path.exists(PROFILE_APPLY_HELPER_SYSTEM)
    else PROFILE_APPLY_HELPER_LOCAL
)

def read_text(path, default=""):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    except Exception:
        return default

def read_int(path, default=None):
    try:
        return int(read_text(path))
    except Exception:
        return default

def human_bytes(n):
    if n is None:
        return "—"
    n = float(n)
    for u in ("B","KB","MB","GB","TB"):
        if n < 1024 or u == "TB":
            return f"{n:.1f} {u}"
        n /= 1024

def run_cmd(cmd):
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
    except Exception:
        return ""

def active_clock(raw):
    if not raw:
        return None
    for line in raw.splitlines():
        if "*" in line:
            m = re.search(r"(\d+)\s*Mhz", line, re.I)
            if m:
                return int(m.group(1))
    return None

def _privileged_helper_can_write(path, value):
    if not os.path.exists(PROFILE_APPLY_HELPER):
        return False
    base=os.path.basename(os.path.realpath(path))
    allowed={
        "power_dpm_force_performance_level","pp_power_profile_mode","power1_cap",
        "pp_dpm_sclk","pp_dpm_mclk","pp_dpm_socclk","pp_dpm_fclk","pp_dpm_pcie",
        "pwm1_enable","pwm1",
    }
    return base in allowed

def _is_atomic_host():
    return os.path.exists("/run/ostree-booted") or shutil.which("rpm-ostree") is not None

def passwordless_gpu_authorization_active(timeout=8.0):
    """Return True only when the installed hardened helper can run noninteractively.

    This is the single runtime authorization check used by both the GUI and
    GPU backend. Atomic hosts verify the installer-created sudoers path with
    ``sudo -n``. Mutable hosts verify ALCC's PolicyKit action without allowing
    an authentication agent. A slightly generous timeout avoids false
    negatives on rpm-ostree hosts where first invocation can take a few
    seconds even though no authentication is required.
    """
    if not (os.path.isfile(PROFILE_APPLY_HELPER_SYSTEM) and os.access(PROFILE_APPLY_HELPER_SYSTEM, os.X_OK)):
        return False
    try:
        if _is_atomic_host():
            if not shutil.which("sudo"):
                return False
            probe=subprocess.run(
                ["sudo","-n",PROFILE_APPLY_HELPER_SYSTEM],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=timeout, check=False
            )
            return probe.returncode == 0
        if not shutil.which("pkexec"):
            return False
        probe=subprocess.run(
            ["pkexec","--disable-internal-agent",PROFILE_APPLY_HELPER_SYSTEM],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=timeout, check=False
        )
        return probe.returncode == 0
    except Exception:
        return False

def privileged_helper_command(helper_args=None):
    """Return the single approved command path for the hardened GPU helper.

    Atomic hosts prefer the installer-created sudoers rule via `sudo -n`,
    which can never open an authentication dialog. Mutable hosts fall back to
    the custom PolicyKit action through pkexec.
    """
    if not os.path.exists(PROFILE_APPLY_HELPER):
        raise RuntimeError("AMD Linux Control Center privileged helper was not found.")
    helper_args=list(helper_args or [])
    system_helper=(PROFILE_APPLY_HELPER == PROFILE_APPLY_HELPER_SYSTEM)
    if system_helper and _is_atomic_host():
        # Do not gate real GPU writes on a separate authorization probe.  On
        # atomic hosts the installer grants NOPASSWD only to this exact helper;
        # execute that same command directly with sudo -n and let its real exit
        # status be authoritative.  This avoids false negatives where a status
        # probe disagrees with the command that sudoers actually permits.
        if not shutil.which("sudo"):
            raise RuntimeError("Atomic-host GPU control requires sudo, but sudo is unavailable.")
        return ["sudo","-n",PROFILE_APPLY_HELPER_SYSTEM]+helper_args
    if _is_atomic_host():
        raise RuntimeError(
            "The installed AMD Linux Control Center GPU helper is unavailable on this atomic host. "
            "Re-run the ALCC installer to repair the narrowly scoped helper authorization."
        )
    if not shutil.which("pkexec"):
        raise RuntimeError("This setting requires administrator access, but neither passwordless helper authorization nor pkexec is available.")
    return ["pkexec",PROFILE_APPLY_HELPER]+helper_args

def run_privileged_helper(helper_args=None):
    cmd=privileged_helper_command(helper_args)
    proc=subprocess.run(cmd,text=True,capture_output=True)
    if proc.returncode!=0:
        raw=(proc.stderr or proc.stdout or "Administrator GPU write was cancelled or failed.").strip()
        if cmd[:2] == ["sudo", "-n"] and ("password is required" in raw.lower() or "a terminal is required" in raw.lower()):
            raise RuntimeError(
                "Passwordless GPU authorization is not active for the hardened ALCC helper on this atomic host. "
                "Re-run the ALCC installer to repair the narrowly scoped sudoers authorization."
            )
        raise RuntimeError(raw)
    return proc

def _run_privileged_helper_sets(pairs):
    helper_args=[]
    for path,value in pairs:
        helper_args += ["--set",f"{os.path.realpath(path)}={value}"]
    run_privileged_helper(helper_args)

def atomic_write_sysfs(path, value):
    """Write one validated sysfs setting.
    Prefer the PolicyKit-authorized hardened helper when installed so ordinary
    GPU control does not fall back to an unrelated `pkexec sh` action.
    """
    path=os.path.realpath(path)
    value=str(value)
    if not path.startswith("/sys/"):
        raise RuntimeError("Refusing to write outside /sys")

    if os.access(path,os.W_OK):
        with open(path,"w",encoding="ascii") as f:
            f.write(value)
        return

    if _privileged_helper_can_write(path,value):
        _run_privileged_helper_sets([(path,value)])
        return

    # Do not fall back to a generic privileged shell.  Every privileged GPU
    # write must pass through ALCC's hardened helper so the PolicyKit rule can
    # remain narrowly scoped and immutable-host sessions never receive surprise
    # authentication prompts from an unrelated pkexec action.
    raise RuntimeError(
        f"Privileged write to {os.path.basename(path)} is not supported by the hardened ALCC helper."
    )

def atomic_write_sysfs_many(pairs):
    """Write multiple validated sysfs settings in one privileged transaction."""
    clean=[]
    for path,value in pairs:
        path=os.path.realpath(path)
        if not path.startswith("/sys/"):
            raise RuntimeError("Refusing to write outside /sys")
        clean.append((path,str(value)))

    if not clean:
        return

    if all(os.access(path,os.W_OK) for path,_ in clean):
        for path,value in clean:
            with open(path,"w",encoding="ascii") as f:
                f.write(value)
        return

    # If every write belongs to our hardened allow-list, use the exact helper
    # executable referenced by the PolicyKit action/rule. This is the path that
    # can be passwordless when the optional authorization is enabled.
    if all(_privileged_helper_can_write(path,value) for path,value in clean):
        _run_privileged_helper_sets(clean)
        return

    unsupported=sorted({os.path.basename(path) for path,_ in clean
                        if not _privileged_helper_can_write(path,_)})
    raise RuntimeError(
        "Privileged GPU write is not supported by the hardened ALCC helper: "
        + ", ".join(unsupported)
    )

class AMDGPU:
    def __init__(self, card_path):
        self.card_path = card_path
        self.card_name = os.path.basename(card_path)
        self.device = os.path.realpath(os.path.join(card_path, "device"))
        hm = glob.glob(os.path.join(self.device, "hwmon", "hwmon*"))
        self.hwmon = hm[0] if hm else None

    @staticmethod
    def discover():
        out = []
        for card in sorted(glob.glob("/sys/class/drm/card*")):
            base = os.path.basename(card)
            if not re.fullmatch(r"card\d+", base):
                continue
            dev = os.path.join(card, "device")
            if not os.path.exists(dev):
                continue
            vendor = read_text(os.path.join(dev, "vendor")).lower()
            driver = ""
            dlink = os.path.join(dev, "driver")
            if os.path.exists(dlink):
                driver = os.path.basename(os.path.realpath(dlink))
            if vendor == "0x1002" and driver == "amdgpu":
                out.append(AMDGPU(card))
        return out

    def pci_slot(self):
        return os.path.basename(self.device)

    def product_name(self):
        slot = self.pci_slot()
        line = run_cmd(["lspci", "-s", slot])
        if line:
            return re.sub(r"^[0-9a-fA-F:.]+\s+", "", line)
        return f"AMD Radeon ({slot})"

    def short_name(self):
        n = self.product_name()
        n = re.sub(r"^VGA compatible controller:\s*", "", n, flags=re.I)
        n = re.sub(r"^Display controller:\s*", "", n, flags=re.I)
        return f"{self.card_name} — {n}"

    def vram_total(self):
        return read_int(os.path.join(self.device, "mem_info_vram_total"), 0) or 0

    def metric(self):
        d = {}
        d["busy"] = read_int(os.path.join(self.device, "gpu_busy_percent"))
        d["vram_total"] = read_int(os.path.join(self.device, "mem_info_vram_total"))
        d["vram_used"] = read_int(os.path.join(self.device, "mem_info_vram_used"))
        d["perf_level"] = read_text(os.path.join(self.device, "power_dpm_force_performance_level"), "—")
        d["sclk_raw"] = read_text(os.path.join(self.device, "pp_dpm_sclk"))
        d["mclk_raw"] = read_text(os.path.join(self.device, "pp_dpm_mclk"))
        d["pcie_raw"] = read_text(os.path.join(self.device, "pp_dpm_pcie"))
        d["sclk"] = None
        d["mclk"] = None
        d["voltage_mv"] = None
        d["voltage_v"] = None
        d["electrical_efficiency_mhz_per_w"] = None
        d["temps"] = {}
        d["fan_rpm"] = None
        d["fan_max"] = None
        d["pwm"] = None
        d["fan_percent"] = None
        d["power_w"] = None
        d["power_cap_w"] = None
        d["power_cap_min_w"] = None
        d["power_cap_max_w"] = None

        if self.hwmon:
            # Prefer hwmon frequency inputs: values are normally Hz.
            f1 = read_int(os.path.join(self.hwmon, "freq1_input"))
            f2 = read_int(os.path.join(self.hwmon, "freq2_input"))
            l1 = read_text(os.path.join(self.hwmon, "freq1_label")).lower()
            l2 = read_text(os.path.join(self.hwmon, "freq2_label")).lower()
            for val, lab in ((f1,l1),(f2,l2)):
                if val is None: continue
                mhz = val / 1_000_000.0
                if "sclk" in lab or "gfx" in lab:
                    d["sclk"] = mhz
                elif "mclk" in lab or "mem" in lab:
                    d["mclk"] = mhz

            for p in sorted(glob.glob(os.path.join(self.hwmon, "temp*_input"))):
                val = read_int(p)
                if val is None: continue
                label = read_text(p.replace("_input","_label"), os.path.basename(p).replace("_input",""))
                d["temps"][label.lower()] = val / 1000.0

            d["fan_rpm"] = read_int(os.path.join(self.hwmon, "fan1_input"))
            d["fan_max"] = read_int(os.path.join(self.hwmon, "fan1_max"))
            d["pwm"] = read_int(os.path.join(self.hwmon, "pwm1"))
            pwm_min = read_int(os.path.join(self.hwmon, "pwm1_min"), 0)
            pwm_max = read_int(os.path.join(self.hwmon, "pwm1_max"), 255)
            if d["pwm"] is not None and pwm_min is not None and pwm_max is not None and pwm_max > pwm_min:
                d["fan_percent"] = max(0.0, min(100.0, (d["pwm"] - pwm_min) * 100.0 / (pwm_max - pwm_min)))

            vin = read_int(os.path.join(self.hwmon, "in0_input"))
            if vin is not None:
                d["voltage_mv"] = vin
                d["voltage_v"] = vin / 1000.0

            pwr = read_int(os.path.join(self.hwmon, "power1_average"))
            if pwr is None:
                pwr = read_int(os.path.join(self.hwmon, "power1_input"))
            if pwr is not None:
                d["power_w"] = pwr / 1_000_000.0

            for key, fn in (
                ("power_cap_w","power1_cap"),
                ("power_cap_min_w","power1_cap_min"),
                ("power_cap_max_w","power1_cap_max"),
            ):
                val = read_int(os.path.join(self.hwmon, fn))
                if val is not None:
                    d[key] = val / 1_000_000.0

        if d["sclk"] is None:
            v = active_clock(d["sclk_raw"])
            d["sclk"] = float(v) if v is not None else None
        if d["mclk"] is None:
            v = active_clock(d["mclk_raw"])
            d["mclk"] = float(v) if v is not None else None
        if d["sclk"] is not None and d["power_w"] not in (None,0):
            d["electrical_efficiency_mhz_per_w"] = d["sclk"] / d["power_w"]
        return d

    def dpm_states(self, domain):
        if domain not in ("sclk","mclk"):
            return []
        raw=read_text(os.path.join(self.device,f"pp_dpm_{domain}"))
        out=[]
        for line in raw.splitlines():
            m=re.match(r"\s*(\d+):\s*(\d+)Mhz\s*(\*)?",line,re.I)
            if m:
                out.append({
                    "index":int(m.group(1)),
                    "mhz":int(m.group(2)),
                    "active":bool(m.group(3))
                })
        return out

    def dpm_domain_states(self, domain):
        path=os.path.join(self.device,f"pp_dpm_{domain}")
        if not os.path.exists(path):
            return []
        raw=read_text(path)
        out=[]
        for line in raw.splitlines():
            # Examples:
            # 0: 500Mhz *
            # 1: 16.0GT/s, x8 619Mhz *
            m=re.match(r"\s*(\d+):\s*(.*?)\s*(\*)?\s*$",line)
            if not m:
                continue
            out.append({
                "index":int(m.group(1)),
                "text":m.group(2).strip(),
                "active":bool(m.group(3))
            })
        return out

    def dpm_clock_domains(self):
        """Return only DPM clock-domain files actually exposed by this AMDGPU."""
        domains=(
            ("GFX / SCLK","pp_dpm_sclk"),
            ("Memory / MCLK","pp_dpm_mclk"),
            ("SOC","pp_dpm_socclk"),
            ("Fabric / FCLK","pp_dpm_fclk"),
            ("Display / DCEFCLK","pp_dpm_dcefclk"),
            ("PCIe","pp_dpm_pcie"),
        )
        out=[]
        for label,filename in domains:
            path=os.path.join(self.device,filename)
            if os.path.exists(path):
                out.append((label,filename,path))
        return out

    def dpm_domain_access(self, path):
        """Classify an exposed DPM sysfs node without confusing user write access
        with driver support. Sysfs ownership/mode tells us whether privileged
        writes are plausible; actual writes still go through the app's existing
        privileged/safety path and read-back verification.
        """
        try:
            st=os.stat(path)
            mode=st.st_mode
            if mode & 0o222:
                if os.access(path,os.W_OK):
                    return "DIRECT-WRITE"
                return "PRIVILEGED-WRITE"
            return "READ-ONLY"
        except OSError:
            return "UNAVAILABLE"

    def dpm_domain_levels(self, path):
        """Parse driver-provided DPM levels without assuming an ASIC layout."""
        raw=read_text(path,"")
        levels=[]
        for line in raw.splitlines():
            line=line.strip()
            if not line:
                continue
            active=line.endswith("*")
            clean=line[:-1].strip() if active else line
            m=re.match(r"^(S|\d+)\s*:\s*(.+)$",clean,re.I)
            if not m:
                continue
            key=m.group(1)
            detail=m.group(2).strip()
            freq=None
            fm=re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([GMK]?Hz)",detail,re.I)
            if fm:
                value=float(fm.group(1)); unit=fm.group(2).lower()
                mult={"ghz":1000.0,"mhz":1.0,"khz":0.001,"hz":0.000001}.get(unit,1.0)
                freq=value*mult
            levels.append({"id":key,"detail":detail,"mhz":freq,"active":active})
        return raw,levels

    def performance_profiles(self):
        p = os.path.join(self.device, "pp_power_profile_mode")
        raw = read_text(p)
        profiles = []
        if not raw:
            return profiles
        # Parse leading profile rows, e.g. " 1 3D_FULL_SCREEN :" or " 0 BOOTUP_DEFAULT*:"
        for line in raw.splitlines():
            m = re.match(r"\s*(\d+)\s+([A-Za-z0-9_ -]+?)(\*)?\s*:", line)
            if m:
                idx = int(m.group(1))
                name = m.group(2).strip()
                active = bool(m.group(3))
                profiles.append((idx, name, active))
        return profiles

    def perf_levels(self):
        p=os.path.join(self.device,"power_dpm_force_performance_level")
        if not os.path.exists(p):
            return []
        # AMDGPU exposes a write-only choice interface rather than a separate
        # "supported values" file. Keep a conservative standard list, but also
        # preserve any current value reported by a newer/different GPU so the
        # UI never assumes one specific ASIC generation.
        levels=["auto","low","high","manual",
                "profile_standard","profile_min_sclk",
                "profile_min_mclk","profile_peak"]
        current=read_text(p).strip()
        if current and current not in levels:
            levels.insert(0,current)
        return levels

    def power_cap_limits(self):
        if not self.hwmon:
            return None
        cur = read_int(os.path.join(self.hwmon, "power1_cap"))
        lo = read_int(os.path.join(self.hwmon, "power1_cap_min"))
        hi = read_int(os.path.join(self.hwmon, "power1_cap_max"))
        if None in (cur, lo, hi):
            return None
        return (cur/1_000_000.0, lo/1_000_000.0, hi/1_000_000.0)

    def power_cap_default_w(self):
        if not self.hwmon:
            return None
        val=read_int(os.path.join(self.hwmon,"power1_cap_default"))
        return (val/1_000_000.0) if val is not None else None

    def fan_control(self):
        if not self.hwmon:
            return None
        paths = {n: os.path.join(self.hwmon, n) for n in
                 ("pwm1","pwm1_enable","pwm1_min","pwm1_max","fan1_input","fan1_max")}
        if not os.path.exists(paths["pwm1"]) or not os.path.exists(paths["pwm1_enable"]):
            return None
        return {
            "pwm": read_int(paths["pwm1"]),
            "enable": read_int(paths["pwm1_enable"]),
            "pwm_min": read_int(paths["pwm1_min"], 0),
            "pwm_max": read_int(paths["pwm1_max"], 255),
            "rpm": read_int(paths["fan1_input"]),
            "rpm_max": read_int(paths["fan1_max"]),
            "pwm_path": paths["pwm1"],
            "enable_path": paths["pwm1_enable"],
        }

    def set_fan_auto(self):
        fc = self.fan_control()
        if not fc:
            raise RuntimeError("This GPU does not expose hwmon fan control.")
        # AMDGPU hwmon follows the standard hwmon PWM convention:
        # pwm1_enable=2 is automatic fan control.
        atomic_write_sysfs(fc["enable_path"], "2")

    def set_fan_manual_percent(self, percent):
        fc = self.fan_control()
        if not fc:
            raise RuntimeError("This GPU does not expose hwmon fan control.")
        percent = max(0.0, min(100.0, float(percent)))
        lo = fc["pwm_min"] if fc["pwm_min"] is not None else 0
        hi = fc["pwm_max"] if fc["pwm_max"] is not None else 255
        pwm = int(round(lo + (hi - lo) * percent / 100.0))
        # Standard hwmon manual mode is pwm1_enable=1.
        atomic_write_sysfs(fc["enable_path"], "1")
        atomic_write_sysfs(fc["pwm_path"], str(pwm))
        return pwm

    def capability_snapshot(self):
        """Read-only inventory of AMDGPU interfaces exposed by this kernel/board."""
        dev=self.device
        hm=self.hwmon
        def cap(name,path,kind="read"):
            exists=os.path.exists(path)
            readable=os.access(path,os.R_OK) if exists else False
            writable=os.access(path,os.W_OK) if exists else False
            return {
                "name":name, "path":path, "exists":exists,
                "readable":readable, "writable":writable, "kind":kind,
            }

        rows=[
            cap("GPU utilization",os.path.join(dev,"gpu_busy_percent")),
            cap("VRAM utilization",os.path.join(dev,"mem_busy_percent")),
            cap("Performance level",os.path.join(dev,"power_dpm_force_performance_level"),"control"),
            cap("GFX DPM states",os.path.join(dev,"pp_dpm_sclk"),"control"),
            cap("Memory DPM states",os.path.join(dev,"pp_dpm_mclk"),"control"),
            cap("PCIe DPM states",os.path.join(dev,"pp_dpm_pcie"),"control"),
            cap("Power profile mode",os.path.join(dev,"pp_power_profile_mode"),"control"),
            cap("Overdrive clock/voltage",os.path.join(dev,"pp_od_clk_voltage"),"control"),
            cap("GPU metrics blob",os.path.join(dev,"gpu_metrics")),
            cap("VRAM total",os.path.join(dev,"mem_info_vram_total")),
            cap("VRAM used",os.path.join(dev,"mem_info_vram_used")),
        ]
        if hm:
            rows += [
                cap("GPU temperature",os.path.join(hm,"temp1_input")),
                cap("GPU voltage",os.path.join(hm,"in0_input")),
                cap("GPU power",os.path.join(hm,"power1_average")),
                cap("Power limit",os.path.join(hm,"power1_cap"),"control"),
                cap("Power limit minimum",os.path.join(hm,"power1_cap_min")),
                cap("Power limit maximum",os.path.join(hm,"power1_cap_max")),
                cap("Fan RPM",os.path.join(hm,"fan1_input")),
                cap("Fan PWM",os.path.join(hm,"pwm1"),"control"),
                cap("Fan control mode",os.path.join(hm,"pwm1_enable"),"control"),
                cap("GFX clock sensor",os.path.join(hm,"freq1_input")),
                cap("Memory clock sensor",os.path.join(hm,"freq2_input")),
            ]
        return rows

    def capability_report(self):
        rows=self.capability_snapshot()
        lines=[
            f"GPU: {self.short_name()}",
            f"PCI: {self.pci_slot()}",
            f"Device sysfs: {self.device}",
            f"HWMON: {self.hwmon or 'Not exposed'}",
            "",
            "READ-ONLY CAPABILITY PROBE",
            "No settings are changed by this scan.",
            "",
        ]
        for r in rows:
            if not r["exists"]:
                status="NOT EXPOSED"
            elif r["readable"]:
                status="READABLE"
            else:
                status="EXISTS / NOT READABLE"
            if r["kind"]=="control":
                status += " | write access now: " + ("YES" if r["writable"] else "NO")
            lines.append(f"{r['name']}: {status}")
            lines.append(f"  {r['path']}")
        return "\n".join(lines)

    def info(self):
        return {
            "DRM card": self.card_name,
            "GPU": self.product_name(),
            "PCI address": self.pci_slot(),
            "Kernel driver": "amdgpu",
            "Vendor ID": read_text(os.path.join(self.device, "vendor"), "—"),
            "Device ID": read_text(os.path.join(self.device, "device"), "—"),
            "Subsystem vendor": read_text(os.path.join(self.device, "subsystem_vendor"), "—"),
            "Subsystem device": read_text(os.path.join(self.device, "subsystem_device"), "—"),
            "VRAM": human_bytes(self.vram_total()),
            "Kernel": run_cmd(["uname", "-r"]) or "—",
            "Mesa": self._mesa_version(),
            "Vulkan": self._vulkan_summary(),
        }

    def _mesa_version(self):
        glx = run_cmd(["glxinfo", "-B"])
        for line in glx.splitlines():
            if "OpenGL version string" in line:
                return line.split(":",1)[-1].strip()
        return "—"

    def _vulkan_summary(self):
        s = run_cmd(["vulkaninfo", "--summary"])
        for line in s.splitlines():
            if "deviceName" in line:
                return line.split("=",1)[-1].strip()
        return "—"
