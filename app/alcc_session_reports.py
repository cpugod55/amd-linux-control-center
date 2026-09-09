"""Pure saved-session text report formatting helpers.

No Tk, filesystem access, process control, or GPU writes live here.  Callers
resolve replay availability/analyzer labels before entering this module.
"""

from alcc_session_analysis import (
    game_session_analysis,
    game_session_quality,
    game_session_setup_key,
    performance_advisor,
    thermal_delta_context,
)


def format_session_duration(seconds):
    try:
        dur=max(0,int(round(float(seconds))))
    except Exception:
        return "—"
    if dur>=3600:
        return f"{dur//3600}h {(dur%3600)//60}m {dur%60}s"
    if dur>=60:
        return f"{dur//60}m {dur%60}s"
    return f"{dur}s"


def format_session_metric(value,suffix="",digits=1):
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except Exception:
        return str(value)


def session_compare_number(rec,key):
    try:
        value=rec.get(key)
        return None if value is None else float(value)
    except Exception:
        return None


def performance_advisor_lines(rec,raw_available=False,synthetic=False):
    advisor=performance_advisor(rec,raw_available=raw_available)
    title="PERFORMANCE ADVISOR"+(" — SYNTHETIC" if synthetic else "")
    lines=[
        title,
        f"Overall: {advisor['overall']}",
        f"Confidence: {advisor['confidence']} — {advisor['confidence_evidence']}",
        f"Primary limiter: {advisor['primary_limiter']} — {advisor['primary_limiter_evidence']}",
        f"Frame consistency: {advisor['frame_consistency']} — {advisor['frame_consistency_evidence']}",
        f"Thermals: {advisor['thermals']} — {advisor['thermal_evidence']}",
        f"Power: {advisor['power']} — {advisor['power_evidence']}",
        f"Optimization opportunity: {advisor['optimization_opportunity']} — {advisor['optimization_evidence']}",
        f"Top recommendation: {advisor['top_recommendation']}",
    ]
    if len(advisor["recommendations"])>1:
        lines += ["Ranked recommendations:"]+[f"  {i}. {text}" for i,text in enumerate(advisor["recommendations"],1)]
    return lines


