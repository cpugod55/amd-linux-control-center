#!/usr/bin/env python3
import argparse
import os
import signal
import time

def read_int(path):
    with open(path,"r",encoding="ascii") as f:
        return int(f.read().strip())

def write(path, value):
    with open(path,"w",encoding="ascii") as f:
        f.write(str(value))

def parent_alive(pid):
    try:
        os.kill(pid,0)
        return True
    except OSError:
        return False

def interpolate(points, temp):
    if temp <= points[0][0]:
        return points[0][1]
    if temp >= points[-1][0]:
        return points[-1][1]
    for (t1,p1),(t2,p2) in zip(points,points[1:]):
        if t1 <= temp <= t2:
            frac=(temp-t1)/(t2-t1)
            return p1+(p2-p1)*frac
    return points[-1][1]

ap=argparse.ArgumentParser()
ap.add_argument("--parent-pid",type=int,required=True)
ap.add_argument("--temp",required=True)
ap.add_argument("--pwm",required=True)
ap.add_argument("--enable",required=True)
ap.add_argument("--pwm-min",type=int,required=True)
ap.add_argument("--pwm-max",type=int,required=True)
ap.add_argument("--stop-file",required=True)
ap.add_argument("--points",required=True)
args=ap.parse_args()

# Hard safety: only sysfs paths are accepted.
for p in (args.temp,args.pwm,args.enable):
    rp=os.path.realpath(p)
    if not rp.startswith("/sys/"):
        raise SystemExit("Refusing non-sysfs path")

points=[]
for item in args.points.split(","):
    t,p=item.split(":",1)
    points.append((float(t),float(p)))
points.sort()
if len(points)<2:
    raise SystemExit("Need at least two fan-curve points")

# Ensure fan percentage never decreases at higher temperature.
last=0.0
safe=[]
for t,p in points:
    p=max(last,max(0.0,min(100.0,p)))
    safe.append((t,p))
    last=p
points=safe

try:
    write(args.enable,1)
    last_pwm=None
    while parent_alive(args.parent_pid) and not os.path.exists(args.stop_file):
        temp_c=read_int(args.temp)/1000.0
        pct=interpolate(points,temp_c)
        pwm=round(args.pwm_min+(args.pwm_max-args.pwm_min)*pct/100.0)
        pwm=max(args.pwm_min,min(args.pwm_max,int(pwm)))
        if pwm != last_pwm:
            write(args.pwm,pwm)
            last_pwm=pwm
        time.sleep(1.0)
finally:
    # Always hand the fan back to AMD's automatic controller.
    try:
        write(args.enable,2)
    except Exception:
        pass
