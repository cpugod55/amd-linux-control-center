"""Offline Analysis Lab backend for AMD Linux Control Center.

Pure/replay-oriented analyzer, telemetry codec, frame-cap evidence, and simulator
helpers.  No Tk widgets, persistence writes, GPU controls, or launch behavior live
here.  The App class supplies the shared session-analysis primitives used by the
mixin.
"""

import base64
import gzip
import json
import math
import time

ANALYZER_VERSION = "0.81.1"
SESSION_SCHEMA_VERSION = 3
MAX_RAW_PAIRED_SAMPLES = 6000
MAX_SIMULATION_DURATION_SECONDS = 21600.0
MAX_SIMULATION_SAMPLES = 30000


class AnalysisLabEngineMixin:
    def _analyze_raw_session(self,raw,started_at=None,fps_fallback=None,refresh_hz=None):
        """Single entry point shared by live completion, replay, and self-tests."""
        clean=[]
        for source_index,item in enumerate(raw if isinstance(raw,list) else []):
            if not isinstance(item,dict):continue
            fps=self._session_num(item.get("fps")); load=self._session_num(item.get("gpu_load"))
            if fps is None or load is None or not (0<=fps<2000):continue
            sample_t=self._session_num(item.get("t"))
            clean.append({"t":sample_t if sample_t is not None else float(source_index),"fps":fps,"gpu_load":load,
                          "power_w":self._session_num(item.get("power_w")),
                          "gpu_clock_mhz":self._session_num(item.get("gpu_clock_mhz"))})
        cur={"paired_perf":clean,"fps":list(fps_fallback or []),"started_at":started_at or time.time()}
        fps_metrics=self._session_gameplay_fps_metrics(cur)
        result={
            "raw_sampled_avg_fps":fps_metrics.get("raw_avg"),"raw_sampled_p1_fps":fps_metrics.get("raw_p1"),
            "gameplay_avg_fps":fps_metrics.get("gameplay_avg"),"gameplay_p1_fps":fps_metrics.get("gameplay_p1"),
            "likely_menu_seconds":fps_metrics.get("likely_menu_seconds"),"likely_menu_samples":fps_metrics.get("likely_menu_samples"),
            "paired_perf_samples":fps_metrics.get("raw_samples"),
        }
        result.update(self._session_frame_dip_metrics(cur))
        marked,_=self._detect_likely_capped_menu_samples(clean)
        transition_marked=self._cap_transition_sample_indexes(clean,marked)
        result.update(self._frame_cap_analysis(clean,marked|transition_marked,refresh_hz=refresh_hz))
        result["frame_cap_excluded_transition_samples"]=len(transition_marked-marked)
        intervals=[]; start=None
        for i,flag in enumerate([i in marked for i in range(len(clean))]+[False]):
            if flag and start is None:start=i
            elif not flag and start is not None:
                chunk=clean[start:i]
                intervals.append({"start_offset_seconds":chunk[0].get("t"),"end_offset_seconds":chunk[-1].get("t"),"samples":len(chunk),"average_fps":sum(r["fps"] for r in chunk)/len(chunk)})
                start=None
        if clean and self._session_num(clean[0].get("t")) is not None:
            base=float(clean[0]["t"])
            for interval in intervals:
                interval["start_offset_seconds"]-=base; interval["end_offset_seconds"]-=base
        result["menu_cap_intervals"]=intervals
        result["analyzer_version"]=ANALYZER_VERSION
        result["schema_version"]=SESSION_SCHEMA_VERSION
        return result

    @classmethod
    def _cap_transition_sample_indexes(cls,paired,menu_indexes=None):
        """Identify transition evidence solely for the cap-evidence denominator.

        Frame-dip reporting and Gameplay FPS/P1 remain untouched.  Severe
        low-workload events are retained here, as are sustained, internally
        stable workload regimes that are materially distinct from the session's
        dominant FPS plateau.  Short ordinary variation and gameplay hitches are
        deliberately not expanded into transition episodes.
        """
        menu=set(menu_indexes or ()); valid=[]
        for index,row in enumerate(paired or []):
            if index in menu or not isinstance(row,dict):continue
            fps=cls._session_num(row.get("fps")); load=cls._session_num(row.get("gpu_load"))
            if fps is None or load is None or not (0<=fps<2000):continue
            valid.append((index,{"fps":fps,"gpu_load":load,"power_w":cls._session_num(row.get("power_w")),"gpu_clock_mhz":cls._session_num(row.get("gpu_clock_mhz"))}))
        if len(valid)<24:return set()
        fps_values=[row["fps"] for _,row in valid]; plateau=cls._percentile(fps_values,.50)
        if not plateau:return set()
        severe=max(1.0,plateau*.70); distinct=max(3.0,plateau*.09)
        def low_work(row):
            signals=int(row["gpu_load"]<=25.0)
            if row["power_w"] is not None:signals+=int(row["power_w"]<=70.0)
            if row["gpu_clock_mhz"] is not None:signals+=int(row["gpu_clock_mhz"]<=700.0)
            return signals>=2
        candidate=[abs(row["fps"]-plateau)>=distinct and low_work(row) for _,row in valid]
        marked=set()
        start=None
        for pos,flag in enumerate(candidate+[False]):
            if flag and start is None:start=pos
            elif not flag and start is not None:
                chunk=valid[start:pos]; values=[row["fps"] for _,row in chunk]
                center=cls._percentile(values,.50); p10=cls._percentile(values,.10); p90=cls._percentile(values,.90)
                stable_regime=bool(len(chunk)>=8 and center and (p90-p10)<=max(3.0,center*.08))
                severe_event=bool(any(row["fps"]<=severe for _,row in chunk))
                at_boundary=start<=2 or pos>=len(valid)-2
                if stable_regime or (severe_event and (len(chunk)>=2 or at_boundary)):
                    marked.update(index for index,_ in chunk)
                start=None
        # Preserve isolated transition candidates already distinguished by the
        # existing multi-sensor dip semantics without widening around them.
        for pos,(index,row) in enumerate(valid):
            if row["fps"]<=severe and low_work(row):
                marked.add(index)
        return marked

    @classmethod
    def _frame_cap_analysis(cls,paired,excluded_indexes=None,refresh_hz=None,min_samples=24,min_duration=18.0):
        """Derive gameplay ceiling evidence without reclassifying it as menu time."""
        excluded=set(excluded_indexes or ())
        rows=[]
        for index,row in enumerate(paired or []):
            if index in excluded or not isinstance(row,dict):continue
            fps=cls._session_num(row.get("fps")); load=cls._session_num(row.get("gpu_load"))
            if fps is None or load is None or not (0<fps<2000):continue
            rows.append({"t":cls._session_num(row.get("t")),"fps":fps,"gpu_load":load,"power_w":cls._session_num(row.get("power_w")),"gpu_clock_mhz":cls._session_num(row.get("gpu_clock_mhz"))})
        empty={"frame_cap_status":"Insufficient evidence","frame_cap_confidence":"Low","frame_cap_plateau_fps":None,"frame_cap_occupancy_pct":None,"frame_cap_dispersion_pct":None,"frame_cap_duration_seconds":0.0,"frame_cap_samples":len(rows),"frame_cap_continuity_pct":None,"frame_cap_avg_gpu_load_pct":None,"frame_cap_avg_power_w":None,"frame_cap_avg_gpu_clock_mhz":None,"frame_cap_refresh_hz":None,"frame_cap_refresh_proximity_pct":None,"frame_cap_evidence":"Not enough continuous gameplay telemetry for cap analysis"}
        if len(rows)<min_samples:return empty
        times=[r["t"] for r in rows if r["t"] is not None]
        duration=max(0.0,times[-1]-times[0]) if len(times)>=2 else float(len(rows)-1)
        if duration<min_duration:return dict(empty,frame_cap_duration_seconds=duration)
        gaps=[b-a for a,b in zip(times,times[1:]) if b>a]
        cadence=cls._percentile(gaps,0.50) if gaps else 1.0
        continuity=(sum(gap<=max(2.5,float(cadence or 1.0)*2.5) for gap in gaps)/len(gaps)) if gaps else 1.0
        fps=[r["fps"] for r in rows]; plateau=cls._percentile(fps,0.50)
        # A relative plateau band tolerates ordinary sampling/pacing variation;
        # cap strength still additionally requires low robust dispersion,
        # sustained occupancy, continuity, and rendering headroom.
        tolerance=max(1.5,float(plateau or 0)*0.07)
        plateau_rows=[r for r in rows if abs(r["fps"]-plateau)<=tolerance]
        occupancy=len(plateau_rows)/len(rows)
        p10=cls._percentile(fps,0.10); p90=cls._percentile(fps,0.90)
        dispersion=((p90-p10)/(2.0*plateau)) if plateau and p10 is not None and p90 is not None else None
        loads=[r["gpu_load"] for r in rows]; plateau_loads=[r["gpu_load"] for r in plateau_rows]
        headroom_share=sum(v<=80.0 for v in loads)/len(loads); saturation_share=sum(v>=95.0 for v in loads)/len(loads)
        avg_load=sum(plateau_loads)/len(plateau_loads) if plateau_loads else None
        def average(key):
            values=[r[key] for r in plateau_rows if r[key] is not None]
            return sum(values)/len(values) if values else None
        avg_power=average("power_w"); avg_clock=average("gpu_clock_mhz")
        refresh=cls._session_num(refresh_hz); proximity=(abs(plateau-refresh)/refresh) if refresh and refresh>0 and plateau else None
        score=0
        if occupancy>=0.68:score+=1
        if dispersion is not None and dispersion<=0.08:score+=1
        if duration>=45 and len(rows)>=40:score+=1
        if headroom_share>=0.70:score+=2
        if saturation_share<=0.12:score+=1
        if continuity>=0.90:score+=1
        refresh_close=bool(proximity is not None and proximity<=0.02)
        if refresh_close:score+=1
        strong=bool(score>=6 and occupancy>=0.68 and dispersion is not None and dispersion<=0.10 and headroom_share>=0.65 and saturation_share<0.30 and continuity>=0.80)
        possible=bool(not strong and score>=4 and occupancy>=0.55 and dispersion is not None and dispersion<=0.14 and headroom_share>=0.55 and saturation_share<0.45 and continuity>=0.70)
        if strong:status="Frame-rate cap / synchronization likely"
        elif possible:status="Possible frame cap or CPU/game-engine limit"
        else:status="No strong frame-cap evidence"
        confidence=("High" if strong and score>=7 and duration>=45 else "Moderate" if strong or possible else "Low")
        if continuity<0.90 and confidence=="High":confidence="Moderate"
        evidence=[f"~{plateau:.1f} FPS plateau",f"{occupancy*100:.0f}% occupancy within a relative plateau band",f"{(dispersion or 0)*100:.1f}% robust dispersion",f"{duration:.0f}s / {len(rows)} eligible gameplay samples",f"{avg_load:.1f}% average GPU load during the plateau" if avg_load is not None else "plateau GPU load unavailable"]
        if avg_power is not None:evidence.append(f"{avg_power:.1f} W average plateau board power")
        if avg_clock is not None:evidence.append(f"{avg_clock:.0f} MHz average plateau GPU clock")
        if refresh_close:evidence.append(f"plateau is within {proximity*100:.1f}% of independently reported {refresh:.2f} Hz refresh")
        elif refresh is not None:evidence.append(f"independently reported refresh is {refresh:.2f} Hz; no close match is claimed")
        if continuity<0.90:evidence.append(f"telemetry continuity reduced to {continuity*100:.0f}%")
        return {"frame_cap_status":status,"frame_cap_confidence":confidence,"frame_cap_plateau_fps":plateau,"frame_cap_occupancy_pct":occupancy*100.0,"frame_cap_dispersion_pct":dispersion*100.0 if dispersion is not None else None,"frame_cap_duration_seconds":duration,"frame_cap_samples":len(rows),"frame_cap_continuity_pct":continuity*100.0,"frame_cap_avg_gpu_load_pct":avg_load,"frame_cap_avg_power_w":avg_power,"frame_cap_avg_gpu_clock_mhz":avg_clock,"frame_cap_refresh_hz":refresh,"frame_cap_refresh_proximity_pct":proximity*100.0 if proximity is not None else None,"frame_cap_evidence":"; ".join(evidence)}

    @staticmethod
    def _encode_raw_telemetry(raw):
        """Return a bounded, compressed JSON payload using only the stdlib."""
        rows=list(raw if isinstance(raw,list) else [])[-MAX_RAW_PAIRED_SAMPLES:]
        packed=json.dumps(rows,separators=(",",":"),allow_nan=False).encode("utf-8")
        return base64.b64encode(gzip.compress(packed,compresslevel=6,mtime=0)).decode("ascii"),len(rows)

    @staticmethod
    def _stored_raw_telemetry(rec):
        """Decode v0.80 compressed telemetry or accept early/legacy list storage."""
        if not isinstance(rec,dict):return []
        legacy=rec.get("raw_paired_telemetry")
        if isinstance(legacy,list):return legacy[-MAX_RAW_PAIRED_SAMPLES:]
        encoded=rec.get("raw_paired_telemetry_gzip_base64")
        if not isinstance(encoded,str) or not encoded:return []
        try:
            rows=json.loads(gzip.decompress(base64.b64decode(encoded,validate=True)).decode("utf-8"))
            return rows[-MAX_RAW_PAIRED_SAMPLES:] if isinstance(rows,list) else []
        except Exception:
            return []

    @staticmethod
    def _telemetry_simulator_presets():
        base={"duration":120,"interval":1,"baseline_fps":90,"baseline_load":98,"baseline_power":220,"baseline_clock":2200,
              "event_enabled":False,"event_start":30,"event_duration":1,"event_fps":10,"event_load":99,"event_power":225,"event_clock":2200,"repeat_count":1,"repeat_interval":30,
              "menu_enabled":False,"menu_start":45,"menu_duration":12,"menu_fps":60,"menu_load":55,"menu_power":105,"menu_clock":1200,
              "stall_enabled":False,"stall_offset":60,"stall_fps":0,"stall_load":99,"stall_power":225,"stall_clock":2200}
        def preset(**changes):
            result=dict(base); result.update(changes); return result
        return {
            "Smooth 90 FPS":preset(),
            "GPU-saturated hitch":preset(event_enabled=True),
            "GPU-headroom hitch":preset(event_enabled=True,event_load=55,event_power=105,event_clock=1200),
            "Transition/loading pause":preset(event_enabled=True,event_duration=3,event_fps=8,event_load=8,event_power=35,event_clock=300),
            "60 FPS menu/cap":preset(menu_enabled=True),
            "Full stall":preset(stall_enabled=True),
            "Rare dips in long session":preset(duration=3300,event_enabled=True,event_start=1090,event_duration=2,event_fps=18,repeat_count=3,repeat_interval=1100),
        }

    @classmethod
    def _generate_simulated_telemetry(cls,config):
        """Generate deterministic paired telemetry; analysis remains external/shared."""
        if not isinstance(config,dict):raise ValueError("configuration must be a mapping")
        def number(key,minimum=None,maximum=None):
            value=cls._session_num(config.get(key))
            if value is None:raise ValueError(f"{key} must be a finite number")
            if minimum is not None and value<minimum:raise ValueError(f"{key} must be at least {minimum}")
            if maximum is not None and value>maximum:raise ValueError(f"{key} must be at most {maximum}")
            return value
        def enabled(key):
            value=config.get(key,False)
            return value if isinstance(value,bool) else str(value).strip().lower() in ("1","true","yes","on")
        def telemetry(prefix):
            return {"fps":number(prefix+"fps",0,1999),"gpu_load":number(prefix+"load",0,100),
                    "power_w":number(prefix+"power",0),"gpu_clock_mhz":number(prefix+"clock",0)}
        duration=number("duration",0.01,MAX_SIMULATION_DURATION_SECONDS)
        interval=number("interval",0.001,duration)
        count=int(math.ceil(duration/interval))
        if count<1 or count>MAX_SIMULATION_SAMPLES:raise ValueError(f"simulation would create {count:,} samples; maximum is {MAX_SIMULATION_SAMPLES:,}")
        baseline=telemetry("baseline_")
        rows=[{"t":i*interval,**baseline} for i in range(count)]
        event_ranges=[]
        if enabled("event_enabled"):
            start=number("event_start",0,duration-0.000001); event_duration=number("event_duration",0.000001,duration)
            repeat_raw=number("repeat_count",1,1000); repeats=int(repeat_raw)
            if repeats!=repeat_raw:raise ValueError("repeat_count must be a whole number")
            repeat_interval=number("repeat_interval",0.000001,duration) if repeats>1 else number("repeat_interval",0)
            values=telemetry("event_")
            for repeat in range(repeats):
                event_start=start+repeat*repeat_interval
                if event_start>=duration:raise ValueError(f"repeated event {repeat+1} starts after the session ends")
                event_ranges.append((event_start,min(duration,event_start+event_duration)))
                for row in rows:
                    if event_start<=row["t"]<event_start+event_duration:row.update(values)
        menu_range=None
        if enabled("menu_enabled"):
            start=number("menu_start",0,duration-0.000001); menu_duration=number("menu_duration",0.000001,duration)
            values=telemetry("menu_"); menu_range=(start,min(duration,start+menu_duration))
            for row in rows:
                if start<=row["t"]<start+menu_duration:row.update(values)
        stall_index=None
        if enabled("stall_enabled"):
            offset=number("stall_offset",0,duration-0.000001); values=telemetry("stall_")
            stall_index=min(count-1,max(0,int(round(offset/interval))))
            rows[stall_index].update(values)
        return rows,{"duration":duration,"interval":interval,"sample_count":count,"event_ranges":event_ranges,
                     "menu_range":menu_range,"stall_index":stall_index,"stall_actual_offset":rows[stall_index]["t"] if stall_index is not None else None}

