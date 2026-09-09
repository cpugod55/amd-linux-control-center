"""Pure saved-session interpretation and Performance Advisor helpers.

No Tk, process control, filesystem access, or GPU writes live here.
"""

import math
import time

from alcc_telemetry import detect_likely_capped_menu_samples, percentile


def session_num(v):
    try:
        v=float(v)
        return v if math.isfinite(v) else None
    except Exception:
        return None


def canonical_session_p1(rec):
    if not isinstance(rec,dict): return None
    for key in ("gameplay_p1_fps","raw_sampled_p1_fps","live_reported_p1_fps","p1_fps"):
        value=session_num(rec.get(key))
        if value is not None: return value
    return None


def game_session_quality(rec):
    if not isinstance(rec,dict): return "Incomplete"
    dur=session_num(rec.get("duration_seconds")) or 0.0
    fps=session_num(rec.get("avg_fps")); avg_load=session_num(rec.get("avg_gpu_load_pct")); max_load=session_num(rec.get("max_gpu_load_pct"))
    active_gpu=(avg_load is not None and avg_load>=30.0) or (max_load is not None and max_load>=60.0)
    try: paired=int(rec.get("paired_perf_samples") or rec.get("raw_paired_telemetry_samples") or 0)
    except Exception: paired=0
    valid_frame_stream=paired>=30
    if dur>=60.0 and fps is not None and fps>1.0 and (valid_frame_stream or active_gpu): return "Gameplay"
    if fps is None and active_gpu: return "Detected / FPS telemetry unavailable"
    if fps is None and (max_load is None or max_load<60.0): return "Idle / No FPS"
    return "Incomplete"


def game_session_setup_key(rec):
    if not isinstance(rec,dict): return ("","","","")
    return (str(rec.get("game") or ""),str(rec.get("gpu_profile") or ""),str(rec.get("graphics_preset") or ""),str(rec.get("scaling") or ""))


def thermal_delta_context(rec):
    delta=session_num(rec.get("max_temp_delta_c")) if isinstance(rec,dict) else None
    if delta is None: return "ΔT context unavailable"
    if delta<20.0: return "ΔT compact"
    if delta<30.0: return "ΔT moderate"
    return "ΔT large — inspect cooling/contact if persistent"


def advisor_pair(average,peak,suffix):
    def value(v): return "unavailable" if v is None else f"{v:.1f}{suffix}"
    return f"{value(average)} average / {value(peak)} peak"


def format_session_duration(seconds):
    try: dur=max(0,int(round(float(seconds))))
    except Exception: return "—"
    if dur>=3600: return f"{dur//3600}h {(dur%3600)//60}m {dur%60}s"
    if dur>=60: return f"{dur//60}m {dur%60}s"
    return f"{dur}s"


def session_event_clock(cur,sample_t,first_sample_t=None):
    try:
        sample_t=float(sample_t)
        base_t=float(first_sample_t if first_sample_t is not None else sample_t)
        offset=max(0.0,sample_t-base_t)
    except Exception:
        offset=0.0
    try:
        wall=float(cur.get("started_at") or time.time())+offset
        clock=time.strftime("%H:%M:%S",time.localtime(wall))
    except Exception:
        clock="—"
    return offset,clock