def game_session_details_text(rec,*,analyzer_label="Legacy analyzer",raw_available=False,history_sessions=()):
    if not isinstance(rec,dict):
        return "No saved session selected."
    f=format_session_metric
    live_p1=rec.get("live_reported_p1_fps") if rec.get("live_reported_p1_fps") is not None else rec.get("p1_fps")
    live_sources=rec.get("live_p1_sources") or []
    live_source_text=", ".join(str(x) for x in live_sources) if live_sources else "legacy source not recorded"
    lines=[
        f"Game: {rec.get('game','Game')}    Steam AppID: {rec.get('steam_appid') or '—'}",
        f"Started: {rec.get('started_iso') or '—'}    Ended: {rec.get('ended_iso') or '—'}    Duration: {format_session_duration(rec.get('duration_seconds'))}",
        f"Session quality: {game_session_quality(rec)}    Thermal context: {thermal_delta_context(rec)}",
        f"Analyzer: {analyzer_label}    Schema: {rec.get('schema_version') or 'legacy'}    Offline replay: {'available' if raw_available else 'unavailable (no raw telemetry)'}",
        f"FPS telemetry: {rec.get('telemetry_status') or ('Captured' if rec.get('avg_fps') is not None else 'Legacy / unavailable')}    Method: {rec.get('telemetry_method') or 'Legacy / not recorded'}",
        f"Telemetry parser: {rec.get('telemetry_parser_status') or 'Legacy / not recorded'}",
        "",
        *performance_advisor_lines(rec,raw_available=raw_available),
        "",
        f"Raw session FPS: average {f(rec.get('raw_sampled_avg_fps') if rec.get('raw_sampled_avg_fps') is not None else rec.get('avg_fps'),' FPS')}    Raw sampled P1 {f(rec.get('raw_sampled_p1_fps'),' FPS')}",
        f"Gameplay FPS: average {f(rec.get('gameplay_avg_fps'),' FPS')}    Gameplay P1 {f(rec.get('gameplay_p1_fps'),' FPS')}",
        f"Provider/live rolling P1: {f(live_p1,' FPS')}    sources: {live_source_text}    (p1_fps compatibility field)",
        f"Likely menu/capped time: {f(rec.get('likely_menu_seconds'),'s',0)}    paired samples: {f(rec.get('paired_perf_samples'),' ',0)}",
        f"Cap/synchronization analysis: {rec.get('frame_cap_status') or 'Unavailable'}    confidence: {rec.get('frame_cap_confidence') or '—'}",
        f"Estimated gameplay plateau: {f(rec.get('frame_cap_plateau_fps'),' FPS')}    occupancy: {f(rec.get('frame_cap_occupancy_pct'),'%')}    dispersion: {f(rec.get('frame_cap_dispersion_pct'),'%')}",
        f"Cap evidence window: {f(rec.get('frame_cap_duration_seconds'),'s',0)} / {f(rec.get('frame_cap_samples'),' samples',0)}    continuity: {f(rec.get('frame_cap_continuity_pct'),'%')}",
        f"Plateau context: GPU load {f(rec.get('frame_cap_avg_gpu_load_pct'),'%')}    board power {f(rec.get('frame_cap_avg_power_w'),' W')}    GPU clock {f(rec.get('frame_cap_avg_gpu_clock_mhz'),' MHz',0)}",
        f"Display refresh evidence: {f(rec.get('frame_cap_refresh_hz'),' Hz')}" if rec.get("frame_cap_refresh_hz") is not None else "Display refresh evidence: unavailable for this recorded session; no refresh rate is inferred from FPS.",
        f"Frame consistency rating: {rec.get('frame_dip_rating') or '—'}    analysis status: {rec.get('dip_analysis_status') or '—'}",
        f"Dip analyzer input: {f(rec.get('dip_analysis_input_samples'),' paired gameplay samples',0)}",
        f"Gameplay-impact dips: {f(rec.get('gameplay_dip_events'),' ',0)}    gameplay dip share: {f(rec.get('gameplay_dip_fraction_pct'),'%')}",
        f"Full-stall candidates (≤1 FPS): {f(rec.get('full_stall_candidates'),' ',0)}",
        f"Gameplay median: {f(rec.get('gameplay_median_fps'),' FPS')}    dip threshold: {f(rec.get('frame_dip_threshold_fps'),' FPS')}",
        f"Frame dips: {f(rec.get('frame_dip_events'),' events',0)}    time in dips: {f(rec.get('frame_dip_seconds'),'s',0)}    samples in dips: {f(rec.get('frame_dip_fraction_pct'),'%')}",
        f"Dip classification: GPU-saturated {f(rec.get('gpu_bound_dip_events'),' ',0)}    GPU-headroom {f(rec.get('gpu_headroom_dip_events'),' ',0)}    transition/loading {f(rec.get('transition_dip_events'),' ',0)}    mixed {f(rec.get('mixed_dip_events'),' ',0)}",
        f"Worst dip: {rec.get('worst_dip_kind') or '—'}    load {f(rec.get('worst_dip_avg_gpu_load'),'%')}    power {f(rec.get('worst_dip_avg_power_w'),' W')}    clock {f(rec.get('worst_dip_avg_gpu_clock_mhz'),' MHz',0)}",
        f"Isolated hitch candidates: {f(rec.get('isolated_hitch_candidates'),' ',0)}    GPU-saturated {f(rec.get('isolated_hitch_gpu_saturated'),' ',0)}    GPU-headroom {f(rec.get('isolated_hitch_gpu_headroom'),' ',0)}    transition/loading {f(rec.get('isolated_hitch_transition'),' ',0)}    mixed {f(rec.get('isolated_hitch_mixed'),' ',0)}",
        f"Worst isolated candidate: {f(rec.get('worst_isolated_hitch_fps'),' FPS')}    {rec.get('worst_isolated_hitch_kind') or '—'}    load {f(rec.get('worst_isolated_hitch_gpu_load'),'%')}    power {f(rec.get('worst_isolated_hitch_power_w'),' W')}    clock {f(rec.get('worst_isolated_hitch_gpu_clock_mhz'),' MHz',0)}",
        "",
        "EVENT TIMESTAMPS",
    ]
    dip_log=rec.get("dip_event_log") or []
    hitch_log=rec.get("isolated_hitch_log") or []
    stall_log=rec.get("full_stall_log") or []
    for e in dip_log[:12]:
        lines.append(
            f"• {e.get('clock','—')} sustained dip — {e.get('kind','—')} — min {f(e.get('min_fps'),' FPS')} — "
            f"load {f(e.get('avg_gpu_load'),'%')} — power {f(e.get('avg_power_w'),' W')} — clock {f(e.get('avg_gpu_clock_mhz'),' MHz',0)}"
        )
    for e in hitch_log[:12]:
        lines.append(
            f"• {e.get('clock','—')} isolated candidate — {e.get('kind','—')} — {f(e.get('fps'),' FPS')} — "
            f"load {f(e.get('gpu_load'),'%')} — power {f(e.get('power_w'),' W')} — clock {f(e.get('gpu_clock_mhz'),' MHz',0)}"
        )
    if stall_log:
        lines.append("Full-stall candidate timestamps: "+", ".join(str(e.get("clock","—")) for e in stall_log[:12]))
    if not dip_log and not hitch_log:
        lines.append("• No timestamped dip/hitch events recorded.")
    lines += [
        "",
        f"GPU load: average {f(rec.get('avg_gpu_load_pct'),'%')}    max {f(rec.get('max_gpu_load_pct'),'%')}",
        f"Edge temp: average {f(rec.get('avg_edge_c'),'°C')}    max {f(rec.get('max_edge_c'),'°C')}",
        f"Junction: average {f(rec.get('avg_junction_c'),'°C')}    max {f(rec.get('max_junction_c'),'°C')}",
        f"Junction − Edge ΔT: average {f(rec.get('avg_temp_delta_c'),'°C')}    max {f(rec.get('max_temp_delta_c'),'°C')}",
        f"Board power: average {f(rec.get('avg_power_w'),' W')}    max {f(rec.get('max_power_w'),' W')}",
        f"GPU clock: average {f(rec.get('avg_gpu_clock_mhz'),' MHz',0)}    max {f(rec.get('max_gpu_clock_mhz'),' MHz',0)}",
        f"Memory clock: average {f(rec.get('avg_memory_clock_mhz'),' MHz',0)}    max {f(rec.get('max_memory_clock_mhz'),' MHz',0)}",
        f"VRAM used: average {f(rec.get('avg_vram_pct'),'%')}    max {f(rec.get('max_vram_pct'),'%')}",
        "",
        f"GPU profile: {rec.get('gpu_profile') or '—'}",
        f"Graphics preset: {rec.get('graphics_preset') or '—'}",
        f"Scaling: {rec.get('scaling') or '—'}",
        f"Session close reason: {rec.get('reason') or '—'}",
        "",
        "PERFORMANCE ANALYSIS",
    ]
    lines += [f"• {x}" for x in game_session_analysis(rec,history_sessions)]
    return "\n".join(lines)


