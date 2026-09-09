#!/usr/bin/env python3
import argparse, os, re, time

ALLOWED_BASENAMES={"power_dpm_force_performance_level","pp_power_profile_mode","power1_cap",
                   "pp_dpm_sclk","pp_dpm_mclk","pp_dpm_socclk","pp_dpm_fclk","pp_dpm_pcie",
                   "pwm1_enable","pwm1"}
PERF_VALUES={"auto","low","high","manual","profile_standard","profile_min_sclk","profile_min_mclk","profile_peak"}

def real_sysfs(p):
    r=os.path.realpath(p)
    if not r.startswith("/sys/"):
        raise ValueError("Refusing path outside /sys")
    # Restrict this privileged helper to AMDGPU DRM device trees and their hwmon children.
    # This prevents a permitted basename from being used against an unrelated sysfs node.
    # sysfs /sys/class/drm/cardN/device is normally a symlink.  realpath()
    # resolves it to the underlying PCI function, e.g.
    # /sys/devices/pci.../0000:03:00.0/pp_dpm_sclk.  Validate that resolved
    # PCI function is actually bound to the amdgpu driver rather than requiring
    # the symlink spelling to remain in the path.
    dev=r
    marker="/hwmon/"
    if marker in dev:
        dev=dev.split(marker,1)[0]
    else:
        dev=os.path.dirname(dev)

    driver_link=os.path.join(dev,"driver")
    try:
        driver=os.path.basename(os.path.realpath(driver_link))
    except Exception:
        driver=""

    if driver != "amdgpu":
        raise ValueError("Refusing sysfs path not owned by the amdgpu driver")
    return r

def validate_setting(path,value):
    real=real_sysfs(path); base=os.path.basename(real)
    if base not in ALLOWED_BASENAMES: raise ValueError(f"Unsupported profile setting: {base}")
    if base=="power_dpm_force_performance_level" and value not in PERF_VALUES:
        raise ValueError("Invalid performance-level value")
    if base in {"pp_power_profile_mode","power1_cap","pwm1_enable","pwm1"} and not re.fullmatch(r"\d+",value):
        raise ValueError(f"Invalid value for {base}")
    if base=="pwm1_enable" and int(value) not in (0,1,2):
        raise ValueError("Invalid pwm1_enable mode")
    if base=="pwm1" and not (0 <= int(value) <= 65535):
        raise ValueError("Invalid pwm1 value")
    if base.startswith("pp_dpm_") and not re.fullmatch(r"\d+",value):
        raise ValueError(f"Invalid DPM state for {base}")
    return real,value

def write(path,value):
    with open(path,"w",encoding="ascii") as f: f.write(str(value))

def read_int(path):
    with open(path,"r",encoding="ascii") as f: return int(f.read().strip())

def parse_dpm_levels(path):
    levels=[]
    with open(path,"r",encoding="ascii") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            active=line.endswith("*")
            clean=line[:-1].strip() if active else line
            m=re.match(r"^(\d+)\s*:\s*(.+)$",clean)
            if not m: continue
            idx=m.group(1); detail=m.group(2)
            fm=re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([GMK]?Hz)",detail,re.I)
            mhz=None
            if fm:
                val=float(fm.group(1)); unit=fm.group(2).lower()
                mhz=val*{"ghz":1000.0,"mhz":1.0,"khz":0.001,"hz":0.000001}.get(unit,1.0)
            levels.append((idx,detail,mhz,active))
    return levels

def resolve_dpm_target(path,target_mhz):
    levels=parse_dpm_levels(path)
    candidates=[x for x in levels if x[2] is not None]
    if not candidates:
        raise ValueError(f"No frequency states exposed by {os.path.basename(path)} after manual mode")
    exact=[x for x in candidates if abs(x[2]-target_mhz)<0.51]
    chosen=exact[0] if exact else min(candidates,key=lambda x:abs(x[2]-target_mhz))
    return chosen

def alive(pid):
    try: os.kill(pid,0); return True
    except OSError: return False

def interp(points,temp):
    if temp<=points[0][0]: return points[0][1]
    if temp>=points[-1][0]: return points[-1][1]
    for (t1,p1),(t2,p2) in zip(points,points[1:]):
        if t1<=temp<=t2:
            return p1+(p2-p1)*(temp-t1)/(t2-t1)
    return points[-1][1]

