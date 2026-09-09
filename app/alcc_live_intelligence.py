#!/usr/bin/env python3
"""Live performance-intelligence backend for AMD Linux Control Center.

This module owns the bounded, display-only workload phase classifier and live
performance interpretation. UI rendering and session persistence remain in the
main application.
"""
import time
import re

MAX_LIVE_INTELLIGENCE_SAMPLES = 240
MAX_LIVE_INTELLIGENCE_EVENTS = 5

class LiveIntelligenceMixin:
    @staticmethod
    def _new_live_intelligence_state(identity=None):
        return {"identity":identity,"samples":[],"events":[],"last_event_t":None,"suspended":True,"result":None,"phase":"unknown","phase_confidence":"Low","phase_started_t":None,"phase_reason":"Waiting for enough telemetry to identify a workload regime","phase_evidence":[],"gameplay_established":False,"transition_evidence_last_t":None,"transition_evidence_horizon":8.0,"transition_event_emitted":False,"transition_signature":None,"stable_recovery_count":0,"recovery_started_t":None,"recovery_samples":[],"pending_events":[],"abnormal_episode_started_t":None,"abnormal_episode_last_t":None,"regime_memory":[],"gameplay_signature":None,"menu_signature":None}
    def _reset_live_intelligence(self,identity=None):
        self.live_intelligence=self._new_live_intelligence_state(identity)
    @staticmethod
    def _live_median(values):
        values=sorted(float(v) for v in values if v is not None)
        if not values:return None
        middle=len(values)//2
        return values[middle] if len(values)%2 else (values[middle-1]+values[middle])/2.0
    @classmethod
    def _live_regime_signature(cls,rows):
        """Bounded, game-neutral description of a short telemetry regime."""
        rows=[r for r in list(rows)[-12:] if isinstance(r,dict) and cls._session_num(r.get("fps")) is not None]
        if not rows:return {"count":0,"duration":0.0,"stable":False,"plateau":False,"continuity":0.0}
        def values(key):return [float(r[key]) for r in rows if cls._session_num(r.get(key)) is not None]
        fps=values("fps"); times=values("t"); med=cls._live_median(fps); p10=cls._percentile(fps,0.10); p90=cls._percentile(fps,0.90)
        intervals=[b-a for a,b in zip(times,times[1:]) if b>a]; cadence=cls._live_median([v for v in intervals if v<=15.0]) or 1.0
        continuity=(sum(1 for v in intervals if v<=max(2.5,min(12.0,cadence*2.5)))/len(intervals)) if intervals else 1.0
        spread=(p90-p10)/med if med and p10 is not None and p90 is not None else 0.0
        unique_ratio=len(set(round(v,1) for v in fps))/len(fps) if fps else 1.0
        signature={"count":len(rows),"duration":max(0.0,times[-1]-times[0]) if len(times)>1 else 0.0,"fps":med,"fps_spread":spread,"continuity":continuity,"cadence":cadence}
        for key,name in (("gpu_load","load"),("power_w","power"),("gpu_clock_mhz","clock")):
            vals=values(key); signature[name]=cls._live_median(vals); signature[name+"_spread"]=(cls._percentile(vals,0.90)-cls._percentile(vals,0.10))/max(abs(signature[name] or 0),1.0) if vals else None
        signature["stable"]=bool(len(fps)>=4 and signature["duration"]>=3.0 and continuity>=0.70 and spread<=0.10)
        signature["plateau"]=bool(signature["stable"] and spread<=0.025 and unique_ratio<=0.35)
        return signature
    @staticmethod
    def _live_regime_distance(left,right):
        """Count independent relative signals that materially changed."""
        if not isinstance(left,dict) or not isinstance(right,dict):return 0,[]
        evidence=[]
        def relative(key,threshold,label):
            a=left.get(key); b=right.get(key)
            if a not in (None,0) and b is not None and abs(float(b)-float(a))/abs(float(a))>=threshold:evidence.append(label)
        relative("fps",0.16,"FPS level changed")
        a=left.get("load"); b=right.get("load")
        if a is not None and b is not None and abs(float(b)-float(a))>=15.0:evidence.append("GPU workload changed")
        relative("power",0.18,"board-power regime changed"); relative("clock",0.18,"GPU-clock regime changed")
        if abs(float(right.get("fps_spread") or 0)-float(left.get("fps_spread") or 0))>=0.08:evidence.append("pacing character changed")
        return len(evidence),evidence
    @classmethod
    def _remember_live_regime(cls,state,phase,signature,now):
        if phase not in ("gameplay","menu/background") or not signature.get("stable") or signature.get("duration",0)<5:return
        memory=state.setdefault("regime_memory",[])
        for item in reversed(memory):
            distance,_=cls._live_regime_distance(item.get("signature"),signature)
            if item.get("phase")==phase and distance<=1:
                item["hits"]=min(9,int(item.get("hits",1))+1); item["signature"]=dict(signature); item["last_t"]=now; return
        memory.append({"phase":phase,"signature":dict(signature),"hits":1,"last_t":now})
        if len(memory)>8:del memory[:-8]
    @classmethod
    def _analyze_live_intelligence(cls,samples,events=None,telemetry_active=True):
        """Conservative display-only interpretation; independent of the session analyzer."""
        rows=[r for r in samples if isinstance(r,dict) and cls._session_num(r.get("fps")) is not None and cls._session_num(r.get("gpu_load")) is not None]
        if not telemetry_active:
            return {"state":"Insufficient evidence","confidence":"Low","evidence":"Telemetry is interrupted; game identity is preserved and conclusions are suspended.","recommendation":"Wait for telemetry to recover; no graphics change is recommended from missing data.","thermal":"Thermal / power context unavailable during the telemetry gap.","events":list(events or [])}
        if not rows:
            return {"state":"Insufficient evidence","confidence":"Low","evidence":"Waiting for paired FPS and GPU telemetry.","recommendation":"No recommendation until sufficient evidence is available.","thermal":"Thermal / power: —","events":list(events or [])}
        latest=rows[-1]; latest_t=float(latest.get("t") or 0); latest_phase=str(latest.get("live_phase") or "gameplay")
        # Phase is annotation only. Every current, valid paired sample remains
        # available to limiter analysis; confirmed-transition tags still guide
        # event reconciliation but never gate the whole analysis result.
        analysis_rows=rows
        immediate=[r for r in analysis_rows if latest_t-float(r.get("t") or latest_t)<=5.0]
        short=[r for r in analysis_rows if latest_t-float(r.get("t") or latest_t)<=15.0]
        established=[r for r in analysis_rows if latest_t-float(r.get("t") or latest_t)<=60.0]
        if not established:established=analysis_rows[-1:]
        first_t=float(established[0].get("t") or latest_t); duration=max(0.0,latest_t-first_t); observed_count=len(established)
        def vals(group,key):return [float(r[key]) for r in group if cls._session_num(r.get(key)) is not None]
        stability_short=[r for r in short if str(r.get("live_phase") or "gameplay") not in ("menu","menu/background","transition","loading/transition","settling")]
        if not stability_short:stability_short=short
        fps_short=vals(stability_short,"fps"); load_short=vals(short,"gpu_load"); fps_long=vals(established,"fps")
        med=cls._live_median(fps_short); baseline=cls._live_median(fps_long); load_med=cls._live_median(load_short)
        low=cls._percentile(fps_short,0.10) if fps_short else None
        continuity=1.0
        if len(short)>1:
            times=[float(r.get("t") or 0) for r in short]; gaps=[b-a for a,b in zip(times,times[1:]) if b>=a]
            cadence=cls._live_median([gap for gap in gaps if 0<gap<=15.0]) or 1.0; continuity_horizon=max(2.5,min(12.0,cadence*2.5))
            continuity=sum(1 for gap in gaps if gap<=continuity_horizon)/len(gaps) if gaps else 1.0
        high_share=(sum(1 for v in load_short if v>=92.0)/len(load_short)) if load_short else 0.0
        headroom_share=(sum(1 for v in load_short if v<=78.0)/len(load_short)) if load_short else 0.0
        immediate_load=cls._live_median(vals(immediate,"gpu_load"))
        pause_like=bool(len(immediate)>=4 and immediate_load is not None and immediate_load<45.0 and low is not None and med and low>=med*0.93)
        instability=bool(med and low is not None and low<med*0.68 and len(fps_short)>=10)
        contradictory=high_share>=0.25 and headroom_share>=0.25
        refresh_hz=cls._session_num(latest.get("display_refresh_hz"))
        # Confirmed transition/settling tags may refine the cap evidence set,
        # while phase remains advisory and never gates the overall analysis.
        cap_rows=[r for r in established if str(r.get("live_phase") or "gameplay") not in ("transition","loading/transition","settling")]
        if len(cap_rows)<16:cap_rows=established
        cap=cls._frame_cap_analysis(cap_rows,refresh_hz=refresh_hz,min_samples=16,min_duration=12.0)
        cap_likely=cap.get("frame_cap_status")=="Frame-rate cap / synchronization likely"
        cap_possible=cap.get("frame_cap_status")=="Possible frame cap or CPU/game-engine limit"
        if observed_count<5 or duration<4.0 or continuity<0.75:
            state="Insufficient evidence"
        elif instability:
            state="Frame-time instability"
        elif cap_likely:
            state="Frame-rate cap / synchronization likely"
        elif cap_possible:
            state="Possible frame cap or CPU/game-engine limit"
        elif high_share>=0.70:
            state="GPU limited"
        elif headroom_share>=0.70:
            state="Likely CPU/game-engine limited"
        elif contradictory:
            state="Mixed / uncertain"
        elif med and low is not None and low>=med*0.80:
            state="Stable / balanced"
        else:
            state="Mixed / uncertain"
        if duration>=45 and observed_count>=40 and continuity>=0.90 and not contradictory and not pause_like:confidence="High"
        elif duration>=12 and observed_count>=10 and continuity>=0.75:confidence="Moderate"
        else:confidence="Low"
        if state=="Insufficient evidence":confidence="Low"
        elif contradictory and confidence=="High":confidence="Moderate"
        phase_uncertain=latest_phase in ("unknown","pending","menu","menu/background","transition","loading/transition","settling")
        if cap_likely:confidence=cap.get("frame_cap_confidence") or confidence
        elif cap_possible and confidence=="High":confidence="Moderate"
        if latest_phase in ("transition","loading/transition"):confidence="Low"
        elif phase_uncertain and confidence=="High":confidence="Moderate"
        evidence_parts=[f"{observed_count} paired samples / {duration:.0f}s",f"recent median {med:.0f} FPS" if med is not None else "FPS unavailable",f"median GPU load {load_med:.0f}%" if load_med is not None else "GPU load unavailable"]
        if pause_like:evidence_parts.append("stable low-work cap resembles a menu or background state")
        excluded=sum(1 for r in rows if str(r.get("live_phase") or "gameplay")!="gameplay")
        if excluded:evidence_parts.append(f"{excluded} recent transition/pending/settling sample(s) excluded from gameplay stability")
        if phase_uncertain:evidence_parts.append("phase context is advisory; recent menu/loading activity may affect this short-term analysis")
        if low is not None:evidence_parts.append(f"recent P10 {low:.0f} FPS")
        if continuity<0.9:evidence_parts.append("telemetry continuity is reduced")
        if contradictory:evidence_parts.append("GPU-load evidence conflicts")
        if cap_likely or cap_possible:evidence_parts.append(cap.get("frame_cap_evidence"))
        if state=="Frame-rate cap / synchronization likely":recommendation="FPS appears intentionally limited. Raising GPU performance or lowering graphics settings is unlikely to increase frame rate until the active frame cap/synchronization limit is changed."
        elif state=="Possible frame cap or CPU/game-engine limit":recommendation="Confirm the configured frame limit or synchronization behavior before reducing graphics quality; the stable ceiling and GPU headroom are not enough to identify the exact source."
        elif state=="GPU limited":recommendation="Lower render scale or GPU-heavy graphics settings for more FPS; recent GPU load is consistently near saturation."
        elif state=="Likely CPU/game-engine limited":recommendation="Lowering render resolution is unlikely to provide a large improvement right now; GPU headroom is consistently present."
        elif state=="Frame-time instability":recommendation="Watch for repeated hitches before changing settings; recent low-frame behavior is inconsistent."
        elif state=="Stable / balanced":recommendation="No obvious performance problem detected."
        elif state=="Mixed / uncertain":recommendation="Keep observing; current evidence is mixed, so no specific graphics change is recommended."
        else:recommendation="No recommendation until sufficient evidence is available."
        if phase_uncertain and state!="Insufficient evidence":recommendation+=" Phase identification is uncertain, so confirm under sustained gameplay before changing settings."
        edge=cls._session_num(latest.get("edge_c")); junction=cls._session_num(latest.get("junction_c")); power=cls._session_num(latest.get("power_w")); clock=cls._session_num(latest.get("gpu_clock_mhz")); delta=(junction-edge) if junction is not None and edge is not None else None
        thermal="Thermal / power: "+"   •   ".join((f"edge {edge:.0f}°C" if edge is not None else "edge —",f"junction {junction:.0f}°C" if junction is not None else "junction —",f"delta {delta:.0f}°C" if delta is not None else "delta —",f"board {power:.0f} W" if power is not None else "board —",f"clock {clock:.0f} MHz" if clock is not None else "clock —"))
        if (junction is not None and junction>=95.0) or (edge is not None and edge>=85.0):
            recommendation="Junction or edge temperature is elevated; monitor cooling behavior during a longer workload. Current temperatures alone do not identify throttling or a hardware fault."
            thermal+="   •   elevated; capability-neutral monitoring advised"
        return {"state":state,"confidence":confidence,"evidence":"   •   ".join(evidence_parts),"recommendation":recommendation,"thermal":thermal,"events":list(events or []),"frame_cap":cap}
    def _cached_active_display_refresh_hz(self):
        """Use only already-parsed KScreen active-mode data; never infer refresh from FPS."""
        displays=self.__dict__.get("display_data",[])
        candidates=[d for d in displays if isinstance(d,dict) and d.get("connected")=="Yes" and d.get("enabled","Yes")=="Yes"]
        chosen=next((d for d in candidates if d.get("primary")=="Yes"),candidates[0] if candidates else None)
        if not chosen:return None
        match=re.search(r"[0-9]+(?:\.[0-9]+)?",str(chosen.get("refresh") or ""))
        return self._session_num(match.group(0)) if match else None
    def _live_intelligence_ingest(self,identity,sample):
        state=getattr(self,"live_intelligence",None)
        if not isinstance(state,dict) or state.get("identity")!=identity:self._reset_live_intelligence(identity); state=self.live_intelligence
        row=dict(sample); row["t"]=float(row.get("t") or time.monotonic()); row["display_refresh_hz"]=self._cached_active_display_refresh_hz(); rows=state["samples"]
        previous=list(rows)
        state["suspended"]=False
        prior_gameplay=[r for r in previous[-60:] if str(r.get("live_phase") or "gameplay")=="gameplay"]
        prior_fps=[float(r["fps"]) for r in prior_gameplay if self._session_num(r.get("fps")) is not None]
        baseline=self._live_median(prior_fps)
        if state.get("phase")=="gameplay" and self._session_num((state.get("gameplay_signature") or {}).get("fps")) is not None:
            baseline=float(state["gameplay_signature"]["fps"])
        fps=self._session_num(row.get("fps")); load=self._session_num(row.get("gpu_load")); now=row["t"]
        if state.get("phase")=="unknown" and not state.get("gameplay_established"):
            candidate=previous[-11:]+[row]; signature=self._live_regime_signature(candidate)
            phase="unknown"; evidence=[f"observing new workload regime: {signature.get('count',0)} sample(s) / {signature.get('duration',0):.1f}s"]
            if signature.get("stable") and signature.get("duration",0)>=6.0:
                if signature.get("plateau"):
                    phase="menu/background"; evidence=["sustained highly stable plateau during unestablished workload","telemetry is continuous"]
                else:
                    phase="gameplay"; evidence=["sustained continuous regime with natural pacing variation","initial gameplay regime established conservatively"]
            elif signature.get("duration",0)>=5.0 and float(signature.get("fps_spread") or 0)>=0.15:
                phase="loading/transition"; evidence=["startup workload remains temporally unstable","no established gameplay regime yet"]
            row["live_phase"]=phase; rows.append(row)
            if phase!="unknown":
                state["phase"]=phase; state["phase_started_t"]=now; state["phase_confidence"]="Moderate"; state["phase_evidence"]=evidence; state["phase_reason"]="; ".join(evidence)
                for old in rows:old["live_phase"]=phase
                if phase=="gameplay":state["gameplay_signature"]=signature; state["gameplay_established"]=True; self._remember_live_regime(state,"gameplay",signature,now)
                elif phase=="menu/background":state["menu_signature"]=signature; self._remember_live_regime(state,"menu/background",signature,now)
                else:state["phase"]="transition"; state["transition_evidence_last_t"]=now; state["transition_evidence_horizon"]=8.0; state["transition_signature"]=signature; state["transition_event_emitted"]=False
            else:
                state["phase_reason"]="; ".join(evidence); state["phase_evidence"]=evidence; state["phase_confidence"]="Low"
            state["result"]=self._analyze_live_intelligence(rows,state["events"],True)
            return state["result"]
        recent=previous[-8:]
        recent_fps=[self._session_num(r.get("fps")) for r in recent]; recent_fps=[v for v in recent_fps if v is not None]
        recent_times=[self._session_num(r.get("t")) for r in recent]+[now]; recent_times=[v for v in recent_times if v is not None]
        recent_intervals=[b-a for a,b in zip(recent_times,recent_times[1:]) if 0<b-a<=12.0]
        sample_interval=self._live_median(recent_intervals) or 1.0
        continuity_gap=max(2.5,min(12.0,sample_interval*2.5))
        low_workload_now=bool(load is not None and load<45.0)
        menu_now=False
        recent_transition=any(str(r.get("live_phase") or "gameplay") in ("menu","menu/background","transition","loading/transition","settling") for r in recent)
        depressed=bool(baseline and fps is not None and fps<baseline*0.72)
        if depressed:
            last_abnormal=self._session_num(state.get("abnormal_episode_last_t"))
            if state.get("abnormal_episode_started_t") is None or (last_abnormal is not None and now-last_abnormal>max(12.0,continuity_gap*1.5)):
                state["abnormal_episode_started_t"]=now
            state["abnormal_episode_last_t"]=now
        def shifted(key):
            current=self._session_num(row.get(key)); values=[self._session_num(r.get(key)) for r in prior_gameplay[-15:]]; values=[v for v in values if v is not None]
            reference=self._live_median(values)
            return bool(current is not None and reference not in (None,0) and abs(current-reference)/abs(reference)>=0.18)
        workload_shift=shifted("power_w") or shifted("gpu_clock_mhz")
        phase=state.get("phase") or "gameplay"
        recent_signature=self._live_regime_signature(previous[-7:]+[row])
        newest_fps=fps; fresh_rows=[]
        for candidate in reversed(previous[-11:]+[row]):
            value=self._session_num(candidate.get("fps"))
            if newest_fps in (None,0) or value is None or abs(value-newest_fps)/abs(newest_fps)>0.12:break
            fresh_rows.append(candidate)
        fresh_rows.reverse(); fresh_signature=self._live_regime_signature(fresh_rows)
        reference=state.get("gameplay_signature") if phase in ("gameplay","unknown") else state.get("menu_signature")
        regime_distance,regime_evidence=self._live_regime_distance(reference,recent_signature)
        recurring_menu=False
        for remembered in state.get("regime_memory",[]):
            distance,_=self._live_regime_distance(remembered.get("signature"),recent_signature)
            if remembered.get("phase")=="menu/background" and int(remembered.get("hits",0))>=2 and distance<=1:recurring_menu=True; break
        generalized_menu=bool(recent_signature.get("stable") and recent_signature.get("duration",0)>=5.0 and recent_signature.get("plateau") and (regime_distance>=1 or recurring_menu))
        menu_now=bool(low_workload_now and recent_signature.get("stable") and recent_signature.get("plateau")) or generalized_menu
        row["live_phase"]="menu/background" if menu_now else ("pending" if depressed and phase=="gameplay" else phase)
        provisional=previous[-11:]+[row]; low_run=[]
        for candidate in reversed(provisional):
            value=self._session_num(candidate.get("fps")); stamp=self._session_num(candidate.get("t"))
            if not baseline or value is None or value>=baseline*0.72:break
            if low_run and stamp is not None and float(low_run[-1].get("t") or stamp)-stamp>continuity_gap:break
            low_run.append(candidate)
        low_run.reverse(); run_fps=[float(r["fps"]) for r in low_run if self._session_num(r.get("fps")) is not None]
        run_duration=(float(low_run[-1].get("t") or now)-float(low_run[0].get("t") or now)) if len(low_run)>=2 else 0.0
        run_median=self._live_median(run_fps); run_spread=((max(run_fps)-min(run_fps))/run_median) if run_median and len(run_fps)>=2 else 0.0
        stable_abnormal_regime=len(low_run)>=4 and run_duration>=3.0 and run_spread<=0.12
        sustained_abnormal_regime=len(low_run)>=6 and run_duration>=5.0
        contextual_transition=len(low_run)>=2 and (recent_transition or workload_shift)
        if menu_now and phase=="gameplay" and not depressed:
            state["phase"]="menu/background"; state["phase_started_t"]=now; state["phase_reason"]="Sustained plateau differs from established gameplay"; state["phase_evidence"]=["sustained stable plateau",*(regime_evidence[:2] or ["workload differs from established gameplay"] )]; state["phase_confidence"]="Moderate"; state["menu_signature"]=recent_signature; phase="menu/background"
            self._remember_live_regime(state,"menu/background",recent_signature,now)
        menu_departure=bool(phase=="menu/background" and not menu_now and recent_signature.get("count",0)>=4 and regime_distance>=1)
        stable_menu_departure=bool(menu_departure and recent_signature.get("stable") and not recent_signature.get("plateau"))
        gameplay_age=now-float(state.get("phase_started_t") or now) if state.get("phase_started_t") is not None else 999.0
        generalized_transition=bool((phase=="gameplay" and gameplay_age>=5.0 and recent_signature.get("count",0)>=4 and recent_signature.get("duration",0)>=3.0 and regime_distance>=2) or (menu_departure and not stable_menu_departure))
        transition_candidate=stable_abnormal_regime or sustained_abnormal_regime or contextual_transition or generalized_transition
        episode_start=self._session_num(state.get("abnormal_episode_started_t")); episode_duration=now-episode_start if episode_start is not None else 0.0
        episode_candidates=sum(1 for event in [*state.get("pending_events",[]),*state.get("events",[])] if event.get("gameplay_impact") is not False and episode_start is not None and float(event.get("t") or 0)>=episode_start)
        established_gameplay=bool(state.get("gameplay_established") or (phase=="gameplay" and len(prior_gameplay)>=12))
        strong_temporal_cluster=bool(episode_duration>=8.0 and episode_candidates>=2)
        independent_transition_signal=bool(workload_shift or any(item in regime_evidence for item in ("GPU workload changed","board-power regime changed","GPU-clock regime changed")))
        strong_multi_signal=bool(run_duration>=3.0 and independent_transition_signal and (stable_abnormal_regime or sustained_abnormal_regime))
        begin_transition=bool(transition_candidate and (not established_gameplay or strong_temporal_cluster or strong_multi_signal or phase=="menu/background"))
        if transition_candidate and not begin_transition and phase=="gameplay":
            state["phase"]="unknown"; state["phase_started_t"]=now; state["phase_reason"]="Possible transition lacks strong multi-signal evidence; analysis remains active"; state["phase_evidence"]=["temporary workload disturbance detected","established gameplay hysteresis prevented a loading claim"]; state["phase_confidence"]="Low"; phase="unknown"
        if generalized_transition:transition_reason="Multiple relative workload signals changed: "+", ".join(regime_evidence[:3])
        elif stable_abnormal_regime:transition_reason=f"Abrupt continuous FPS regime ({len(low_run)} samples / {run_duration:.1f}s) with stable pacing"
        elif sustained_abnormal_regime:transition_reason=f"Sustained abnormal FPS regime ({len(low_run)} samples / {run_duration:.1f}s)"
        elif workload_shift:transition_reason="Clustered FPS regime with GPU power/clock shift"
        else:transition_reason="Clustered FPS regime following recent menu/transition context"
        if begin_transition and state.get("phase") not in ("transition","settling"):
            transition_start=episode_start if episode_start is not None else (float(low_run[0].get("t") or now) if low_run else now)
            state["phase"]="transition"; state["phase_started_t"]=transition_start; state["phase_reason"]=transition_reason; state["phase_evidence"]=[transition_reason,"strong temporal/multi-signal evidence confirmed","authority requires continuing current evidence"]; state["phase_confidence"]="Moderate"; state["transition_evidence_last_t"]=now; state["transition_evidence_horizon"]=max(6.0,min(12.0,continuity_gap*3.0)); state["transition_event_emitted"]=False; state["transition_signature"]=recent_signature; state["stable_recovery_count"]=0; state["recovery_started_t"]=None; state["recovery_samples"]=[]
            for old in rows:
                if float(old.get("t") or 0)>=transition_start and str(old.get("live_phase") or "gameplay") in ("pending","gameplay"):old["live_phase"]="transition"
            state["pending_events"]=[event for event in state.get("pending_events",[]) if float(event.get("t") or 0)<transition_start]
            # A loading episode can outlive the provisional publication delay.
            # Reconcile already-visible gameplay hitches from this same bounded
            # episode once temporal evidence confirms it as a transition.
            state["events"]=[event for event in state.get("events",[]) if not (event.get("gameplay_impact") is not False and transition_start<=float(event.get("t") or 0)<=now)]
        phase=state.get("phase") or "gameplay"
        plateau_severely_depressed=bool(baseline and fresh_signature.get("fps") is not None and float(fresh_signature["fps"])<baseline*0.55)
        _,fresh_gameplay_evidence=self._live_regime_distance(state.get("gameplay_signature"),fresh_signature)
        plateau_workload_changed=any(item in fresh_gameplay_evidence for item in ("GPU workload changed","board-power regime changed","GPU-clock regime changed"))
        if phase=="transition" and fresh_signature.get("plateau") and fresh_signature.get("duration",0)>=5.0 and not plateau_severely_depressed and (plateau_workload_changed or recurring_menu):
            transition_start=float(state.get("phase_started_t") or now); state["events"]=[event for event in state.get("events",[]) if not (event.get("gameplay_impact") is False and float(event.get("t") or 0)>=transition_start)]
            state["phase"]="menu/background"; state["phase_started_t"]=float(fresh_rows[0].get("t") or now); state["phase_reason"]="Stable plateau established after workload change"; state["phase_evidence"]=["new workload is sustained and plateau-like","menu interpretation does not depend on GPU utilization"]; state["phase_confidence"]="Moderate"; state["menu_signature"]=fresh_signature; phase="menu/background"
            self._remember_live_regime(state,"menu/background",fresh_signature,now)
        if stable_menu_departure and phase=="menu/background":
            state["phase"]="settling"; state["phase_started_t"]=now; state["recovery_started_t"]=now; state["recovery_samples"]=[row]; state["phase_reason"]="New stable non-menu regime detected; confirming gameplay"; state["phase_evidence"]=["workload departed recurring/stable menu regime","new pacing is internally stable"]; state["phase_confidence"]="Low"; phase="settling"
        elif phase=="transition":
            transition_signature=state.get("transition_signature") or {}
            recovery_distance,recovery_evidence=self._live_regime_distance(transition_signature,fresh_signature)
            transition_was_unstable=not bool(transition_signature.get("stable"))
            severe_relative_depression=bool(baseline and fresh_signature.get("fps") is not None and float(fresh_signature["fps"])<baseline*0.55)
            independent_workload_change=any(item in recovery_evidence for item in ("GPU workload changed","board-power regime changed","GPU-clock regime changed"))
            continuing_transition_evidence=bool((run_duration>=3.0 and (workload_shift or regime_distance>=2 or run_spread>0.12)) or (not fresh_signature.get("stable") and recent_signature.get("duration",0)>=3.0))
            if continuing_transition_evidence:state["transition_evidence_last_t"]=now
            stable_again=bool(fresh_signature.get("stable") and (recovery_distance>=1 or transition_was_unstable) and not menu_now and (not severe_relative_depression or independent_workload_change))
            if stable_again:
                if state.get("recovery_started_t") is None:
                    state["recovery_started_t"]=float(fresh_rows[0].get("t") or now); state["recovery_samples"]=list(fresh_rows)
                elif not state.get("recovery_samples") or float(state["recovery_samples"][-1].get("t") or 0)!=now:state.setdefault("recovery_samples",[]).append(row)
                state["recovery_samples"]=state["recovery_samples"][-12:]
                state["stable_recovery_count"]=len(state["recovery_samples"]); recovery_duration=now-float(state.get("recovery_started_t") or now)
                state["phase_reason"]=f"New stable regime candidate: {state['stable_recovery_count']} sample(s) / {recovery_duration:.1f}s"
                state["phase_evidence"]=["new FPS/pacing regime is internally stable",*(recovery_evidence[:2] or ["prior loading regime no longer matches"]),"telemetry remains continuous"]
            else:
                state["stable_recovery_count"]=0; state["recovery_started_t"]=None; state["recovery_samples"]=[]; state["phase_reason"]="Transition evidence remains; no distinct stable recovery regime yet"; state["phase_evidence"]=["recent regime remains unstable or matches loading","waiting for fresh continuous evidence"]
            recovery_duration=now-float(state.get("recovery_started_t") or now) if state.get("recovery_started_t") is not None else 0.0
            if state["stable_recovery_count"]>=5 and recovery_duration>=4.0:
                state["phase"]="settling"; state["phase_started_t"]=now; state["phase_reason"]=f"Recovered pacing is stable for {recovery_duration:.1f}s; short settling guard remains"; phase="settling"
            else:phase="menu" if menu_now else "transition"
        elif phase=="settling" and fresh_signature.get("plateau") and fresh_signature.get("duration",0)>=5.0 and not plateau_severely_depressed and (plateau_workload_changed or recurring_menu):
            transition_start=float(state.get("phase_started_t") or now); state["events"]=[event for event in state.get("events",[]) if not (event.get("gameplay_impact") is False and float(event.get("t") or 0)>=transition_start)]
            state["phase"]="menu/background"; state["phase_started_t"]=float(fresh_rows[0].get("t") or now); state["phase_reason"]="Stable plateau confirmed as a menu/background regime"; state["phase_evidence"]=["plateau persisted through the settling guard","workload differs from established gameplay"]; state["phase_confidence"]="Moderate"; state["menu_signature"]=fresh_signature; phase="menu/background"
            self._remember_live_regime(state,"menu/background",fresh_signature,now)
        elif phase=="settling":
            state.setdefault("recovery_samples",[]).append(row); state["recovery_samples"]=state["recovery_samples"][-12:]
            recovery_signature=self._live_regime_signature(state["recovery_samples"]); recovery_values=[self._session_num(r.get("fps")) for r in state["recovery_samples"]]; recovery_values=[v for v in recovery_values if v is not None]
            if not recovery_signature.get("stable") and fresh_signature.get("stable"):
                state["recovery_samples"]=list(fresh_rows); state["recovery_started_t"]=float(fresh_rows[0].get("t") or now); recovery_signature=fresh_signature; recovery_values=[self._session_num(r.get("fps")) for r in fresh_rows]; recovery_values=[v for v in recovery_values if v is not None]
            pacing_stable=bool(recovery_signature.get("stable") and not menu_now)
            recovery_duration=now-float(state.get("recovery_started_t") or now)
            if pacing_stable and recovery_duration>=8.0:
                state["phase"]="gameplay"; state["phase_started_t"]=now; state["phase_reason"]=f"Gameplay re-established after {recovery_duration:.1f}s of continuous stable recovery"; state["phase_evidence"]=["fresh FPS regime is stable","GPU workload is internally consistent","no continuing transition evidence"]; state["phase_confidence"]="Moderate"; state["transition_event_emitted"]=False; state["abnormal_episode_started_t"]=None; state["abnormal_episode_last_t"]=None; state["gameplay_signature"]=recovery_signature; phase="gameplay"
                self._remember_live_regime(state,"gameplay",recovery_signature,now)
            else:
                state["phase_reason"]=f"Settling: {len(recovery_values)} stable recovery sample(s) / {recovery_duration:.1f}s; awaiting continuous pacing"; phase="settling"
        elif phase=="unknown":
            if fresh_signature.get("stable") and fresh_signature.get("duration",0)>=5.0:
                state["phase"]="gameplay"; state["phase_started_t"]=now; state["phase_reason"]="Stable telemetry restored after advisory phase uncertainty"; state["phase_evidence"]=["fresh workload is internally stable","performance analysis remained active during uncertainty"]; state["phase_confidence"]="Moderate"; state["gameplay_signature"]=fresh_signature; phase="gameplay"
            else:
                phase="unknown"; state["phase_reason"]="Possible transition remains uncertain; performance analysis is active"; state["phase_evidence"]=["evidence is insufficient for authoritative loading","established gameplay hysteresis remains active"]
        elif phase=="menu/background":
            phase="menu/background"; state["phase_reason"]="Sustained non-gameplay plateau remains stable"; state["phase_evidence"]=["pacing remains plateau-like","no distinct gameplay recovery regime yet"]
            if recent_signature.get("stable"):state["menu_signature"]=recent_signature; self._remember_live_regime(state,"menu/background",recent_signature,now)
        else:
            phase="pending" if depressed else "gameplay"
            if phase=="pending" and state.get("phase")!="pending":state["phase"]="pending"; state["phase_started_t"]=now; state["phase_reason"]="Abrupt FPS change pending temporal classification"
            elif phase=="gameplay" and state.get("phase")=="pending":state["phase"]="gameplay"; state["phase_started_t"]=now; state["phase_reason"]="Abnormal sample recovered without transition evidence"
        authority_horizon=float(state.get("transition_evidence_horizon") or 8.0); last_authority=self._session_num(state.get("transition_evidence_last_t"))
        if phase=="transition" and last_authority is not None and now-last_authority>authority_horizon:
            state["phase"]="settling"; state["phase_started_t"]=now; state["phase_reason"]="Confirmed-transition authority expired because current evidence was not renewed"; state["phase_evidence"]=["stale loading evidence no longer controls analysis","brief fail-safe settling before phase uncertainty"]; state["phase_confidence"]="Low"; phase="settling"
        elif phase=="settling" and now-float(state.get("phase_started_t") or now)>authority_horizon:
            state["phase"]="unknown"; state["phase_started_t"]=now; state["phase_reason"]="Phase remains uncertain after bounded settling; performance analysis is active"; state["phase_evidence"]=["no current strong transition evidence","unknown samples remain usable with reduced confidence"]; state["phase_confidence"]="Low"; phase="unknown"
        row["live_phase"]=phase; rows.append(row)
        if phase=="gameplay" and recent_signature.get("stable"):
            state["gameplay_signature"]=recent_signature; state["gameplay_established"]=True; state["phase_confidence"]="High" if len(prior_gameplay)>=40 else "Moderate"; state["phase_evidence"]=["established gameplay telemetry is continuous","recent workload regime is internally stable"]
            self._remember_live_regime(state,"gameplay",recent_signature,now)
        if len(rows)>MAX_LIVE_INTELLIGENCE_SAMPLES:del rows[:-MAX_LIVE_INTELLIGENCE_SAMPLES]
        pending=state.setdefault("pending_events",[])
        if baseline and len(prior_fps)>=8 and fps is not None and fps<baseline*0.55 and phase=="pending":
            if load is not None and load>=92:kind="GPU-saturated hitch"
            elif load is not None and load<35 and fps<baseline*0.30:kind="Loading/transition"
            elif load is not None and load<=78:kind="GPU-headroom/engine hitch"
            else:kind="Uncertain event"
            pending.append({"t":now,"clock":time.strftime("%H:%M:%S",time.localtime()),"kind":kind,"fps":fps,"gameplay_impact":kind!="Loading/transition"})
        if phase in ("transition","settling"):
            transition_pending=[event for event in pending if now-float(event.get("t") or now)<=12.0]
            pending[:]=[event for event in pending if event not in transition_pending]
            if (transition_pending or depressed) and not state.get("transition_event_emitted"):
                event_fps=min([float(event.get("fps")) for event in transition_pending if event.get("fps") is not None]+([fps] if fps is not None else []))
                state["events"].append({"t":now,"clock":time.strftime("%H:%M:%S",time.localtime()),"kind":"Loading/transition","fps":event_fps,"gameplay_impact":False}); state["transition_event_emitted"]=True
        resolved=[event for event in pending if now-float(event.get("t") or now)>=3.0]
        pending[:]=[event for event in pending if event not in resolved][-12:]
        for event in resolved:
            last_event=state.get("last_event_t")
            if last_event is None or float(event.get("t") or now)-float(last_event)>=3.0:
                state["events"].append(event); state["last_event_t"]=float(event.get("t") or now)
            for old in rows:
                if old.get("live_phase")=="pending" and float(old.get("t") or 0)<=float(event.get("t") or 0):old["live_phase"]="gameplay"
        # Mild provisional samples may not create an event. Once their temporal
        # classification window expires without transition evidence, restore
        # them to gameplay so they are not indefinitely excluded from live P1.
        last_abnormal=self._session_num(state.get("abnormal_episode_last_t"))
        episode_closed=bool(not depressed and last_abnormal is not None and now-last_abnormal>12.0 and state.get("phase")=="gameplay")
        if episode_closed:
            for old in rows:
                if old.get("live_phase")=="pending":old["live_phase"]="gameplay"
            state["abnormal_episode_started_t"]=None; state["abnormal_episode_last_t"]=None
        if len(state["events"])>MAX_LIVE_INTELLIGENCE_EVENTS:del state["events"][:-MAX_LIVE_INTELLIGENCE_EVENTS]
        state["result"]=self._analyze_live_intelligence(rows,state["events"],True)
        return state["result"]
    def _suspend_live_intelligence(self,identity=None):
        state=getattr(self,"live_intelligence",None)
        if not isinstance(state,dict) or (identity is not None and state.get("identity")!=identity):self._reset_live_intelligence(identity); state=self.live_intelligence
        if state.get("phase")=="pending":
            state["pending_events"]=[]
            for row in state.get("samples",[]):
                if row.get("live_phase")=="pending":row["live_phase"]="gameplay"
            state["phase"]="gameplay"; state["phase_started_t"]=None; state["phase_reason"]="Telemetry interrupted before provisional event classification"
        state["suspended"]=True; state["result"]=self._analyze_live_intelligence(state["samples"],state["events"],False)