def session_frame_dip_metrics(cur):
    """Analyze sustained gameplay FPS dips using paired FPS/GPU telemetry.

    This is intentionally descriptive, not a claim of root cause. Menu/capped
    samples identified by the v0.78.1 filter are removed first.
    """
    paired=list(cur.get("paired_perf",[]) or [])
    menu_marked,_=detect_likely_capped_menu_samples(paired)
    rows=[]
    for i,r in enumerate(paired):
        if i in menu_marked or not isinstance(r,dict):
            continue
        try:
            fps=float(r.get("fps")); load=float(r.get("gpu_load"))
        except Exception:
            continue
        # Preserve zero/near-zero samples: these are valuable full-stall
        # evidence, not invalid FPS telemetry.
        if not (0 <= fps < 2000):
            continue
        rows.append({
            "t":r.get("t"),
            "fps":fps,
            "gpu_load":load,
            "power_w":session_num(r.get("power_w")),
            "gpu_clock_mhz":session_num(r.get("gpu_clock_mhz")),
        })

    if len(rows)<12:
        return {
            "dip_analysis_status":"insufficient paired gameplay data",
            "dip_analysis_input_samples":len(rows),
            "frame_dip_samples":0,"frame_dip_events":0,"frame_dip_seconds":0.0,
            "frame_dip_fraction_pct":None,"worst_fps":None,"worst_window_fps":None,
            "gpu_bound_dip_events":0,"gpu_headroom_dip_events":0,"mixed_dip_events":0,
            "transition_dip_events":0,
            "frame_dip_rating":"Insufficient paired gameplay data",
            "gameplay_median_fps":None,"frame_dip_threshold_fps":None,
            "worst_dip_kind":None,"worst_dip_avg_gpu_load":None,
            "worst_dip_avg_power_w":None,"worst_dip_avg_gpu_clock_mhz":None,
            "isolated_hitch_candidates":0,"isolated_hitch_gpu_saturated":0,
            "isolated_hitch_gpu_headroom":0,"isolated_hitch_transition":0,"isolated_hitch_mixed":0,
            "worst_isolated_hitch_fps":None,"worst_isolated_hitch_kind":None,
            "worst_isolated_hitch_gpu_load":None,"worst_isolated_hitch_power_w":None,
            "worst_isolated_hitch_gpu_clock_mhz":None,
        }

    fps_values=[r["fps"] for r in rows]
    load_values=[r["gpu_load"] for r in rows]
    first_sample_t=None
    for r in rows:
        try:
            first_sample_t=float(r.get("t")); break
        except Exception:
            pass
    # Median resists menus/spikes and represents the normal session pace better
    # than the maximum FPS.
    sorted_fps=sorted(fps_values)
    median_fps=percentile(sorted_fps,0.50)
    active_load=percentile(load_values,0.75)
    if median_fps is None or median_fps<=0:
        return {
            "dip_analysis_status":"invalid gameplay median",
            "dip_analysis_input_samples":len(rows),
            "frame_dip_rating":"Insufficient paired gameplay data",
            "gameplay_median_fps":None,"frame_dip_threshold_fps":None,
            "frame_dip_samples":0,"frame_dip_events":0,"frame_dip_seconds":0.0,
            "frame_dip_fraction_pct":None,"worst_fps":None,"worst_window_fps":None,
            "gpu_bound_dip_events":0,"gpu_headroom_dip_events":0,"mixed_dip_events":0,
            "transition_dip_events":0,
            "worst_dip_kind":None,"worst_dip_avg_gpu_load":None,
            "worst_dip_avg_power_w":None,"worst_dip_avg_gpu_clock_mhz":None,
            "isolated_hitch_candidates":0,"isolated_hitch_gpu_saturated":0,
            "isolated_hitch_gpu_headroom":0,"isolated_hitch_transition":0,"isolated_hitch_mixed":0,
            "worst_isolated_hitch_fps":None,"worst_isolated_hitch_kind":None,
            "worst_isolated_hitch_gpu_load":None,"worst_isolated_hitch_power_w":None,
            "worst_isolated_hitch_gpu_clock_mhz":None,
        }

    # A meaningful dip is <=70% of the gameplay median. Require at least two
    # consecutive paired samples so single telemetry glitches do not count.
    dip_threshold=max(1.0,median_fps*0.70)
    flags=[r["fps"]<=dip_threshold for r in rows]

    # Separate isolated single-sample hitch candidates from sustained dips.
    # A candidate is one low sample with non-low neighbors (when present).
    isolated_indexes=[]
    for i,flag in enumerate(flags):
        if not flag:
            continue
        prev_low=(i>0 and flags[i-1])
        next_low=(i+1<len(flags) and flags[i+1])
        if not prev_low and not next_low:
            isolated_indexes.append(i)

    # Estimate paired-sample interval for event duration.
    times=[]
    for r in rows:
        try: times.append(float(r.get("t")))
        except Exception: pass
    diffs=[b-a for a,b in zip(times,times[1:]) if 0 < b-a < 5]
    interval=(sum(diffs)/len(diffs)) if diffs else 1.0
    interval=max(0.25,min(2.5,interval))

    events=[]
    start=None
    for i,flag in enumerate(flags+[False]):
        if flag and start is None:
            start=i
        elif not flag and start is not None:
            if i-start>=2:
                events.append((start,i))
            start=None

    gpu_bound=headroom=mixed=transitions=0
    dip_sample_count=0
    event_rows=[]
    for a,b in events:
        chunk=rows[a:b]
        dip_sample_count += len(chunk)
        avg_load=sum(r["gpu_load"] for r in chunk)/len(chunk)
        avg_fps=sum(r["fps"] for r in chunk)/len(chunk)
        powers=[r["power_w"] for r in chunk if r["power_w"] is not None]
        clocks=[r["gpu_clock_mhz"] for r in chunk if r["gpu_clock_mhz"] is not None]
        avg_power=(sum(powers)/len(powers)) if powers else None
        avg_clock=(sum(clocks)/len(clocks)) if clocks else None
        # Transition/loading heuristic: a severe FPS dip accompanied by a
        # near-idle GPU state is qualitatively different from a normal
        # CPU/engine-headroom dip. Require multiple independent low-workload
        # signals so ordinary CPU-limited gameplay is not mislabeled.
        transition_signals=0
        if avg_load <= 25.0:
            transition_signals += 1
        if avg_power is not None and avg_power <= 70.0:
            transition_signals += 1
        if avg_clock is not None and avg_clock <= 700.0:
            transition_signals += 1
        if transition_signals >= 2:
            kind="Likely transition/loading"
        elif avg_load>=95.0:
            kind="GPU-saturated"
            gpu_bound+=1
        elif active_load is not None and avg_load<=min(80.0,active_load-15.0):
            kind="GPU-headroom"
            headroom+=1
        else:
            kind="Mixed/uncertain"
            mixed+=1
        if kind=="Likely transition/loading":
            transitions+=1
        offset,event_clock=session_event_clock(cur,chunk[0].get("t"),first_sample_t)
        event_rows.append({
            "kind":kind,
            "avg_fps":avg_fps,
            "min_fps":min(r["fps"] for r in chunk),
            "avg_gpu_load":avg_load,
            "avg_power_w":avg_power,
            "avg_gpu_clock_mhz":avg_clock,
            "seconds":len(chunk)*interval,
            "offset_seconds":offset,
            "clock":event_clock,
        })

    # Lowest short rolling interval (~5 paired samples).
    window=min(5,len(fps_values))
    worst_window=None
    if window>=2:
        worst_window=min(
            sum(fps_values[i:i+window])/window
            for i in range(0,len(fps_values)-window+1)
        )

    frac=(100.0*dip_sample_count/len(rows)) if rows else None
    gameplay_p1=percentile(fps_values,0.01)
    ratio=(gameplay_p1/median_fps) if gameplay_p1 is not None and median_fps else None

    isolated_gpu=isolated_headroom=isolated_transition=isolated_mixed=0
    isolated_rows=[]
    for i in isolated_indexes:
        r=rows[i]
        load=r["gpu_load"]
        power=r.get("power_w")
        clock=r.get("gpu_clock_mhz")
        transition_signals=0
        if load <= 25.0:
            transition_signals += 1
        if power is not None and power <= 70.0:
            transition_signals += 1
        if clock is not None and clock <= 700.0:
            transition_signals += 1
        if transition_signals >= 2:
            kind="Likely transition/loading"
            isolated_transition+=1
        elif load>=95.0:
            kind="GPU-saturated"
            isolated_gpu+=1
        elif active_load is not None and load<=min(80.0,active_load-15.0):
            kind="GPU-headroom"
            isolated_headroom+=1
        else:
            kind="Mixed/uncertain"
            isolated_mixed+=1
        offset,event_clock=session_event_clock(cur,r.get("t"),first_sample_t)
        isolated_rows.append({
            "kind":kind,
            "fps":r["fps"],
            "gpu_load":load,
            "power_w":power,
            "gpu_clock_mhz":clock,
            "offset_seconds":offset,
            "clock":event_clock,
        })

    # Transition/loading events stay recorded but do not degrade the
    # gameplay consistency severity rating.
    gameplay_event_rows=[e for e in event_rows if e.get("kind")!="Likely transition/loading"]
    gameplay_event_count=len(gameplay_event_rows)
    gameplay_dip_seconds=sum(float(e.get("seconds") or 0) for e in gameplay_event_rows)
    total_seconds=max(interval*len(rows),0.001)
    gameplay_dip_fraction=100.0*gameplay_dip_seconds/total_seconds

    if gameplay_event_count==0:
        if transitions>0:
            rating="Good — transition/loading events only"
        elif len(isolated_indexes)==0:
            rating="Smooth"
        elif len(isolated_indexes)<=3:
            rating="Smooth / isolated hitch candidate(s)"
        else:
            rating="Good — isolated hitch candidates"
    elif gameplay_dip_fraction<1.0 and gameplay_event_count<=3:
        rating="Good — rare brief dips"
    elif gameplay_dip_fraction<3.0:
        rating="Moderate dips"
    else:
        rating="Significant dips"

    full_stall_rows=[r for r in isolated_rows if r.get("fps") is not None and float(r.get("fps"))<=1.0]
    for e in event_rows:
        if e.get("min_fps") is not None and float(e.get("min_fps"))<=1.0:
            full_stall_rows.append({
                "kind":e.get("kind"),
                "fps":e.get("min_fps"),
                "gpu_load":e.get("avg_gpu_load"),
                "power_w":e.get("avg_power_w"),
                "gpu_clock_mhz":e.get("avg_gpu_clock_mhz"),
                "offset_seconds":e.get("offset_seconds"),
                "clock":e.get("clock"),
            })

    worst_event=None
    if event_rows:
        worst_event=min(event_rows,key=lambda e:e["min_fps"])
    worst_isolated=None
    if isolated_rows:
        worst_isolated=min(isolated_rows,key=lambda e:e["fps"])

    return {
        "dip_analysis_status":"ok",
        "dip_analysis_input_samples":len(rows),
        "frame_dip_threshold_fps":dip_threshold,
        "gameplay_median_fps":median_fps,
        "frame_dip_samples":dip_sample_count,
        "frame_dip_events":len(events),
        "frame_dip_seconds":dip_sample_count*interval,
        "frame_dip_fraction_pct":frac,
        "worst_fps":min(fps_values) if fps_values else None,
        "worst_window_fps":worst_window,
        "gpu_bound_dip_events":gpu_bound,
        "gpu_headroom_dip_events":headroom,
        "mixed_dip_events":mixed,
        "transition_dip_events":transitions,
        "frame_dip_rating":rating,
        "gameplay_dip_events":gameplay_event_count,
        "gameplay_dip_fraction_pct":gameplay_dip_fraction,
        "dip_event_log":event_rows[:50],
        "isolated_hitch_log":isolated_rows[:50],
        "full_stall_candidates":len(full_stall_rows),
        "full_stall_log":full_stall_rows[:20],
        "worst_dip_kind":worst_event.get("kind") if worst_event else None,
        "worst_dip_avg_gpu_load":worst_event.get("avg_gpu_load") if worst_event else None,
        "worst_dip_avg_power_w":worst_event.get("avg_power_w") if worst_event else None,
        "worst_dip_avg_gpu_clock_mhz":worst_event.get("avg_gpu_clock_mhz") if worst_event else None,
        "isolated_hitch_candidates":len(isolated_indexes),
        "isolated_hitch_gpu_saturated":isolated_gpu,
        "isolated_hitch_gpu_headroom":isolated_headroom,
        "isolated_hitch_transition":isolated_transition,
        "isolated_hitch_mixed":isolated_mixed,
        "worst_isolated_hitch_fps":worst_isolated.get("fps") if worst_isolated else None,
        "worst_isolated_hitch_kind":worst_isolated.get("kind") if worst_isolated else None,
        "worst_isolated_hitch_gpu_load":worst_isolated.get("gpu_load") if worst_isolated else None,
        "worst_isolated_hitch_power_w":worst_isolated.get("power_w") if worst_isolated else None,
        "worst_isolated_hitch_gpu_clock_mhz":worst_isolated.get("gpu_clock_mhz") if worst_isolated else None,
    }

