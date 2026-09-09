#!/usr/bin/env python3
"""Session lifecycle and telemetry-record assembly for AMD Linux Control Center.

This module deliberately contains no Tk/UI code, Steam launch manipulation, or
MangoHud/Gamescope setup.  It owns only the mutable per-game session state,
sample ingestion/pairing, finish gating, and construction of a completed
session record.
"""
import time


def _num(value):
    try:
        value=float(value)
        return value if value==value else None
    except Exception:
        return None


def build_session_state(*, identity, game, steam_appid, started_at, gpu_profile,
                        graphics_preset, scaling, render_resolution,
                        output_resolution, power_limit_w, workload_profile,
                        telemetry_identity, telemetry_method, display_refresh_hz):
    return {
        "identity":identity,
        "game":str(game or "Game"),
        "steam_appid":str(steam_appid or ""),
        "started_at":started_at,
        "started_iso":time.strftime("%Y-%m-%d %H:%M:%S",time.localtime(started_at)),
        "gpu_profile":gpu_profile,
        "graphics_preset":graphics_preset,
        "scaling":scaling,
        "render_resolution":render_resolution,
        "output_resolution":output_resolution,
        "power_limit_w":power_limit_w,
        "workload_profile":workload_profile,
        "telemetry_identity":str(telemetry_identity or ""),
        "telemetry_status":"Game detected — waiting for telemetry",
        "telemetry_method":telemetry_method or "Not instrumented / provider unavailable",
        "display_refresh_hz":display_refresh_hz,
        "fps":[], "p1":[], "p1_sources":[], "edge":[], "junction":[],
        "temp_delta":[], "gpu_load":[], "power":[], "gpu_clock":[],
        "memory_clock":[], "vram_pct":[], "paired_perf":[],
        "_last_fps":None, "_last_fps_time":None,
    }


def ingest_session_sample(cur, mh=None, gpu_metrics=None, *, now_monotonic=None, max_samples=30000):
    """Mutate *cur* with one telemetry/GPU refresh and return a live-analysis sample.

    The return value is None unless a recent FPS value can be paired with a GPU
    utilization sample.  This mirrors ALCC's existing 2.5-second pairing rule.
    """
    if not isinstance(cur,dict): return None
    mh=mh or {}; gpu_metrics=gpu_metrics or {}
    if mh.get("telemetry_state"): cur["telemetry_status"]=mh.get("telemetry_state")
    if mh.get("parser_status"): cur["telemetry_parser_status"]=mh.get("parser_status")
    if mh.get("source_path"): cur["telemetry_source_path"]=mh.get("source_path")
    now_fn=now_monotonic or time.monotonic

    fps=_num(mh.get("fps")); p1=_num(mh.get("low"))
    if fps is not None and 0<=fps<2000:
        cur["fps"].append(fps); cur["_last_fps"]=fps; cur["_last_fps_time"]=now_fn()
    if p1 is not None and 0<p1<2000:
        cur["p1"].append(p1)
        source=str(mh.get("low_kind") or "unknown_live")
        if source not in cur.setdefault("p1_sources",[]): cur["p1_sources"].append(source)

    temps=gpu_metrics.get("temps",{}) if isinstance(gpu_metrics,dict) else {}
    edge=_num(temps.get("edge") if isinstance(temps,dict) else None)
    junction=_num(temps.get("junction") if isinstance(temps,dict) else None)
    temp_delta=(junction-edge) if junction is not None and edge is not None else None
    load=_num(gpu_metrics.get("busy") if isinstance(gpu_metrics,dict) else None)
    power=_num(gpu_metrics.get("power_w") if isinstance(gpu_metrics,dict) else None)
    sclk=_num(gpu_metrics.get("sclk") if isinstance(gpu_metrics,dict) else None)
    mclk=_num(gpu_metrics.get("mclk") if isinstance(gpu_metrics,dict) else None)
    vram_pct=None
    if isinstance(gpu_metrics,dict):
        used=_num(gpu_metrics.get("vram_used")); total=_num(gpu_metrics.get("vram_total"))
        if used is not None and total not in (None,0): vram_pct=max(0.0,min(100.0,100.0*used/total))

    for key,value in (("edge",edge),("junction",junction),("temp_delta",temp_delta),
                      ("gpu_load",load),("power",power),("gpu_clock",sclk),
                      ("memory_clock",mclk),("vram_pct",vram_pct)):
        if value is not None: cur[key].append(value)

    live_sample=None
    last_fps=cur.get("_last_fps"); last_fps_time=cur.get("_last_fps_time")
    if load is not None and last_fps is not None and last_fps_time is not None:
        now=now_fn(); age=now-float(last_fps_time)
        if 0.0<=age<=2.5:
            paired={"t":now,"fps":float(last_fps),"gpu_load":float(load),
                    "power_w":float(power) if power is not None else None,
                    "gpu_clock_mhz":float(sclk) if sclk is not None else None}
            cur["paired_perf"].append(paired)
            live_sample={**paired,
                "edge_c":float(edge) if edge is not None else None,
                "junction_c":float(junction) if junction is not None else None}

    for key in ("fps","p1","edge","junction","temp_delta","gpu_load","power",
                "gpu_clock","memory_clock","vram_pct","paired_perf"):
        if len(cur[key])>max_samples: cur[key]=cur[key][::2]
    return live_sample


