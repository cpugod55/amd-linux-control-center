"""Pure Session Trends/history data preparation helpers.

No Tk widgets, process control, filesystem writes, or GPU access live here.
"""

import time

from alcc_session_analysis import (
    canonical_session_p1,
    game_session_quality,
    game_session_setup_key,
    session_num,
    format_session_duration,
)
from alcc_session_reports import format_session_metric


def trend_timestamp(rec, fallback=0):
    value=session_num(rec.get("started_at_epoch") if isinstance(rec,dict) else None)
    if value is not None:
        return value
    text=str(rec.get("ended_iso") or rec.get("started_iso") or "") if isinstance(rec,dict) else ""
    for fmt in ("%Y-%m-%d %H:%M:%S","%Y-%m-%dT%H:%M:%S"):
        try:
            return time.mktime(time.strptime(text[:19],fmt))
        except Exception:
            pass
    return float(fallback)


def trend_game_matches(rec, reference):
    if not isinstance(rec,dict) or not isinstance(reference,dict):
        return False
    aid=str(rec.get("steam_appid") or "").strip()
    bid=str(reference.get("steam_appid") or "").strip()
    if aid and aid!="0" and bid and bid!="0":
        return aid==bid
    return str(rec.get("game") or "Game").strip().casefold()==str(reference.get("game") or "Game").strip().casefold()


def trend_point(index, rec):
    def first(*keys):
        for key in keys:
            value=session_num(rec.get(key))
            if value is not None:
                return value
        return None
    avg=first("gameplay_avg_fps","raw_sampled_avg_fps","avg_fps")
    p1=canonical_session_p1(rec)
    power=first("avg_power_w")
    efficiency=avg/power if avg is not None and power is not None and power>0 else None
    consistency=max(0.0,min(100.0,p1/avg*100.0)) if avg is not None and avg>0 and p1 is not None and p1>=0 else None
    date=str(rec.get("ended_iso") or rec.get("started_iso") or "Unavailable")
    tooltip=f"{date} • {format_session_duration(rec.get('duration_seconds'))} • Avg {format_session_metric(avg,' FPS')} • P1 {format_session_metric(p1,' FPS')} • {rec.get('scaling') or '—'} • {rec.get('gpu_profile') or '—'}"
    return {
        "history_index":index,"record":rec,"timestamp":trend_timestamp(rec,index),
        "gameplay_avg":avg,"gameplay_p1":p1,"consistency_pct":consistency,
        "avg_junction":first("avg_junction_c"),"max_junction":first("max_junction_c"),
        "avg_power":power,"avg_gpu_load":first("avg_gpu_load_pct"),
        "avg_gpu_clock":first("avg_gpu_clock_mhz"),"fps_per_watt":efficiency,"tooltip":tooltip,
    }


def trend_sessions(sessions, reference_index=None, comparable_only=False):
    indexed=[(i,r) for i,r in enumerate(sessions if isinstance(sessions,list) else []) if isinstance(r,dict)]
    reference=None
    if reference_index is not None:
        try:
            reference=sessions[reference_index]
        except Exception:
            reference=None
    included=[]
    reasons={"different game":0,"non-Gameplay quality":0,"different graphics/scaling/GPU profile":0}
    for index,rec in indexed:
        if reference is not None and not trend_game_matches(rec,reference):
            reasons["different game"]+=1
            continue
        if comparable_only and game_session_quality(rec)!="Gameplay":
            reasons["non-Gameplay quality"]+=1
            continue
        if comparable_only and reference is not None and game_session_setup_key(rec)!=game_session_setup_key(reference):
            reasons["different graphics/scaling/GPU profile"]+=1
            continue
        included.append(trend_point(index,rec))
    included.sort(key=lambda p:(p["timestamp"],p["history_index"]))
    return included,reasons


def trend_neighbor_index(points,current,step):
    indexes=[p.get("history_index") for p in points]
    if not indexes:
        return None
    try:
        position=indexes.index(current)
    except ValueError:
        return indexes[-1] if step<0 else indexes[0]
    target=position+(-1 if step<0 else 1)
    return indexes[target] if 0<=target<len(indexes) else None


def trend_baseline(points, selected_index):
    others=[p for p in points if p.get("history_index")!=selected_index]
    if len(others)<2:
        return None
    keys=("gameplay_avg","gameplay_p1","consistency_pct","avg_junction","avg_power","fps_per_watt")
    result={}
    for key in keys:
        values=[p[key] for p in others if p.get(key) is not None]
        result[key]=sum(values)/len(values) if len(values)>=2 else None
    candidates=[p for p in others if p.get("gameplay_avg") is not None and result.get("gameplay_avg") is not None]
    result["representative_history_index"]=min(candidates,key=lambda p:abs(p["gameplay_avg"]-result["gameplay_avg"]))["history_index"] if candidates else None
    result["sessions"]=len(others)
    return result