def performance_advisor(rec, raw_available=False):
    """Explain existing analyzer metrics without changing or persisting them."""
    def num(key):
        try:
            value=rec.get(key) if isinstance(rec,dict) else None
            value=float(value)
            return value if math.isfinite(value) else None
        except Exception:return None
    if not isinstance(rec,dict):rec={}
    avg_load=num("avg_gpu_load_pct"); avg_power=num("avg_power_w"); max_power=num("max_power_w")
    max_j=num("max_junction_c"); avg_j=num("avg_junction_c"); max_edge=num("max_edge_c"); avg_edge=num("avg_edge_c")
    max_delta=num("max_temp_delta_c"); avg_delta=num("avg_temp_delta_c")
    gpu_dips=int(num("gpu_bound_dip_events") or 0); headroom_dips=int(num("gpu_headroom_dip_events") or 0)
    mixed_dips=int(num("mixed_dip_events") or 0); transitions=int(num("transition_dip_events") or 0)
    gameplay_dips=int(num("gameplay_dip_events") or 0); isolated=int(num("isolated_hitch_candidates") or 0)
    hitch_gpu=int(num("isolated_hitch_gpu_saturated") or 0); hitch_headroom=int(num("isolated_hitch_gpu_headroom") or 0)
    hitch_transition=int(num("isolated_hitch_transition") or 0); hitch_mixed=int(num("isolated_hitch_mixed") or 0)
    duration=num("duration_seconds") or 0; samples=int(num("paired_perf_samples") or num("dip_analysis_input_samples") or 0)
    dip_share=num("gameplay_dip_fraction_pct")
    cap_status=str(rec.get("frame_cap_status") or "")
    cap_confidence=str(rec.get("frame_cap_confidence") or "Low")
    cap_plateau=num("frame_cap_plateau_fps"); cap_occupancy=num("frame_cap_occupancy_pct"); cap_load=num("frame_cap_avg_gpu_load_pct")
    rating=str(rec.get("frame_dip_rating") or "Unknown — insufficient frame-consistency data")
    diagnoses=[]; recommendations=[]

    total_correlated=gpu_dips+headroom_dips+mixed_dips+hitch_gpu+hitch_headroom+hitch_mixed
    saturated=gpu_dips+hitch_gpu; headroom=headroom_dips+hitch_headroom
    load_evidence=f"{avg_load:.1f}% average GPU utilization" if avg_load is not None else "average GPU utilization unavailable"
    transition_count=transitions+hitch_transition
    if total_correlated:
        event_evidence=f"{saturated} of {total_correlated} gameplay-impact classified lows were GPU-saturated"
        if transition_count:event_evidence+=f"; {transition_count} additional candidate(s) were transition/loading"
    else:event_evidence="no classified gameplay lows to correlate"+(f"; {transition_count} candidate(s) were transition/loading" if transition_count else "")

    transition_only=transition_count>0 and gameplay_dips==0 and (hitch_gpu+hitch_headroom+hitch_mixed)==0
    cap_likely=cap_status=="Frame-rate cap / synchronization likely"
    cap_possible=cap_status=="Possible frame cap or CPU/game-engine limit"
    cap_evidence=str(rec.get("frame_cap_evidence") or f"{cap_occupancy:.0f}% plateau occupancy with GPU headroom" if cap_occupancy is not None else "stable ceiling evidence with GPU headroom")
    if cap_likely:
        limiter="Frame-rate cap / synchronization likely"
        limiter_evidence=cap_evidence
        diagnoses.append("Likely frame-rate ceiling")
        recommendations.append("FPS appears intentionally limited. Raising GPU performance or lowering graphics settings is unlikely to increase frame rate until the active frame cap/synchronization limit is changed — because "+cap_evidence+".")
    elif cap_possible:
        limiter="Possible frame cap or CPU/game-engine limit"
        limiter_evidence=cap_evidence
        diagnoses.append("Ambiguous stable GPU-headroom ceiling")
        recommendations.append("Confirm the configured frame limit or synchronization behavior before reducing graphics quality — because "+cap_evidence+".")
    elif transition_only:
        limiter="No gameplay limiter established; identified transition/loading interruptions"
        limiter_evidence=f"{transition_count} transition/loading event/candidate(s), with 0 sustained gameplay-impact dips"
        diagnoses.append("Transition/loading interruptions")
        recommendations.append(f"Do not change graphics settings for these events — because {limiter_evidence} and they were excluded from gameplay severity.")
    elif headroom>saturated and headroom>0:
        limiter="Likely CPU/game-engine/asset-streaming limited during lows"
        limiter_evidence=f"{load_evidence}; {headroom}/{total_correlated} classified gameplay lows had GPU headroom"
        diagnoses.append("GPU-headroom lows")
        recommendations.append(f"Investigate CPU/game-engine behavior and asset streaming first — because {headroom}/{total_correlated} classified lows occurred with GPU headroom.")
    elif avg_load is not None and avg_load>=95:
        limiter="Strongly GPU-bound"
        limiter_evidence=f"{load_evidence}; {event_evidence}"
        diagnoses.append("Strongly GPU-bound")
        recommendations.append(f"Lower render scale or GPU-heavy graphics settings if more FPS is desired — because {load_evidence} and {event_evidence}.")
    elif avg_load is not None and avg_load>=85:
        limiter="Mostly GPU-bound"
        limiter_evidence=f"{load_evidence}; {event_evidence}"
        diagnoses.append("Mostly GPU-bound")
        recommendations.append(f"Consider a modest render-scale or GPU-heavy setting reduction — because {load_evidence}; no exact FPS gain is inferred.")
    elif avg_load is not None and avg_load<70:
        limiter="Likely CPU/game-engine/streaming limited or otherwise GPU-headroom constrained"
        limiter_evidence=f"{load_evidence}; sustained GPU saturation was not established"
        diagnoses.append("Substantial GPU headroom")
        recommendations.append(f"Inspect CPU/game-engine and streaming behavior before reducing resolution — because {load_evidence} leaves substantial GPU headroom.")
    elif avg_load is not None:
        limiter="Mixed workload"
        limiter_evidence=f"{load_evidence}; event correlation is split or inconclusive ({saturated} saturated, {headroom} headroom, {mixed_dips+hitch_mixed} mixed)"
        diagnoses.append("Mixed workload")
        recommendations.append(f"Compare repeatable scenes before changing settings — because {limiter_evidence}.")
    else:
        limiter="Unknown — insufficient utilization telemetry"
        limiter_evidence="No usable average GPU-utilization metric was recorded"

    scaling=str(rec.get("scaling") or "—")
    if cap_likely:
        opportunity="Low opportunity while the frame-rate ceiling remains active"
        opportunity_evidence=f"{cap_plateau:.1f} FPS estimated plateau with {cap_occupancy:.0f}% occupancy and {cap_load:.1f}% plateau GPU utilization" if None not in (cap_plateau,cap_occupancy,cap_load) else cap_evidence
    elif cap_possible:
        opportunity="Uncertain opportunity until frame-cap versus engine limitation is distinguished"
        opportunity_evidence=cap_evidence
    elif transition_only:
        opportunity="Graphics changes unlikely to address the dominant lows"
        opportunity_evidence=f"all {transition_count} event/candidate(s) were identified as transition/loading activity"
    elif headroom>0 and headroom>=max(1,saturated):
        opportunity="Low opportunity from render-scale/GPU-heavy setting reduction"
        opportunity_evidence=f"{headroom}/{max(total_correlated,headroom)} classified lows had GPU headroom; scaling recorded as {scaling}"
    elif avg_load is not None and avg_load>=95 and (not total_correlated or saturated/total_correlated>=.5):
        opportunity="High opportunity from render-scale/GPU-heavy setting reduction"
        opportunity_evidence=f"{load_evidence}; {event_evidence}; scaling recorded as {scaling}"
    elif avg_load is not None and avg_load>=85:
        opportunity="Moderate opportunity from GPU-heavy setting reduction"
        opportunity_evidence=f"{load_evidence}; event evidence is not strong enough to estimate a gain"
    elif avg_load is not None:
        opportunity="Low opportunity from render-scale/GPU-heavy setting reduction"
        opportunity_evidence=f"{load_evidence} does not establish a persistent GPU bottleneck"
    else:
        opportunity="Insufficient evidence"
        opportunity_evidence="GPU utilization and correlated-event evidence are incomplete"

    persistent_large_delta=(avg_delta is not None and avg_delta>=25) or (avg_delta is not None and avg_delta>=20 and max_delta is not None and max_delta>=30)
    if persistent_large_delta:
        thermal="Large hotspot delta worth investigating"
        diagnoses.append("Large junction-edge delta")
        recommendations.insert(0,f"Inspect cooling/contact and airflow if the delta persists — because average/max junction-edge delta was {advisor_pair(avg_delta,max_delta,'°C')}.")
    elif (max_j is not None and max_j>=100) or (avg_j is not None and avg_j>=95) or (max_j is None and max_edge is not None and max_edge>=90):
        thermal="Hot; exact GPU-specific limit is not available from recorded telemetry"
        diagnoses.append("Thermal concern")
        recommendations.insert(0,f"Consider cooling, fan-curve tuning, or a mild stable undervolt — because junction was {advisor_pair(avg_j,max_j,'°C')} with {advisor_pair(avg_delta,max_delta,'°C')} delta; temperature alone does not imply a mount problem.")
    elif (max_j is not None and max_j>=90) or (avg_j is not None and avg_j>=85) or (max_j is None and ((max_edge is not None and max_edge>=80) or (avg_edge is not None and avg_edge>=75))):
        thermal="Warm to hot, with no exact throttle limit inferred"
        recommendations.append(f"Monitor thermals across comparable sessions — because junction was {advisor_pair(avg_j,max_j,'°C')} and edge was {advisor_pair(avg_edge,max_edge,'°C')}.")
    elif max_j is not None or max_edge is not None:
        thermal="Normal recorded thermal range"
    else:
        thermal="Unknown — insufficient temperature telemetry"

    thermal_evidence=f"edge {advisor_pair(avg_edge,max_edge,'°C')}; junction {advisor_pair(avg_j,max_j,'°C')}; junction-edge delta {advisor_pair(avg_delta,max_delta,'°C')}"

    if avg_power is not None and max_power and max_power>0 and avg_load is not None and avg_load>=85 and avg_power/max_power>=.90:
        power="Sustained heavy GPU load"
        diagnoses.append("Sustained high-power GPU workload")
        recommendations.append(f"Treat power as sustained workload evidence, not proof of throttling — because power averaged {avg_power:.0f} W versus a {max_power:.0f} W session peak at {avg_load:.1f}% GPU utilization.")
    elif avg_power is not None:
        power="Recorded board-power context"
    else:power="Unknown — insufficient power telemetry"
    power_evidence=advisor_pair(avg_power,max_power," W")
    if transitions>0 and not transition_only:diagnoses.append("Transition/loading interruptions")
    if gameplay_dips>=4:
        diagnoses.append("Repeated sustained dips")
        dominant="GPU-saturated" if gpu_dips>=max(headroom_dips,mixed_dips) and gpu_dips else ("GPU-headroom" if headroom_dips>=mixed_dips and headroom_dips else "mixed")
        recommendations.append(f"Investigate repeated sustained dips with emphasis on {dominant} events — because {gameplay_dips} gameplay-impact dips were recorded.")
    elif "rare brief dips" in rating.lower():
        diagnoses.append("Smooth / rare brief dips")
        share=f"{dip_share:.2f}%" if dip_share is not None else "an unrecorded share"
        recommendations.append(f"Avoid broad changes for rare dips alone — because {gameplay_dips} gameplay-impact dips occupied {share} of gameplay and may not materially affect play.")
    elif rating.lower().startswith("smooth"):diagnoses.append("Smooth frame delivery")
    if isolated>0:
        diagnoses.append("Isolated hitch candidates")
        recommendations.append(f"Treat isolated hitches as lower-confidence evidence — because {isolated} single-sample candidate(s) need repeatability before attribution.")

    duration_text=format_session_duration(duration)
    share_text=f"; {dip_share:.2f}% of gameplay" if dip_share is not None else ""
    frame_evidence=f"{gameplay_dips} sustained gameplay-impact dip(s); {isolated} isolated candidate(s) over {duration_text}{share_text}"

    raw_available=bool(raw_available) or rec.get("analysis_context")=="telemetry_simulator"
    confidence_score=(2 if duration>=600 else 1 if duration>=180 else 0)+(2 if samples>=300 else 1 if samples>=60 else 0)+(1 if raw_available else 0)
    if total_correlated+transitions>=3:confidence_score+=1
    if cap_likely and cap_confidence=="High":confidence_score=max(confidence_score,5)
    elif cap_likely or cap_possible:confidence_score=max(confidence_score,3)
    if limiter=="Mixed workload":confidence_score=min(confidence_score-1,4)
    confidence="High" if confidence_score>=5 else "Moderate" if confidence_score>=3 else "Low"
    confidence_evidence=f"{duration_text}, {samples} paired sample(s), raw/replay telemetry {'available' if raw_available else 'unavailable'}"
    if limiter=="Mixed workload":confidence_evidence+="; mixed workload reduces causal confidence"

    if limiter.startswith("Unknown") and thermal.startswith("Unknown") and rating.startswith("Unknown"):
        overall="Insufficient telemetry for a confident advisor summary"
        recommendations=["Capture a longer Gameplay session before changing settings — because paired utilization, thermal, and frame-consistency evidence is incomplete."]
    else:overall=f"{rating}; {limiter.lower()}"
    # Stable de-duplication preserves ranking.
    recommendations=list(dict.fromkeys(recommendations))
    return {"overall":overall,"primary_limiter":limiter,"primary_limiter_evidence":limiter_evidence,
            "frame_consistency":rating,"frame_consistency_evidence":frame_evidence,"thermals":thermal,"thermal_evidence":thermal_evidence,
            "power":power,"power_evidence":power_evidence,"optimization_opportunity":opportunity,"optimization_evidence":opportunity_evidence,
            "confidence":confidence,"confidence_evidence":confidence_evidence,
            "top_recommendation":recommendations[0] if recommendations else "No specific change is supported by the available evidence.",
            "diagnoses":diagnoses,"recommendations":recommendations,
            "thermal_context":{"average_edge_c":avg_edge,"max_edge_c":max_edge,"average_junction_c":avg_j,"max_junction_c":max_j,"average_delta_c":avg_delta,"max_delta_c":max_delta}}


