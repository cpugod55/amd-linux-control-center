"""Pure telemetry and session-processing helpers for AMD Linux Control Center.

This module intentionally contains no Tk, process control, launch orchestration, or
filesystem policy.  Callers remain responsible for choosing telemetry files and
for presenting provider state to the UI.
"""


def percentile(values, pct):
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    pos = (len(vals) - 1) * float(pct)
    lo = int(pos)
    hi = min(len(vals) - 1, lo + 1)
    frac = pos - lo
    return vals[lo] * (1.0 - frac) + vals[hi] * frac


def parse_mangohud_csv_text(text, max_samples=240):
    """Parse one MangoHud CSV payload without touching the filesystem.

    Returns None when no valid FPS sample can be recovered.  The returned dict
    preserves ALCC's existing provider-vs-derived metric semantics.
    """
    rows = [r for r in str(text or "").splitlines() if r.strip()]
    if len(rows) < 2:
        return None

    fps = ft = low = gpu_ft = cpu_ft = None
    sampled_fps = []
    header_idx = None
    for idx, line in enumerate(rows[:-1]):
        cols = [x.strip().lower() for x in line.split(",")]
        if any(c == "fps" or "frametime" in c or "frame time" in c for c in cols):
            header_idx = idx

    if header_idx is not None and header_idx + 1 < len(rows):
        header = [x.strip().lower() for x in rows[header_idx].split(",")]
        data_rows = [[x.strip() for x in line.split(",")] for line in rows[header_idx + 1:]]

        def col_index(exact=(), contains=()):
            for name in exact:
                for idx, h in enumerate(header):
                    if h == name:
                        return idx
            for name in contains:
                for idx, h in enumerate(header):
                    if name in h:
                        return idx
            return None

        def last_value(idx):
            if idx is None:
                return None
            for data in reversed(data_rows):
                if idx < len(data):
                    try:
                        return float(data[idx])
                    except Exception:
                        pass
            return None

        fps_idx = col_index(("fps",), (" fps",))
        ft_idx = col_index(("frametime", "frame time", "frame_time"), ())
        low_idx = col_index(
            ("1% low", "1%low", "fps_1%", "fps_1_percent", "one_percent_low"),
            ("1% low", "1_percent_low", "one_percent_low"),
        )
        gpu_idx = col_index(
            ("gpu frametime", "gpu_frame_time", "gpu frame time", "gpu_frame"),
            ("gpu frametime", "gpu frame time", "gpu_frame_time"),
        )
        cpu_idx = col_index(
            ("cpu frametime", "cpu_frame_time", "cpu frame time", "cpu_frame"),
            ("cpu frametime", "cpu frame time", "cpu_frame_time"),
        )

        fps = last_value(fps_idx)
        ft = last_value(ft_idx)
        low = last_value(low_idx)
        gpu_ft = last_value(gpu_idx)
        cpu_ft = last_value(cpu_idx)

        if fps_idx is not None:
            # ALCC logs at 250 ms; 240 samples are approximately 60 seconds.
            scan = max(max_samples + 20, max_samples)
            for data in data_rows[-scan:]:
                if fps_idx < len(data):
                    try:
                        value = float(data[fps_idx])
                        if 1.0 <= value <= 2000.0:
                            sampled_fps.append(value)
                    except Exception:
                        pass
            sampled_fps = sampled_fps[-max_samples:]

    if fps is None:
        # Legacy format: first numeric column is FPS.
        numeric = []
        for line in rows:
            vals = [x.strip() for x in line.split(",")]
            try:
                value = float(vals[0])
            except Exception:
                continue
            if 1.0 <= value <= 2000.0:
                numeric.append(value)
        if numeric:
            fps = numeric[-1]
            sampled_fps = numeric[-max_samples:]

    if fps is None or fps <= 0:
        return None

    result = {
        "fps": fps,
        "low": None,
        "low_kind": None,
        "frametime": None,
        "frametime_kind": None,
        "gpu_frame": None,
        "cpu_frame": None,
        "samples": list(sampled_fps[-max_samples:]),
        "avg_fps": None,
        "stability_pct": None,
    }

    if ft is not None and 0 < ft <= 1000:
        result["frametime"] = ft
        result["frametime_kind"] = "provider"
    else:
        result["frametime"] = 1000.0 / fps
        result["frametime_kind"] = "derived"

    if sampled_fps:
        result["avg_fps"] = sum(sampled_fps) / len(sampled_fps)

    if low is not None and low > 0:
        result["low"] = low
        result["low_kind"] = "provider"
    elif len(sampled_fps) >= 20:
        result["low"] = percentile(sampled_fps, 0.01)
        result["low_kind"] = "sampled_p1_60s"

    if result["low"] is not None and result["avg_fps"]:
        result["stability_pct"] = max(
            0.0, min(100.0, 100.0 * float(result["low"]) / float(result["avg_fps"]))
        )

    if gpu_ft is not None and 0 < gpu_ft <= 1000:
        result["gpu_frame"] = gpu_ft
    if cpu_ft is not None and 0 < cpu_ft <= 1000:
        result["cpu_frame"] = cpu_ft
    return result