def trend_change_text(point, baseline):
    if not baseline:
        return "Comparable baseline unavailable: at least two other comparable sessions are required."
    rows=[]
    specs=(("Gameplay FPS","gameplay_avg"," FPS"," FPS",True),("Gameplay P1","gameplay_p1"," FPS"," FPS",True),("Consistency","consistency_pct","%"," pp",True),("Junction","avg_junction","°C","°C",False),("Board power","avg_power"," W"," W",True),("FPS/W","fps_per_watt"," FPS/W"," FPS/W",True))
    for label,key,value_suffix,delta_suffix,percent in specs:
        value=point.get(key); base=baseline.get(key)
        if value is None or base is None:
            rows.append(f"{label}: unavailable")
            continue
        delta=value-base
        change=f"{delta:+.1f}{delta_suffix}"
        if percent and base!=0:
            change+=f" / {delta/base*100:+.1f}%"
        rows.append(f"{label}: {value:.1f}{value_suffix} ({change} vs {baseline['sessions']}-session baseline)")
    return "Selected vs comparable baseline:\n"+"    ".join(rows)


def trend_baseline_cell_data(point, baseline):
    specs=(("gameplay_avg"," FPS"," FPS",True),("gameplay_p1"," FPS"," FPS",True),("consistency_pct","%"," pp",True),("avg_junction","°C","°C",False),("avg_power"," W"," W",True),("fps_per_watt"," FPS/W"," FPS/W",True))
    result={}
    for key,value_suffix,delta_suffix,with_percent in specs:
        value=point.get(key); base=baseline.get(key) if baseline else None
        value_text="Unavailable" if value is None else f"{value:.1f}{value_suffix}"
        if value is None or base is None:
            change="Baseline unavailable"
        else:
            delta=value-base
            change=f"{delta:+.1f}{delta_suffix}"
            if with_percent and base!=0:
                change+=f" / {delta/base*100:+.1f}%"
        result[key]=(value_text,change)
    return result


def trend_summary_text(points, allow_baseline=True):
    def values(key):
        return [p[key] for p in points if p.get(key) is not None]
    def avg(key,suffix):
        vals=values(key)
        return format_session_metric(sum(vals)/len(vals),suffix) if vals else "Unavailable"
    fps=values("gameplay_avg")
    dates=[p["record"].get("ended_iso") or p["record"].get("started_iso") for p in points if p["record"].get("ended_iso") or p["record"].get("started_iso")]
    span=f"{dates[0]} → {dates[-1]}" if dates else "Unavailable"
    baseline="Recent baseline change: insufficient comparable sessions"
    if allow_baseline and len(fps)>=4:
        recent=fps[-1]; prior=fps[-4:-1]; mean=sum(prior)/len(prior)
        baseline=f"Recent baseline change: {recent-mean:+.1f} FPS versus prior 3-session mean" if mean else baseline
    elif not allow_baseline:
        baseline="Recent baseline change: unavailable while incompatible configurations are included"
    return (f"Sessions: {len(points)}    Time span: {span}\nAverage Gameplay FPS: {avg('gameplay_avg',' FPS')}    Average Gameplay P1: {avg('gameplay_p1',' FPS')}\nAverage junction: {avg('avg_junction','°C')}    Average board power: {avg('avg_power',' W')}    Average GPU load: {avg('avg_gpu_load','%')}\nBest Gameplay FPS: {format_session_metric(max(fps),' FPS') if fps else 'Unavailable'}    Worst Gameplay FPS: {format_session_metric(min(fps),' FPS') if fps else 'Unavailable'}\nAverage GPU clock: {avg('avg_gpu_clock',' MHz')}    Average FPS/W: {avg('fps_per_watt',' FPS/W')}\n{baseline}\nFPS/W is a comparative session metric, not a universal GPU-efficiency benchmark.")


def trend_comparison_pair(points, selected_index, mode):
    selected=next((p for p in points if p.get("history_index")==selected_index),None)
    if selected is None:
        return None
    if mode=="previous":
        other_index=trend_neighbor_index(points,selected_index,-1)
    elif mode=="baseline":
        baseline=trend_baseline(points,selected_index)
        other_index=baseline.get("representative_history_index") if baseline else None
    else:
        other_index=None
    other=next((p for p in points if p.get("history_index")==other_index),None)
    if other is None:
        return None
    return (other,selected) if other["timestamp"]<=selected["timestamp"] else (selected,other)