def game_session_analysis(rec, history_sessions=()):
    """Interpret a completed session conservatively from recorded telemetry."""
    if not isinstance(rec,dict):
        return ["Analysis unavailable."]
    if game_session_quality(rec)!="Gameplay":
        return ["Limited analysis: this session is not classified as Gameplay."]

    def num(key):
        try:
            v=rec.get(key)
            return float(v) if v is not None else None
        except Exception:
            return None

    raw_avg=num("raw_sampled_avg_fps")
    raw_p1=num("raw_sampled_p1_fps")
    gameplay_avg=num("gameplay_avg_fps")
    gameplay_p1=num("gameplay_p1_fps")
    avg_fps=gameplay_avg if gameplay_avg is not None else num("avg_fps")
    p1=gameplay_p1 if gameplay_p1 is not None else num("p1_fps")
    avg_load=num("avg_gpu_load_pct"); max_load=num("max_gpu_load_pct")
    avg_power=num("avg_power_w"); max_power=num("max_power_w")
    avg_j=num("avg_junction_c"); max_j=num("max_junction_c")
    avg_dt=num("avg_temp_delta_c"); max_dt=num("max_temp_delta_c")
    out=[]

    menu_seconds=num("likely_menu_seconds")
    menu_samples=num("likely_menu_samples")
    if menu_samples is not None and menu_samples>0:
        out.append(
            f"Menu/cap filtering: excluded about {menu_seconds:.0f}s of confidently detected capped/low-GPU intervals from Gameplay FPS metrics; raw session FPS remains preserved."
        )
    elif gameplay_avg is not None:
        out.append("Menu/cap filtering: no sustained capped + low-GPU interval was confidently detected.")

    cap_status=str(rec.get("frame_cap_status") or "Insufficient evidence")
    if cap_status!="Insufficient evidence":
        plateau=num("frame_cap_plateau_fps"); occupancy=num("frame_cap_occupancy_pct"); cap_load=num("frame_cap_avg_gpu_load_pct")
        cap_detail=f"Gameplay frame-cap analysis: {cap_status}"
        if plateau is not None:cap_detail+=f"; estimated plateau {plateau:.1f} FPS"
        if occupancy is not None:cap_detail+=f", {occupancy:.0f}% occupancy"
        if cap_load is not None:cap_detail+=f", {cap_load:.1f}% average GPU load during the plateau"
        out.append(cap_detail+". This is a gameplay limiter interpretation and does not remove capped gameplay from FPS statistics.")

    dip_status=str(rec.get("dip_analysis_status") or "")
    dip_rating=rec.get("frame_dip_rating")
    dip_events=num("frame_dip_events")
    dip_fraction=num("frame_dip_fraction_pct")
    gameplay_dip_events=num("gameplay_dip_events")
    gameplay_dip_fraction=num("gameplay_dip_fraction_pct")
    full_stalls=num("full_stall_candidates")
    gpu_dips=num("gpu_bound_dip_events")
    headroom_dips=num("gpu_headroom_dip_events")
    mixed_dips=num("mixed_dip_events")
    transition_dips=num("transition_dip_events")
    hitch_candidates=num("isolated_hitch_candidates")
    hitch_gpu=num("isolated_hitch_gpu_saturated")
    hitch_headroom=num("isolated_hitch_gpu_headroom")
    hitch_transition=num("isolated_hitch_transition")
    hitch_mixed=num("isolated_hitch_mixed")
    if dip_status and dip_status!="ok":
        out.append(f"Frame-dip analyzer status: {dip_status}.")
    if dip_rating and dip_rating!="Insufficient paired gameplay data":
        detail=f"Frame consistency: {dip_rating}"
        if gameplay_dip_events is not None:
            detail+=f"; {gameplay_dip_events:.0f} gameplay-impact sustained dip event(s)"
        if gameplay_dip_fraction is not None:
            detail+=f", {gameplay_dip_fraction:.1f}% of paired gameplay time"
        if dip_events is not None and gameplay_dip_events is not None and dip_events>gameplay_dip_events:
            detail+=f" ({int(dip_events-gameplay_dip_events)} transition/loading event(s) excluded from severity)"
        out.append(detail+".")
        if full_stalls is not None and full_stalls>0:
            out.append(f"Full-stall candidates: {int(full_stalls)} event/sample(s) reached ≤1 FPS; timestamps are listed in Session Details.")
        if (gpu_dips or 0)+(headroom_dips or 0)+(transition_dips or 0)+(mixed_dips or 0)>0:
            out.append(
                f"Dip correlation: {int(gpu_dips or 0)} GPU-saturated, "
                f"{int(headroom_dips or 0)} GPU-headroom, {int(transition_dips or 0)} likely transition/loading, "
                f"{int(mixed_dips or 0)} mixed/uncertain event(s). "
                "GPU-headroom dips can be consistent with CPU/game-engine/asset-streaming limits; "
                "transition/loading dips show a near-idle GPU state and should not be treated as ordinary gameplay stutter."
            )
        if hitch_candidates is not None and hitch_candidates>0:
            out.append(
                f"Isolated hitch candidates: {int(hitch_candidates)} single-sample low(s) were detected outside sustained dips "
                f"({int(hitch_gpu or 0)} GPU-saturated, {int(hitch_headroom or 0)} GPU-headroom, "
                f"{int(hitch_transition or 0)} likely transition/loading, {int(hitch_mixed or 0)} mixed/uncertain). "
                "These are lower-confidence events and may be too brief to notice."
            )

    if avg_load is not None:
        if avg_load>=95:
            out.append("GPU utilization: strongly GPU-bound in this session; render scaling or lower GPU-heavy settings should have the most room to raise FPS.")
        elif avg_load>=85:
            out.append("GPU utilization: mostly GPU-limited, but there is some headroom; CPU/game-engine limits may also appear in parts of the session.")
        elif avg_load<70:
            out.append("GPU utilization: substantial GPU headroom; lowering render resolution may give limited benefit unless brief GPU-bound spikes dominate.")
        else:
            out.append("GPU utilization: mixed workload; neither a persistent GPU bottleneck nor large GPU headroom is obvious.")

    if avg_fps is not None and p1 is not None and avg_fps>0:
        ratio=p1/avg_fps
        display_ratio=min(1.0,ratio)
        transitions_explain_low=(
            (transition_dips or 0)>0 and (gameplay_dip_events or 0)==0 and
            (gpu_dips or 0)==0 and (headroom_dips or 0)==0 and (mixed_dips or 0)==0
        )
        if ratio<0.65 and transitions_explain_low:
            out.append("Frame consistency: raw/gameplay P1 is low because of identified transition/loading activity; those events were excluded from gameplay consistency severity.")
        elif ratio<0.65:
            out.append(f"Frame consistency: weak P1/average ratio ({display_ratio*100:.0f}%); noticeable lows/stutter are more likely than the average FPS alone suggests.")
        elif ratio<0.80:
            out.append(f"Frame consistency: moderate P1/average ratio ({display_ratio*100:.0f}%); lows are meaningfully below the average.")
        else:
            out.append(f"Frame consistency: good P1/average ratio ({display_ratio*100:.0f}%).")

    if avg_power is not None and max_power is not None and max_power>0:
        pr=avg_power/max_power
        if pr>=0.90:
            out.append("Power behavior: sustained board power is close to the session peak, consistent with a heavy sustained GPU workload.")
        elif pr<0.65:
            out.append("Power behavior: average board power is well below the session peak, suggesting a variable or partially limited workload.")

    if max_j is not None:
        if max_j>=100:
            out.append("Thermals: junction temperature reached 100°C or higher; watch for repeated sustained peaks and check cooling behavior.")
        elif max_j>=95:
            out.append("Thermals: junction temperature reached the upper-90s; worth monitoring across longer comparable sessions.")
        elif max_j<90:
            out.append("Thermals: recorded junction peak stayed below 90°C in this session.")
    if max_dt is not None:
        out.append("Thermal spread: "+thermal_delta_context(rec)+".")

    # Personal baseline: exact same game/profile/preset/scaling, Gameplay only, excluding self.
    if rec.get("analysis_context")!="telemetry_simulator":
        peers=[]
        for other in list(history_sessions or ()):
            if other is rec or game_session_quality(other)!="Gameplay":
                continue
            if game_session_setup_key(other)!=game_session_setup_key(rec):
                continue
            try:
                candidate=other.get("gameplay_avg_fps")
                if candidate is None:
                    candidate=other.get("avg_fps")
                f=float(candidate)
            except Exception:
                continue
            peers.append(f)
        if avg_fps is not None and peers:
            base=sum(peers)/len(peers)
            if base>0:
                pct=(avg_fps-base)/base*100.0
                direction="above" if pct>=0 else "below"
                label="Gameplay average FPS" if gameplay_avg is not None else "Average FPS"
                out.append(f"Personal baseline: {label} is {abs(pct):.1f}% {direction} {len(peers)} prior comparable session(s) ({base:.1f} FPS baseline).")
        elif avg_fps is not None:
            out.append("Personal baseline: no prior exact-match Gameplay session is available yet.")

    return out or ["Not enough recorded telemetry for a useful analysis."]