def detect_likely_capped_menu_samples(paired):
    """Conservatively mark stable low-workload FPS plateaus as menu/background samples.

    The detector first finds obvious low-workload plateaus, then learns the FPS,
    board-power, and GPU-clock envelope of those confirmed samples.  That learned
    envelope lets it recover sparse unfocused/background samples elsewhere in the
    same session even when reported GPU utilization remains moderately high.
    """
    rows = [r for r in (paired or []) if isinstance(r, dict)]
    loads = []
    for row in rows:
        try:
            loads.append(float(row.get("gpu_load")))
        except Exception:
            pass
    if len(loads) < 8:
        return set(), None

    ordered = sorted(loads)
    q75 = ordered[int(round((len(ordered) - 1) * 0.75))]
    if q75 < 45.0:
        return set(), q75

    low_workload = []
    for row in rows:
        try:
            fps = float(row.get("fps"))
            load = float(row.get("gpu_load"))
        except Exception:
            low_workload.append(False)
            continue
        workload_drop = load <= min(80.0, q75 - 15.0)
        low_workload.append(bool(fps > 0 and workload_drop))

    marked = set()
    run_start = None
    for i, flag in enumerate(low_workload + [False]):
        if flag and run_start is None:
            run_start = i
        elif not flag and run_start is not None:
            if i - run_start >= 4:
                run = []
                for row in rows[run_start:i]:
                    try:
                        run.append(float(row.get("fps")))
                    except Exception:
                        pass
                center = percentile(run, 0.50)
                p10 = percentile(run, 0.10)
                p90 = percentile(run, 0.90)
                if center and p10 is not None and p90 is not None and (p90 - p10) <= max(2.0, center * 0.04):
                    marked.update(range(run_start, i))
            run_start = None

    fps_values = []
    powers = []
    clocks = []
    for row in rows:
        try:
            fps_values.append(float(row.get("fps")))
        except Exception:
            pass
        try:
            powers.append(float(row.get("power_w")))
        except Exception:
            pass
        try:
            clocks.append(float(row.get("gpu_clock_mhz")))
        except Exception:
            pass
    normal_fps = percentile(fps_values, 0.50)
    power_ref = percentile(powers, 0.75)
    clock_ref = percentile(clocks, 0.75)

    # Common game behaviour: throttle to about 30 FPS when unfocused.  Seed the
    # learned background state only when FPS is near that plateau and the GPU has
    # strong idle evidence.  High-power/high-clock 30 FPS remains gameplay.
    if normal_fps is not None and normal_fps >= 50.0 and q75 >= 70.0:
        for i, row in enumerate(rows):
            try:
                fps = float(row.get("fps"))
                load = float(row.get("gpu_load"))
            except Exception:
                continue
            if not (27.0 <= fps <= 33.5):
                continue
            if load > min(60.0, q75 - 30.0):
                continue
            corroborated = False
            try:
                power = float(row.get("power_w"))
                if power_ref and power_ref > 0 and power <= power_ref * 0.60:
                    corroborated = True
            except Exception:
                pass
            try:
                clock = float(row.get("gpu_clock_mhz"))
                if clock_ref and clock_ref > 0 and clock <= clock_ref * 0.70:
                    corroborated = True
            except Exception:
                pass
            if not corroborated and load > min(35.0, q75 - 50.0):
                continue
            marked.add(i)

    # Learn the operating envelope of positively identified background samples.
    # This is intentionally based on FPS + power + clock, not utilization alone:
    # some games report 65-80% GPU utilization while unfocused even though board
    # power and clocks have collapsed.  The learned envelope is session-local and
    # therefore does not hard-code a universal 30 FPS background cap.
    if marked and normal_fps is not None:
        seed_fps = []
        seed_power = []
        seed_clock = []
        for i in sorted(marked):
            row = rows[i]
            try:
                seed_fps.append(float(row.get("fps")))
            except Exception:
                pass
            try:
                seed_power.append(float(row.get("power_w")))
            except Exception:
                pass
            try:
                seed_clock.append(float(row.get("gpu_clock_mhz")))
            except Exception:
                pass

        bg_fps = percentile(seed_fps, 0.50)
        bg_power_hi = percentile(seed_power, 0.90)
        bg_clock_hi = percentile(seed_clock, 0.90)

        if bg_fps and bg_fps > 0 and normal_fps >= bg_fps * 1.45:
            fps_lo = max(1.0, bg_fps * 0.72)
            fps_hi = min(normal_fps * 0.80, bg_fps * 1.22)

            # Allow entry/exit power and clocks to rise somewhat above the
            # steady background plateau, but still require a major collapse
            # relative to normal gameplay.  Both signals must corroborate when
            # both are available, preventing real loaded-GPU lows from vanishing.
            power_limit = None
            if bg_power_hi is not None and power_ref and power_ref > 0:
                power_limit = min(bg_power_hi * 1.80, power_ref * 0.55)
            clock_limit = None
            if bg_clock_hi is not None and clock_ref and clock_ref > 0:
                clock_limit = min(bg_clock_hi * 1.65, clock_ref * 0.72)

            learned = set(marked)
            for i, row in enumerate(rows):
                if i in learned:
                    continue
                try:
                    fps = float(row.get("fps"))
                except Exception:
                    continue
                if not (fps_lo <= fps <= fps_hi):
                    continue

                power_ok = None
                clock_ok = None
                if power_limit is not None:
                    try:
                        power_ok = float(row.get("power_w")) <= power_limit
                    except Exception:
                        power_ok = None
                if clock_limit is not None:
                    try:
                        clock_ok = float(row.get("gpu_clock_mhz")) <= clock_limit
                    except Exception:
                        clock_ok = None

                # With both power and clock available, require both.  With only
                # one signal available, require it plus a substantial load drop.
                if power_ok is not None and clock_ok is not None:
                    if not (power_ok and clock_ok):
                        continue
                elif power_ok is True or clock_ok is True:
                    try:
                        load = float(row.get("gpu_load"))
                    except Exception:
                        continue
                    if load > min(55.0, q75 - 30.0):
                        continue
                else:
                    continue
                learned.add(i)
            marked = learned

    return marked, q75