ap=argparse.ArgumentParser()
ap.add_argument("--set",dest="settings",action="append",default=[])
ap.add_argument("--dpm-target",dest="dpm_targets",action="append",default=[])
ap.add_argument("--dpm-mode",choices=("auto","manual"))
ap.add_argument("--perf-path")
ap.add_argument("--curve",action="store_true")
ap.add_argument("--parent-pid",type=int)
ap.add_argument("--temp")
ap.add_argument("--pwm")
ap.add_argument("--enable")
ap.add_argument("--pwm-min",type=int)
ap.add_argument("--pwm-max",type=int)
ap.add_argument("--stop-file")
ap.add_argument("--points")
a=ap.parse_args()

ops=[]
dpm_targets=[]
for item in a.dpm_targets:
    if "=" not in item: raise SystemExit("Malformed DPM target")
    path,val=item.rsplit("=",1)
    try:
        path=real_sysfs(path)
        if os.path.basename(path) not in {"pp_dpm_sclk","pp_dpm_mclk","pp_dpm_socclk","pp_dpm_fclk","pp_dpm_pcie"}:
            raise ValueError("Unsupported DPM target interface")
        target=float(val)
        if target < 0 or target > 100000:
            raise ValueError("Invalid DPM target frequency")
        dpm_targets.append((path,target))
    except Exception as e:
        raise SystemExit(str(e))

ops=[]
for item in a.settings:
    if "=" not in item: raise SystemExit("Malformed setting")
    path,val=item.rsplit("=",1)
    try: ops.append(validate_setting(path,val))
    except Exception as e: raise SystemExit(str(e))

# Validate curve inputs before making any writes.
points=None
if a.curve:
    required=[a.parent_pid,a.temp,a.pwm,a.enable,a.pwm_min,a.pwm_max,a.stop_file,a.points]
    if any(x is None for x in required): raise SystemExit("Incomplete fan curve arguments")
    try:
        a.temp=real_sysfs(a.temp); a.pwm=real_sysfs(a.pwm); a.enable=real_sysfs(a.enable)
        if os.path.basename(a.pwm)!="pwm1" or os.path.basename(a.enable)!="pwm1_enable":
            raise ValueError("Unsupported fan interface")
        points=[]
        for item in a.points.split(","):
            t,p=item.split(":",1); points.append((float(t),float(p)))
        points.sort()
        if len(points)<2: raise ValueError("Need at least two curve points")
        last=0; safe=[]
        for t,p in points:
            p=max(last,max(0,min(100,p))); safe.append((t,p)); last=p
        points=safe
    except Exception as e: raise SystemExit(str(e))

for path,val in ops:
    try: write(path,val)
    except Exception as e: raise SystemExit(f"Could not write {os.path.basename(path)}: {e}")

# Apply the DPM mode inside this same privileged transaction.  For manual
# profiles this must happen before resolving targets because AMDGPU can change
# the pp_dpm_* tables when manual mode is entered.
if a.dpm_mode:
    if not a.perf_path:
        raise SystemExit("Missing AMDGPU performance-level path")
    perf_path=real_sysfs(a.perf_path)
    if os.path.basename(perf_path)!="power_dpm_force_performance_level":
        raise SystemExit("Invalid AMDGPU performance-level path")
    try:
        write(perf_path,a.dpm_mode)
        time.sleep(0.12)
        with open(perf_path,"r",encoding="ascii") as f:
            actual=f.read().strip()
        if actual != a.dpm_mode:
            raise RuntimeError(f"AMDGPU reports {actual!r} after requesting {a.dpm_mode!r}")
    except Exception as e:
        raise SystemExit(f"Could not set DPM mode: {e}")

# Resolve DPM targets only after performance mode/settings above have been written,
# because AMDGPU may expose a different state table in manual mode.
for path,target in dpm_targets:
    try:
        idx,detail,mhz,active=resolve_dpm_target(path,target)
        write(path,idx)
    except Exception as e:
        raise SystemExit(f"Could not apply DPM target for {os.path.basename(path)}: {e}")

if a.curve:
    try:
        write(a.enable,1)
        last_pwm=None
        while alive(a.parent_pid) and not os.path.exists(a.stop_file):
            temp=read_int(a.temp)/1000.0
            pct=interp(points,temp)
            pwm=round(a.pwm_min+(a.pwm_max-a.pwm_min)*pct/100.0)
            pwm=max(a.pwm_min,min(a.pwm_max,int(pwm)))
            if pwm!=last_pwm:
                write(a.pwm,pwm); last_pwm=pwm
            time.sleep(1)
    finally:
        try: write(a.enable,2)
        except Exception: pass