def game_session_comparison_text(older,newer,*,raw_available_older=False,raw_available_newer=False):
    if not isinstance(older,dict) or not isinstance(newer,dict):
        return "Select exactly two saved sessions to compare."
    rows=[
        ("Raw average FPS","raw_sampled_avg_fps"," FPS",1,True),
        ("Raw sampled P1","raw_sampled_p1_fps"," FPS",1,True),
        ("Gameplay average FPS","gameplay_avg_fps"," FPS",1,True),
        ("Gameplay P1 FPS","gameplay_p1_fps"," FPS",1,True),
        ("Likely menu/capped","likely_menu_seconds"," s",0,False),
        ("Estimated FPS plateau","frame_cap_plateau_fps"," FPS",1,None),
        ("Plateau occupancy","frame_cap_occupancy_pct","%",1,None),
        ("Plateau dispersion","frame_cap_dispersion_pct","%",1,False),
        ("Frame dip events","frame_dip_events","",0,False),
        ("Gameplay-impact dips","gameplay_dip_events","",0,False),
        ("Transition/loading dips","transition_dip_events","",0,False),
        ("Full-stall candidates","full_stall_candidates","",0,False),
        ("Isolated hitch candidates","isolated_hitch_candidates","",0,False),
        ("Time in frame dips","frame_dip_seconds"," s",0,False),
        ("Samples in frame dips","frame_dip_fraction_pct","%",1,False),
        ("Worst short-window FPS","worst_window_fps"," FPS",1,True),
        ("Average GPU load","avg_gpu_load_pct","%",1,None),
        ("Max GPU load","max_gpu_load_pct","%",1,None),
        ("Average edge temp","avg_edge_c","°C",1,False),
        ("Max edge temp","max_edge_c","°C",1,False),
        ("Average junction","avg_junction_c","°C",1,False),
        ("Max junction","max_junction_c","°C",1,False),
        ("Average junction-edge ΔT","avg_temp_delta_c","°C",1,False),
        ("Max junction-edge ΔT","max_temp_delta_c","°C",1,False),
        ("Average board power","avg_power_w"," W",1,False),
        ("Max board power","max_power_w"," W",1,False),
        ("Average GPU clock","avg_gpu_clock_mhz"," MHz",0,None),
        ("Max GPU clock","max_gpu_clock_mhz"," MHz",0,None),
        ("Average memory clock","avg_memory_clock_mhz"," MHz",0,None),
        ("Max memory clock","max_memory_clock_mhz"," MHz",0,None),
        ("Average VRAM used","avg_vram_pct","%",1,False),
        ("Max VRAM used","max_vram_pct","%",1,False),
    ]
    warnings=[]
    qa=game_session_quality(older); qb=game_session_quality(newer)
    if qa!="Gameplay" or qb!="Gameplay":
        warnings.append(f"Session quality differs/limited: A={qa}, B={qb}. Treat performance deltas cautiously.")
    try:
        da=float(older.get("duration_seconds") or 0); db=float(newer.get("duration_seconds") or 0)
        if min(da,db)>0 and max(da,db)/min(da,db)>=2.0:
            warnings.append("Session durations differ by 2× or more; map/gameplay mix can dominate FPS and power differences.")
    except Exception:
        pass
    if game_session_setup_key(older)!=game_session_setup_key(newer):
        warnings.append("Game/profile/preset/scaling setup is not identical, so this is not a controlled comparison.")

    lines=[
        "SESSION COMPARISON",
        f"A (older): {older.get('game','Game')} • {older.get('ended_iso','—')} • {qa}",
        f"B (newer): {newer.get('game','Game')} • {newer.get('ended_iso','—')} • {qb}",
    ]
    if warnings:
        lines += ["", "COMPARISON CAUTION:"] + [f"- {w}" for w in warnings]
    aa=performance_advisor(older,raw_available=raw_available_older)
    ab=performance_advisor(newer,raw_available=raw_available_newer)
    def delta(key,suffix):
        a=session_compare_number(older,key); b=session_compare_number(newer,key)
        return None if a is None or b is None else f"{b-a:+.1f}{suffix}"
    load_delta=delta("avg_gpu_load_pct"," percentage points")
    junction_delta=delta("avg_junction_c","°C average junction")
    power_delta=delta("avg_power_w"," W average board power")
    a_load=session_compare_number(older,"avg_gpu_load_pct"); b_load=session_compare_number(newer,"avg_gpu_load_pct")
    if load_delta:
        load_relation="B was more GPU-bound" if b_load>a_load else "A was more GPU-bound" if a_load>b_load else "Average GPU utilization was unchanged"
        load_relation+=f" ({load_delta})"
    else:
        load_relation="GPU-bound change is unavailable"
    consistency_order={"smooth":4,"good":3,"minor":2,"significant":1,"unknown":0}
    def consistency_rank(value):
        text=str(value or "unknown").lower()
        return next((score for name,score in consistency_order.items() if name in text),0)
    ra=consistency_rank(older.get("frame_dip_rating")); rb=consistency_rank(newer.get("frame_dip_rating"))
    consistency_relation="B had better frame consistency" if rb>ra else "A had better frame consistency" if ra>rb else "Frame-consistency category was unchanged"
    a_j=session_compare_number(older,"avg_junction_c"); b_j=session_compare_number(newer,"avg_junction_c")
    heat_relation=(("B ran hotter" if b_j>a_j else "A ran hotter" if a_j>b_j else "Average junction temperature was unchanged")+f" ({junction_delta})") if junction_delta else "Junction-temperature change is unavailable"
    a_power=session_compare_number(older,"avg_power_w"); b_power=session_compare_number(newer,"avg_power_w")
    power_relation=(("B used more power" if b_power>a_power else "A used more power" if a_power>b_power else "Average board power was unchanged")+f" ({power_delta})") if power_delta else "Power change is unavailable"
    comparison_confidence="Low" if warnings else ("High" if aa["confidence"]==ab["confidence"]=="High" else "Moderate")
    reliability="comparison conditions differ; causation is uncertain" if warnings else "setup and duration checks found no major mismatch, though map/gameplay can still differ"
    lines += [
        "","ADVISOR SUMMARY",
        f"A: {aa['primary_limiter']} / {aa['frame_consistency']} / {aa['thermals']} / confidence {aa['confidence']}",
        f"B: {ab['primary_limiter']} / {ab['frame_consistency']} / {ab['thermals']} / confidence {ab['confidence']}",
        f"Comparison confidence: {comparison_confidence} — {reliability}.",
        f"Measured summary: {load_relation}; {consistency_relation}; {heat_relation}; {power_relation}.",
    ]
    lines += [
        "",
        f"{'Metric':<25} {'A':>12} {'B':>12} {'Change B-A':>16}",
        "-"*69,
    ]
    for label,key,suffix,digits,higher_better in rows:
        a=session_compare_number(older,key); b=session_compare_number(newer,key)
        if a is None or b is None:
            av=format_session_metric(a,suffix,digits); bv=format_session_metric(b,suffix,digits); change="—"
        else:
            av=f"{a:.{digits}f}{suffix}"; bv=f"{b:.{digits}f}{suffix}"
            d=b-a; change=f"{d:+.{digits}f}{suffix}"
            if higher_better is True and abs(d)>1e-9:
                change += "  better" if d>0 else "  worse"
            elif higher_better is False and abs(d)>1e-9:
                change += "  lower" if d<0 else "  higher"
        lines.append(f"{label:<25} {av:>12} {bv:>12} {change:>16}")
    lines += [
        "",
        f"Duration: {format_session_duration(older.get('duration_seconds'))} → {format_session_duration(newer.get('duration_seconds'))}",
        f"GPU profile: {older.get('gpu_profile') or '—'} → {newer.get('gpu_profile') or '—'}",
        f"Graphics preset: {older.get('graphics_preset') or '—'} → {newer.get('graphics_preset') or '—'}",
        f"Scaling: {older.get('scaling') or '—'} → {newer.get('scaling') or '—'}",
        f"Frame consistency rating: {older.get('frame_dip_rating') or '—'} → {newer.get('frame_dip_rating') or '—'}",
        f"Thermal ΔT context: {thermal_delta_context(older)} → {thermal_delta_context(newer)}",
    ]
    return "\n".join(lines)