def session_gameplay_fps_metrics(cur):
    paired = list(cur.get("paired_perf", []) or [])
    marked, active_load = detect_likely_capped_menu_samples(paired)
    raw = [float(r["fps"]) for r in paired if isinstance(r, dict) and r.get("fps") is not None]
    gameplay = [
        float(r["fps"])
        for i, r in enumerate(paired)
        if i not in marked and isinstance(r, dict) and r.get("fps") is not None
    ]
    if not raw:
        raw = [float(v) for v in cur.get("fps", []) if v is not None]
    if not gameplay:
        gameplay = list(raw)

    menu_seconds = 0.0
    if marked:
        times = []
        for row in paired:
            try:
                times.append(float(row.get("t")))
            except Exception:
                pass
        if len(times) >= 2:
            diffs = [b - a for a, b in zip(times, times[1:]) if 0 < a and 0 < b - a < 5]
            interval = (sum(diffs) / len(diffs)) if diffs else 1.0
        else:
            interval = 1.0
        menu_seconds = len(marked) * max(0.25, min(2.5, interval))

    return {
        "raw_avg": (sum(raw) / len(raw)) if raw else None,
        "raw_p1": percentile(raw, 0.01),
        "gameplay_avg": (sum(gameplay) / len(gameplay)) if gameplay else None,
        "gameplay_p1": percentile(gameplay, 0.01),
        "raw_samples": len(raw),
        "gameplay_samples": len(gameplay),
        "likely_menu_samples": len(marked),
        "likely_menu_seconds": menu_seconds,
        "active_load_reference": active_load,
    }