def should_finish_session(current, missing_since, grace_seconds, *, now_monotonic=None):
    if current is None or missing_since is None: return False
    now=(now_monotonic or time.monotonic)()
    return now-float(missing_since)>=float(grace_seconds)


def build_completed_record(cur, *, reason, ended_at, analyzed, encoded_raw, encoded_count,
                           analyzer_version, quality):
    def avg(values): return (sum(values)/len(values)) if values else None
    def maximum(values): return max(values) if values else None
    duration=max(0.0,float(ended_at)-float(cur.get("started_at",ended_at)))
    refresh_hz=_num(cur.get("display_refresh_hz"))
    record={
        "game":cur.get("game","Game"), "steam_appid":cur.get("steam_appid",""),
        "telemetry_identity":cur.get("telemetry_identity",""), "started_iso":cur.get("started_iso",""),
        "ended_iso":time.strftime("%Y-%m-%d %H:%M:%S",time.localtime(ended_at)),
        "duration_seconds":round(duration,1), "avg_fps":avg(cur.get("fps",[])),
        "p1_fps":avg(cur.get("p1",[])), "live_reported_p1_fps":avg(cur.get("p1",[])),
        "live_p1_sources":sorted(cur.get("p1_sources",[]) or ["unknown_live"]) if cur.get("p1",[]) else [],
        "avg_edge_c":avg(cur.get("edge",[])), "max_edge_c":maximum(cur.get("edge",[])),
        "avg_junction_c":avg(cur.get("junction",[])), "max_junction_c":maximum(cur.get("junction",[])),
        "avg_temp_delta_c":avg(cur.get("temp_delta",[])), "max_temp_delta_c":maximum(cur.get("temp_delta",[])),
        "avg_gpu_load_pct":avg(cur.get("gpu_load",[])), "max_gpu_load_pct":maximum(cur.get("gpu_load",[])),
        "avg_power_w":avg(cur.get("power",[])), "max_power_w":maximum(cur.get("power",[])),
        "avg_gpu_clock_mhz":avg(cur.get("gpu_clock",[])), "max_gpu_clock_mhz":maximum(cur.get("gpu_clock",[])),
        "avg_memory_clock_mhz":avg(cur.get("memory_clock",[])), "max_memory_clock_mhz":maximum(cur.get("memory_clock",[])),
        "avg_vram_pct":avg(cur.get("vram_pct",[])), "max_vram_pct":maximum(cur.get("vram_pct",[])),
        "gpu_profile":cur.get("gpu_profile","—"), "graphics_preset":cur.get("graphics_preset",""),
        "scaling":cur.get("scaling","—"), "render_resolution":cur.get("render_resolution"),
        "output_resolution":cur.get("output_resolution"), "power_limit_w":cur.get("power_limit_w"),
        "workload_profile":cur.get("workload_profile"),
        "telemetry_status":cur.get("telemetry_status") or ("Telemetry active" if cur.get("fps") else "Telemetry unavailable"),
        "telemetry_parser_status":cur.get("telemetry_parser_status") or "No valid FPS samples received",
        "telemetry_method":cur.get("telemetry_method") or "Unavailable", "display_refresh_hz":refresh_hz,
        "reason":reason, "started_at_epoch":cur.get("started_at"),
        "raw_paired_telemetry_encoding":"gzip+base64 compact JSON",
        "raw_paired_telemetry_samples":encoded_count, "raw_paired_telemetry_gzip_base64":encoded_raw,
    }
    record.update(analyzed or {})
    record["dip_analysis_version"]=analyzer_version
    record["quality"]=quality(record) if callable(quality) else quality
    return record
