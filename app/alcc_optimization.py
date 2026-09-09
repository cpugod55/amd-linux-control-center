"""Optimization Insights and Guided Optimization Trial backend helpers.

This mixin contains configuration grouping/ranking, candidate validation,
trial evidence aggregation, stopping decisions, and report preparation.
It deliberately contains no Tk widget construction, GPU writes, game launch,
or persistence orchestration. The App class supplies shared session/trend helpers.
"""

import hashlib
import json
import math
import re


class OptimizationEngineMixin:
    @staticmethod
    def _optimization_unknown(value):
        text=str(value).strip() if value is not None else ""
        return text if text and text not in ("—","-") else "Unknown"
    @classmethod
    def _optimization_game_identity(cls,rec):
        appid=str(rec.get("steam_appid") or "").strip() if isinstance(rec,dict) else ""
        if appid and appid!="0":return ("appid",appid)
        return ("name",str(rec.get("game") or "Unknown game").strip().casefold())
    @staticmethod
    def _optimization_resolution(value):
        text=str(value or "").strip()
        match=re.fullmatch(r"(\d{3,5})\s*[x×]\s*(\d{3,5})",text,re.I)
        return f"{match.group(1)}×{match.group(2)}" if match else "Unknown"
    @classmethod
    def _optimization_fingerprint(cls,rec):
        """Immutable observed setup identity; absent legacy fields stay explicitly unknown."""
        def value(*keys):
            for key in keys:
                if key in rec and rec.get(key) not in (None,""):return cls._optimization_unknown(rec.get(key))
            return "Unknown"
        scaling=value("scaling_mode","scaling")
        match=re.search(r"(\d{3,5}\s*[x×]\s*\d{3,5})\s*(?:→|->)\s*(\d{3,5}\s*[x×]\s*\d{3,5})",scaling,re.I)
        parsed_render=cls._optimization_resolution(match.group(1)) if match else "Unknown"; parsed_output=cls._optimization_resolution(match.group(2)) if match else "Unknown"
        render_res=cls._optimization_resolution(value("render_resolution","render_size","game_resolution")); output_res=cls._optimization_resolution(value("output_resolution","output_size"))
        if render_res=="Unknown":render_res=parsed_render
        if output_res=="Unknown":output_res=parsed_output
        return (cls._optimization_game_identity(rec),value("graphics_preset"),scaling,render_res,output_res,value("gpu_profile"))
    @classmethod
    def _optimization_fingerprint_text(cls,fingerprint):
        _,preset,scaling,render_res,output_res,profile=fingerprint
        resolution=(f"{render_res} → {output_res}" if render_res!="Unknown" or output_res!="Unknown" else "Unknown")
        return f"Graphics: {preset} • Scaling: {scaling} • Resolution: {resolution} • GPU profile: {profile}"
    @classmethod
    def _optimization_compact_label(cls,fingerprint,prefix=None):
        _,preset,scaling,render_res,output_res,profile=fingerprint
        scaling_short=re.sub(r"\s*[•|]\s*\d{3,5}\s*[x×]\s*\d{3,5}\s*(?:→|->)\s*\d{3,5}\s*[x×]\s*\d{3,5}.*$","",scaling).strip()
        scaling_short=re.sub(r"\((\d+(?:\.\d+)?)%\)",r"\1%",scaling_short)
        profile_short=re.sub(r"(?i)^adaptive\s*:\s*maximum\s+performance$","Adaptive Max Performance",profile).strip()
        resolution=f"{render_res}→{output_res}" if render_res!="Unknown" and output_res!="Unknown" else ""
        parts=[part for part in (prefix,preset if preset!="Unknown" else None,scaling_short if scaling_short!="Unknown" else None,resolution or None,profile_short if profile_short!="Unknown" else None) if part]
        return " • ".join(parts) if parts else (prefix or "Legacy session • configuration not recorded")
    @classmethod
    def _optimization_groups(cls,sessions,reference=None):
        indexed=[(i,r) for i,r in enumerate(sessions if isinstance(sessions,list) else []) if isinstance(r,dict)]
        if reference is None and indexed:reference=max(indexed,key=lambda pair:(cls._trend_timestamp(pair[1],pair[0]),pair[0]))[1]
        groups={}
        for index,rec in indexed:
            if reference is not None and not cls._trend_game_matches(rec,reference):continue
            if cls._game_session_quality(rec)!="Gameplay":continue
            fingerprint=cls._optimization_fingerprint(rec)
            groups.setdefault(fingerprint,[]).append((index,rec))
        result=[]
        for fingerprint,rows in groups.items():result.append(cls._optimization_aggregate(fingerprint,rows))
        result.sort(key=lambda group:(-group["newest_timestamp"],group["label"]))
        return result
    @classmethod
    def _optimization_aggregate(cls,fingerprint,rows):
        rows=sorted(rows,key=lambda pair:(cls._trend_timestamp(pair[1],pair[0]),pair[0]))
        points=[cls._trend_point(index,rec) for index,rec in rows]
        def vals(key):return [p[key] for p in points if p.get(key) is not None]
        def record_vals(key):
            result=[]
            for _,rec in rows:
                value=cls._session_num(rec.get(key))
                if value is not None:result.append(value)
            return result
        def mean(values):return sum(values)/len(values) if values else None
        def sd(values):
            if len(values)<2:return None
            average=mean(values); return math.sqrt(sum((v-average)**2 for v in values)/(len(values)-1))
        durations=[max(0.0,cls._session_num(rec.get("duration_seconds")) or 0.0) for _,rec in rows]
        fps=vals("gameplay_avg"); p1=vals("gameplay_p1"); consistency=vals("consistency_pct"); power=vals("avg_power")
        duration_hours=sum(durations)/3600.0
        dips=sum(record_vals("gameplay_dip_events")); hitches=sum(record_vals("isolated_hitch_candidates"))
        raw_count=sum(1 for _,rec in rows if bool(cls._stored_raw_telemetry(rec)))
        canonical_count=sum(1 for _,rec in rows if cls._session_num(rec.get("gameplay_avg_fps")) is not None and cls._session_num(rec.get("gameplay_p1_fps")) is not None)
        aggregate={"fingerprint":fingerprint,"label":cls._optimization_fingerprint_text(fingerprint),"rows":rows,"points":points,
                   "session_count":len(rows),"total_duration_seconds":sum(durations),"median_duration_seconds":cls._percentile(durations,.5),
                   "gameplay_avg_fps":mean(fps),"median_gameplay_fps":cls._percentile(fps,.5),"gameplay_fps_sd":sd(fps),
                   "gameplay_fps_range":(max(fps)-min(fps)) if fps else None,"gameplay_p1_fps":mean(p1),
                   "gameplay_p1_sd":sd(p1),"consistency_pct":mean(consistency),"consistency_sd":sd(consistency),"avg_gpu_load_pct":mean(vals("avg_gpu_load")),
                   "avg_junction_c":mean(vals("avg_junction")),"avg_junction_sd":sd(vals("avg_junction")),"max_junction_c":max(vals("max_junction")) if vals("max_junction") else None,
                   "avg_power_w":mean(power),"avg_gpu_clock_mhz":mean(vals("avg_gpu_clock")),"fps_per_watt":mean(vals("fps_per_watt")),"fps_per_watt_sd":sd(vals("fps_per_watt")),
                   "gameplay_dips_per_hour":dips/duration_hours if duration_hours>0 and record_vals("gameplay_dip_events") else None,
                   "isolated_hitches_per_hour":hitches/duration_hours if duration_hours>0 and record_vals("isolated_hitch_candidates") else None,
                   "raw_session_count":raw_count,"canonical_session_count":canonical_count,
                   "newest_timestamp":max(cls._trend_timestamp(rec,index) for index,rec in rows),"newest_history_index":rows[-1][0]}
        aggregate.update(cls._optimization_confidence(aggregate))
        return aggregate
    @classmethod
    def _optimization_confidence(cls,group):
        count=group["session_count"]; duration=group["total_duration_seconds"]; sd=group.get("gameplay_fps_sd"); avg=group.get("gameplay_avg_fps")
        raw=group.get("raw_session_count",0); canonical=group.get("canonical_session_count",0); cv=(sd/avg*100.0) if sd is not None and avg and avg>0 else None
        long_count=sum(1 for _,rec in group.get("rows",[]) if (cls._session_num(rec.get("duration_seconds")) or 0)>=1200)
        rating="Low"
        if count>=3 and duration>=3600 and long_count>=2 and canonical>=max(2,math.ceil(count*.67)) and (cv is None or cv<=15):rating="Moderate"
        if count>=5 and duration>=7200 and long_count>=4 and canonical>=math.ceil(count*.8) and raw>=math.ceil(count*.6) and cv is not None and cv<=8:rating="High"
        if cv is not None and cv>15:rating="Low"
        elif cv is not None and cv>10 and rating=="High":rating="Moderate"
        variance="unavailable" if cv is None else ("low" if cv<=5 else "moderate" if cv<=12 else "high")
        preliminary="Preliminary — single-session evidence. " if count==1 else ""
        why=f"{preliminary}{count} session{'s' if count!=1 else ''} / {cls._format_session_duration(duration)} total gameplay; {long_count} session(s) reached 20 minutes; FPS variance {variance}; {raw}/{count} sessions contain replay telemetry; {canonical}/{count} contain canonical FPS/P1; exact configuration fingerprint consistent."
        return {"confidence":rating,"confidence_reason":why,"fps_cv_pct":cv}
    @classmethod
    def _optimization_rankings(cls,groups):
        specs={"performance":("gameplay_avg_fps",True),"p1":("gameplay_p1_fps",True),"consistency":("consistency_pct",True),"efficiency":("fps_per_watt",True),"thermals":("avg_junction_c",False)}
        ranked={key:sorted([g for g in groups if g.get(metric) is not None],key=lambda g:g[metric],reverse=higher) for key,(metric,higher) in specs.items()}
        ranked["consistency"]=sorted(ranked["consistency"],key=lambda g:(g["consistency_pct"],-(g["gameplay_dips_per_hour"] if g.get("gameplay_dips_per_hour") is not None else math.inf)),reverse=True)
        components=(("gameplay_avg_fps",.25,True),("gameplay_p1_fps",.25,True),("consistency_pct",.20,True),("fps_per_watt",.15,True),("avg_junction_c",.15,False))
        for group in groups:
            used=[]
            for metric,weight,higher in components:
                values=[g[metric] for g in groups if g.get(metric) is not None]
                value=group.get(metric)
                if value is None or not values:continue
                low,high=min(values),max(values); normalized=.5 if high==low else (value-low)/(high-low)
                if not higher:normalized=1-normalized
                used.append((metric,weight,normalized))
            weight=sum(item[1] for item in used)
            group["balanced_score"]=sum(w*n for _,w,n in used)/weight*100 if weight and len(used)>=3 else None
            group["balanced_components"]=[f"{metric} {normalized*100:.0f}%" for metric,_,normalized in used]
        ranked["balanced"]=sorted([g for g in groups if g.get("balanced_score") is not None],key=lambda g:g["balanced_score"],reverse=True)
        return ranked
    @staticmethod
    def _optimization_difference(a,b,metric="gameplay_avg_fps"):
        av=a.get(metric); bv=b.get(metric)
        if av is None or bv is None:return "Insufficient evidence"
        if min(a.get("session_count",0),b.get("session_count",0))<2:return "Insufficient evidence"
        sd_key={"gameplay_avg_fps":"gameplay_fps_sd","gameplay_p1_fps":"gameplay_p1_sd","consistency_pct":"consistency_sd","fps_per_watt":"fps_per_watt_sd","avg_junction_c":"avg_junction_sd"}.get(metric)
        delta=abs(av-bv); dispersion=max(a.get(sd_key) or 0,b.get(sd_key) or 0) if sd_key else 0
        floor={"fps_per_watt":.02,"avg_junction_c":1.5,"consistency_pct":2.0}.get(metric,2.0)
        if delta<max(floor,dispersion):return "Too close to call"
        if delta>=max(floor*2.5,1.5*dispersion):return "Likely meaningful"
        return "Possible advantage"
    @classmethod
    def _optimization_delta(cls,value,base,unit,percent=True,points=False):
        if value is None or base is None:return "Unavailable"
        delta=value-base; text=f"{delta:+.1f} {'pp' if points else unit}".rstrip()
        if percent and not points and abs(base)>.01:text+=f" / {delta/base*100:+.1f}%"
        return text
    @classmethod
    def _optimization_recommendation_text(cls,groups,current=None):
        if not groups:return "More comparable gameplay data is needed. Record Gameplay sessions with saved configuration metadata."
        def display(group):return group.get("display_label") or cls._optimization_compact_label(group["fingerprint"],group.get("short_label"))
        if len(groups)==1:
            group=groups[0]
            return "\n".join((
                "OPTIMIZATION INSIGHTS • CURRENT BASELINE",
                "Observed Session History associations; different maps, updates, background load, match intensity, and ambient conditions can affect results.",
                "",
                "Only one tested configuration is available. Add a second comparable configuration to enable rankings.",
                display(group),
                f"Gameplay FPS: {cls._format_session_metric(group.get('gameplay_avg_fps'),' FPS')}",
                f"Gameplay P1: {cls._format_session_metric(group.get('gameplay_p1_fps'),' FPS')}",
                f"P1/Average consistency: {cls._format_session_metric(group.get('consistency_pct'),'%')}",
                f"Comparative FPS/W: {cls._format_session_metric(group.get('fps_per_watt'),' FPS/W')}",
                f"Average junction: {cls._format_session_metric(group.get('avg_junction_c'),'°C')}",
                "Balanced comparative ranking: unavailable until another tested configuration exists.",
                f"Evidence quality for this baseline: {group['confidence']} — {group['confidence_reason']}",
                "These values describe the current observed baseline; they do not establish a competitive or causal conclusion."
            ))
        rankings=cls._optimization_rankings(groups); lines=["OPTIMIZATION INSIGHTS","Observed Session History associations; different maps, updates, background load, match intensity, and ambient conditions can affect results. Repeated comparable tests improve confidence.",""]
        labels=(("BEST PERFORMANCE","performance","gameplay_avg_fps"," FPS"),("BEST GAMEPLAY P1","p1","gameplay_p1_fps"," FPS"),("BEST CONSISTENCY","consistency","consistency_pct","%"),("BEST EFFICIENCY","efficiency","fps_per_watt"," FPS/W"),("BEST THERMALS","thermals","avg_junction_c","°C"),("BALANCED RECOMMENDATION","balanced","balanced_score","/100"))
        for title,key,metric,suffix in labels:
            ranked=rankings[key]
            if not ranked:lines.extend([title,"Unavailable — required historical metrics are missing.",""]); continue
            best=ranked[0]; basis=f"{best['session_count']} session(s), {cls._format_session_duration(best['total_duration_seconds'])}; {best['confidence']} confidence"
            if best["session_count"]<2 or all(g["session_count"]<2 for g in groups):
                verdict="Preliminary only — more comparable gameplay data is needed before calling this configuration best."
            else:verdict=cls._optimization_difference(best,ranked[1],metric if key!="balanced" else "gameplay_avg_fps") if len(ranked)>1 else "Possible leader; no second configuration has adequate evidence."
            value=best.get(metric); lines.extend([title,display(best),f"Observed value: {value:.1f}{suffix} • Evidence: {best['confidence']} • {verdict}",f"Basis: {basis}. {best['confidence_reason']}",f"Observed tradeoffs: P1 {cls._format_session_metric(best.get('gameplay_p1_fps'),' FPS')}; consistency {cls._format_session_metric(best.get('consistency_pct'),'%')}; power {cls._format_session_metric(best.get('avg_power_w'),' W')}; junction {cls._format_session_metric(best.get('avg_junction_c'),'°C')}; comparative FPS/W {cls._format_session_metric(best.get('fps_per_watt'),' FPS/W')}."])
            if current and current is not best:
                lines.append("Versus Current/Recent: "+cls._optimization_delta(best.get("gameplay_avg_fps"),current.get("gameplay_avg_fps"),"FPS")+" Gameplay FPS; "+cls._optimization_delta(best.get("gameplay_p1_fps"),current.get("gameplay_p1_fps"),"FPS")+" P1; "+cls._optimization_delta(best.get("consistency_pct"),current.get("consistency_pct"),"",False,True)+" consistency; "+cls._optimization_delta(best.get("avg_power_w"),current.get("avg_power_w"),"W")+" power; "+cls._optimization_delta(best.get("avg_junction_c"),current.get("avg_junction_c"),"°C",False)+" junction; "+cls._optimization_delta(best.get("fps_per_watt"),current.get("fps_per_watt"),"FPS/W")+" comparative FPS/W.")
            elif current is best:lines.append("Current context: this is the Current/Recent configuration, so its change versus itself is zero and is not presented as an improvement.")
            if key=="balanced":lines.append("Balanced formula: FPS 25% + Gameplay P1 25% + consistency 20% + FPS/W 15% + cooler average junction 15%; weights are renormalized across available components, never filled with zero. Components: "+", ".join(best["balanced_components"])+".")
            lines.append("")
        return "\n".join(lines)
    @classmethod
    def _optimization_next_test(cls,groups):
        if not groups:return "Recommended Next Test: record a 20–30 minute Gameplay session with configuration metadata."
        if len(groups)==1:
            group=groups[0]; sampled=group["session_count"]>=2 and group["total_duration_seconds"]>=2400 and (group.get("median_duration_seconds") or 0)>=900
            if sampled:
                _,preset,scaling,render_res,output_res,profile=group["fingerprint"]
                if scaling!="Unknown":variable="Keep the graphics preset and GPU profile unchanged; test one different render-scale preset/configuration"
                elif profile!="Unknown":variable="Keep graphics and scaling unchanged; test one different non-privileged GPU profile already available to your normal workflow"
                else:variable="Change one documented graphics or scaling variable while holding every other known setting constant"
                return f"Recommended Next Test: Test one controlled alternative to establish a comparison baseline. {variable} for approximately 20–30 minutes under comparable workload and conditions. This is guidance only; no setting will be changed automatically."
            short_note=" and includes short-session evidence" if (group.get("median_duration_seconds") or 0)<1200 else ""
            return f"Recommended Next Test: repeat this only tested configuration for approximately 20–30 minutes before introducing an alternative. Its evidence is still under-sampled{short_note} ({group['session_count']} session(s), {cls._format_session_duration(group['total_duration_seconds'])})."
        least=min(groups,key=lambda g:(g["session_count"],g["total_duration_seconds"],-g["newest_timestamp"]))
        if least["session_count"]<max(g["session_count"] for g in groups):reason=f"has only {least['session_count']} session(s), fewer than the better-sampled alternative"
        elif (least.get("median_duration_seconds") or 0)<1200:reason="has short-session evidence"
        elif len(groups)>=2 and cls._optimization_difference(groups[0],groups[1])=="Too close to call":reason="is part of a comparison that remains too close to call"
        else:reason="would benefit from another repeat to measure session-to-session variance"
        compact=least.get("display_label") or cls._optimization_compact_label(least["fingerprint"],least.get("short_label"))
        return f"Recommended Next Test: play 20–30 minutes using {compact}. It {reason}. Keep the map/workload and background conditions as comparable as practical."
    @staticmethod
    def _optimization_card_titles(configuration_count):
        if configuration_count==1:return ("GAMEPLAY FPS BASELINE","GAMEPLAY P1 BASELINE","CONSISTENCY BASELINE","EFFICIENCY BASELINE","THERMAL BASELINE","BALANCED RANKING")
        return ("BEST PERFORMANCE","BEST GAMEPLAY P1","BEST CONSISTENCY","BEST EFFICIENCY","BEST THERMALS","BALANCED")
    @classmethod
    def _optimization_comparison_text(cls,a,b):
        lines=["CONFIGURATION COMPARISON","Observed-session comparison; association does not prove that a configuration caused the difference.","",f"A • {a['label']}",f"B • {b['label']}",""]
        specs=(("Sessions","session_count","",False,False),("Total duration","total_duration_seconds","s",False,False),("Gameplay FPS","gameplay_avg_fps"," FPS",True,False),("Gameplay P1","gameplay_p1_fps"," FPS",True,False),("Consistency","consistency_pct","%",False,True),("GPU load","avg_gpu_load_pct","%",True,False),("Average junction","avg_junction_c","°C",False,False),("Board power","avg_power_w"," W",True,False),("Comparative FPS/W","fps_per_watt"," FPS/W",True,False),("Gameplay dips/hour","gameplay_dips_per_hour","/h",False,False),("Isolated hitches/hour","isolated_hitches_per_hour","/h",False,False))
        for label,key,prefix,pct,points in specs:
            av=a.get(key); bv=b.get(key)
            if key=="total_duration_seconds":atext=cls._format_session_duration(av); btext=cls._format_session_duration(bv)
            elif av is None or bv is None:atext=cls._format_session_metric(av,prefix); btext=cls._format_session_metric(bv,prefix)
            else:atext=f"{av:.1f}{prefix}"; btext=f"{bv:.1f}{prefix}"
            lines.append(f"{label}: A {atext} • B {btext} • Δ {cls._optimization_delta(bv,av,prefix.strip(),pct,points)}")
        lines.extend(["",f"A confidence: {a['confidence']} — {a['confidence_reason']}",f"B confidence: {b['confidence']} — {b['confidence_reason']}",f"Performance interpretation: {cls._optimization_difference(a,b)}.","More repeated, similarly controlled gameplay sessions improve reliability."])
        return "\n".join(lines)
    @staticmethod
    def _trial_configuration(source):
        source=source if isinstance(source,dict) else {}
        return {key:str(source.get(key) if source.get(key) not in (None,"") else "Unknown") for key in ("gpu_profile","graphics_preset","scaling","render_resolution","output_resolution","power_limit_w","workload_profile")}
    @classmethod
    def _trial_fingerprint(cls,configuration):
        payload=json.dumps(cls._trial_configuration(configuration),sort_keys=True,separators=(",",":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    @classmethod
    def _trial_candidate_validation(cls,baseline,candidate,tested_variable):
        baseline=cls._trial_configuration(baseline); candidate=cls._trial_configuration(candidate)
        changed=[key for key in baseline if baseline[key]!=candidate[key]]
        scaling_fields={"graphics_preset","scaling","render_resolution","output_resolution"}
        valid=(len(changed)==1 and changed[0]==tested_variable) or (tested_variable=="graphics_preset" and "graphics_preset" in changed and set(changed)<=scaling_fields)
        warning="" if valid else ("No relevant configuration variable changes." if not changed else "Multiple relevant variables differ; causal attribution is weakened: "+", ".join(changed))
        return {"valid":valid,"changed":changed,"warning":warning}
    def _trial_game_matches_session(self,trial,rec):
        if trial.get("steam_appid"):return str(rec.get("steam_appid") or "")==str(trial["steam_appid"])
        return str(rec.get("telemetry_identity") or "")==str(trial.get("game_id")) or str(rec.get("game") or "").casefold()==str(trial.get("game_name") or "").casefold()
    def _trial_session_matches_configuration(self,configuration,rec,tested_variable=None):
        expected=self._trial_configuration(configuration); actual=self._trial_configuration(rec)
        known={key:value for key,value in expected.items() if value!="Unknown"}
        # The active driver workload mode is runtime context and may change as
        # a game starts (for example default -> full-screen 3D). It is strict
        # trial evidence only when workload_profile is itself the tested knob.
        if tested_variable!="workload_profile":known.pop("workload_profile",None)
        mismatches=[key for key,value in known.items() if actual.get(key)!=value]
        return not mismatches,mismatches
    def _trial_session_matches_candidate(self,trial,rec):
        return self._trial_session_matches_configuration(trial.get("candidate_configuration"),rec,trial.get("tested_variable"))
    @classmethod
    def _trial_recommended_run_target(cls,trial,baseline_aggregate=None,candidate_aggregate=None):
        baseline_count=len(trial.get("baseline_session_indexes",[])); candidate_count=len(trial.get("candidate_session_indexes",[]))
        count_difference=baseline_count-candidate_count
        metric=cls._trial_goal_metric(trial.get("goal"))[0]; sd_key={"gameplay_avg_fps":"gameplay_fps_sd","gameplay_p1_fps":"gameplay_p1_sd","consistency_pct":"consistency_sd","avg_junction_c":"avg_junction_sd","fps_per_watt":"fps_per_watt_sd"}.get(metric)
        if baseline_aggregate and candidate_aggregate and sd_key:
            baseline_sd=baseline_aggregate.get(sd_key); candidate_sd=candidate_aggregate.get(sd_key)
            if baseline_sd is not None and candidate_sd is not None and abs(count_difference)<=1 and max(float(baseline_sd),float(candidate_sd))>1.75*max(min(float(baseline_sd),float(candidate_sd)),.01):return "baseline" if float(baseline_sd)>float(candidate_sd) else "candidate"
        if baseline_count<candidate_count:return "baseline"
        if candidate_count<baseline_count:return "candidate"
        if not baseline_count:return "baseline"
        if baseline_aggregate and candidate_aggregate:
            baseline_raw=int(baseline_aggregate.get("raw_session_count") or 0); candidate_raw=int(candidate_aggregate.get("raw_session_count") or 0)
            if baseline_raw!=candidate_raw:return "baseline" if baseline_raw<candidate_raw else "candidate"
            baseline_duration=float(baseline_aggregate.get("total_duration_seconds") or 0); candidate_duration=float(candidate_aggregate.get("total_duration_seconds") or 0)
            if abs(baseline_duration-candidate_duration)>max(60.0,.1*max(baseline_duration,candidate_duration)):return "baseline" if baseline_duration<candidate_duration else "candidate"
            if sd_key:
                baseline_sd=baseline_aggregate.get(sd_key); candidate_sd=candidate_aggregate.get(sd_key)
                if baseline_sd is not None and candidate_sd is not None and abs(float(baseline_sd)-float(candidate_sd))>.05*max(abs(float(baseline_sd)),abs(float(candidate_sd)),1.0):return "baseline" if float(baseline_sd)>float(candidate_sd) else "candidate"
        return "candidate" if (trial.get("last_capture") or {}).get("side")=="baseline" else "baseline"
    @classmethod
    def _trial_next_run_reason(cls,trial,result,target):
        baseline=(result or {}).get("baseline"); candidate=(result or {}).get("candidate"); baseline_count=len(trial.get("baseline_session_indexes",[])); candidate_count=len(trial.get("candidate_session_indexes",[])); metric=cls._trial_goal_metric(trial.get("goal"))[0]; sd_key={"gameplay_avg_fps":"gameplay_fps_sd","gameplay_p1_fps":"gameplay_p1_sd","consistency_pct":"consistency_sd","avg_junction_c":"avg_junction_sd","fps_per_watt":"fps_per_watt_sd"}.get(metric)
        if baseline and candidate and sd_key and baseline.get(sd_key) is not None and candidate.get(sd_key) is not None:
            bsd=float(baseline[sd_key]); csd=float(candidate[sd_key])
            labels={'gameplay_p1_fps':'P1','gameplay_avg_fps':'average FPS','consistency_pct':'consistency','avg_junction_c':'junction temperature','fps_per_watt':'FPS/W'}
            if abs(baseline_count-candidate_count)<=1 and max(bsd,csd)>1.75*max(min(bsd,csd),.01):return f"{target.title()} {labels.get(metric,metric)} variance is substantially higher; another run helps test repeatability."
        if baseline_count!=candidate_count:return f"{target.title()} has fewer accepted runs ({baseline_count if target=='baseline' else candidate_count} vs {candidate_count if target=='baseline' else baseline_count})."
        return "Evidence counts and spread are similar; one alternating run adds balanced evidence."
    @classmethod
    def _trial_evidence_summary(cls,trial,result=None):
        baseline=len(trial.get("baseline_session_indexes",[])); candidate=len(trial.get("candidate_session_indexes",[])); last=trial.get("last_capture") or {}; target=cls._trial_recommended_run_target(trial,(result or {}).get("baseline"),(result or {}).get("candidate")); value=cls._trial_configuration(trial.get(f"{target}_configuration")).get(trial.get("tested_variable"),"Unknown")
        last_line=f"Last captured: {str(last.get('side')).title()} — {last.get('configuration')}" if last.get("side") else "Last captured: none"
        capture=[last.get("message"),str(last.get("configuration")),f"{str(last.get('side')).title()} runs: {baseline if last.get('side')=='baseline' else candidate}"] if last.get("message") else []
        reason=cls._trial_next_run_reason(trial,result,target)
        return {"baseline":baseline,"candidate":candidate,"last":last_line,"next_target":target,"next_value":value,"next_reason":reason,"button":f"Add {target.title()} Run","capture":capture,"evidence":[f"Baseline runs: {baseline}    Candidate runs: {candidate}",last_line,f"Recommended next: {target.title()} run — {value}",f"Why: {reason}"]}
    @staticmethod
    def _trial_rejection_feedback(trial):
        rejection=trial.get("last_rejection") or ((trial.get("rejected_sessions") or [None])[-1])
        if not rejection or float(rejection.get("time") or 0)<=float((trial.get("last_capture") or {}).get("captured_at") or 0):return []
        return [f"{str(rejection.get('target') or trial.get('waiting_for') or 'Run').title()} run not accepted",f"Reason: {rejection.get('reason') or 'Session did not meet the active trial requirements'}"]
    @classmethod
    def _trial_target_configuration_matches(cls,trial,target,current_configuration):
        variable=trial.get("tested_variable"); expected=cls._trial_configuration(trial.get(f"{target}_configuration")).get(variable); actual=cls._trial_configuration(current_configuration).get(variable)
        return cls._trial_candidate_value_available(variable,expected,[actual]),expected,actual
    @classmethod
    def _trial_goal_metric(cls,goal):
        return {"Higher average FPS":("gameplay_avg_fps",True),"Better P1 / lows":("gameplay_p1_fps",True),"Better consistency":("consistency_pct",True),"Lower power":("avg_power_w",False),"Lower junction temperature":("avg_junction_c",False),"Better FPS/W":("fps_per_watt",True),"Balanced":("balanced_score",True)}.get(goal,("gameplay_avg_fps",True))
    def _trial_aggregate(self,indexes,configuration):
        sessions=self.game_session_history.get("sessions",[]); rows=[(i,sessions[i]) for i in indexes if isinstance(i,int) and 0<=i<len(sessions) and self._game_session_quality(sessions[i])=="Gameplay"]
        if not rows:return None
        fingerprint=self._optimization_fingerprint(rows[-1][1]); return self._optimization_aggregate(fingerprint,rows)
    def _optimization_trial_result(self,trial):
        baseline=self._trial_aggregate(trial.get("baseline_session_indexes",[]),trial.get("baseline_configuration")); candidate=self._trial_aggregate(trial.get("candidate_session_indexes",[]),trial.get("candidate_configuration"))
        if not baseline or not candidate:return {"verdict":"MORE EVIDENCE NEEDED","confidence":"Low","summary":"A comparable baseline and candidate Gameplay session are required.","baseline":baseline,"candidate":candidate}
        metric,higher=self._trial_goal_metric(trial.get("goal")); metric="gameplay_avg_fps" if metric=="balanced_score" else metric
        av=baseline.get(metric); bv=candidate.get(metric); delta=(bv-av) if av is not None and bv is not None else None
        preliminary=min(baseline["session_count"],candidate["session_count"])<2
        evidence=self._optimization_difference(baseline,candidate,metric)
        if delta is None:verdict="MORE EVIDENCE NEEDED"; summary="The selected goal metric is unavailable in one configuration."
        elif evidence in ("Too close to call","Insufficient evidence"):
            verdict="TOO CLOSE TO CALL"; spread=self._trial_run_spread(candidate,metric); pct=(100.0*delta/av) if delta is not None and av else None; max_sd=max(baseline.get({"gameplay_avg_fps":"gameplay_fps_sd","gameplay_p1_fps":"gameplay_p1_sd","consistency_pct":"consistency_sd","fps_per_watt":"fps_per_watt_sd","avg_junction_c":"avg_junction_sd"}.get(metric)) or 0,candidate.get({"gameplay_avg_fps":"gameplay_fps_sd","gameplay_p1_fps":"gameplay_p1_sd","consistency_pct":"consistency_sd","fps_per_watt":"fps_per_watt_sd","avg_junction_c":"avg_junction_sd"}.get(metric)) or 0)
            if spread and spread.get("sd") is not None and delta is not None:summary=f"Candidate {self._trial_metric_label(metric)} averages {pct:+.1f}% versus baseline, but candidate runs vary from {spread['min']:.1f}–{spread['max']:.1f} ({spread['sd']:.1f} SD) and the {abs(delta):.1f} observed difference is not larger than {max_sd:.1f} run-to-run variability."
            else:summary="The comparison is preliminary because the selected goal lacks enough repeated-run variance evidence."
        elif (delta>0)==higher:verdict="KEEP CANDIDATE"; summary=("Possible improvement" if evidence=="Possible advantage" else "Likely meaningful improvement")+f" in the goal metric ({self._optimization_delta(bv,av,'',True)})."
        else:verdict="REVERT TO BASELINE"; summary=f"Candidate regressed the selected goal metric ({self._optimization_delta(bv,av,'',True)})."
        confidence="Low" if preliminary else ("Moderate" if evidence in ("Possible advantage","Too close to call") else "High" if min(baseline["session_count"],candidate["session_count"])>=5 else "Moderate")
        if preliminary:summary="Preliminary — "+summary+" More comparable sessions are recommended."
        cap=any(str(group.get("rows",[[0,{}]])[-1][1].get("frame_cap_status") or "").startswith(("Frame-rate cap","Possible frame cap")) for group in (baseline,candidate))
        if cap:summary+=" Frame-cap/synchronization evidence means unchanged capped FPS can still accompany useful power, thermal, or consistency gains."
        if not trial.get("trial_complete") and trial.get("waiting_for") not in ("baseline","candidate"):trial["status"]="More Evidence Needed" if verdict in ("MORE EVIDENCE NEEDED","TOO CLOSE TO CALL") else "Completed"
        return {"verdict":verdict,"confidence":confidence,"summary":summary,"baseline":baseline,"candidate":candidate,"metric":metric,"delta":delta,"evidence":evidence}
    @classmethod
    def _trial_stopping_decision(cls,trial,result):
        if trial.get("evidence_budget_override"):return {"stop":False,"reason":"Explicit Continue Testing override is active."}
        baseline=result.get("baseline"); candidate=result.get("candidate")
        if not baseline or not candidate:return {"stop":False,"reason":"Both sides do not yet have eligible Gameplay evidence."}
        baseline_count=int(baseline.get("session_count") or 0); candidate_count=int(candidate.get("session_count") or 0); evidence=result.get("evidence")
        if result.get("verdict") in ("KEEP CANDIDATE","REVERT TO BASELINE") and evidence=="Likely meaningful" and min(baseline_count,candidate_count)>=3:
            return {"stop":True,"outcome":result["verdict"],"reason":"The existing conservative comparison reached a repeatable likely-meaningful result before the practical evidence budget."}
        if min(baseline_count,candidate_count)<4:return {"stop":False,"reason":"The practical four-runs-per-side evidence budget has not been reached."}
        metric=result.get("metric"); baseline_spread=cls._trial_run_spread(baseline,metric); candidate_spread=cls._trial_run_spread(candidate,metric)
        if not baseline_spread or not candidate_spread or len(baseline_spread["indexed"])<4 or len(candidate_spread["indexed"])<4:return {"stop":False,"reason":"Accepted runs exist, but the goal metric is missing from enough sessions that another valid run may resolve the evidence gap."}
        label=cls._trial_metric_label(metric); unusual=bool(baseline_spread["unusual"] or candidate_spread["unusual"]); dominant=max(baseline_spread.get("sd") or 0,candidate_spread.get("sd") or 0); delta=abs(float(result.get("delta") or 0))
        if result.get("verdict") in ("TOO CLOSE TO CALL","MORE EVIDENCE NEEDED"):
            detail=(f"{label} run-to-run variability ({dominant:.1f}) exceeds the observed difference ({delta:.1f})" if dominant>delta else f"the observed {label} difference remains below the conservative decision threshold")
            if unusual:detail+=" and the aggregate is sensitive to an unusual retained run"
            promising=[]
            if candidate.get("gameplay_p1_fps") is not None and baseline.get("gameplay_p1_fps") is not None and candidate["gameplay_p1_fps"]>baseline["gameplay_p1_fps"]:promising.append("higher P1")
            if candidate.get("consistency_pct") is not None and baseline.get("consistency_pct") is not None and candidate["consistency_pct"]>baseline["consistency_pct"]:promising.append("better P1/Avg consistency")
            if candidate.get("gameplay_dips_per_hour") is not None and baseline.get("gameplay_dips_per_hour") is not None and candidate["gameplay_dips_per_hour"]<baseline["gameplay_dips_per_hour"]:promising.append("fewer gameplay dips")
            promise=("The candidate shows promising "+", ".join(promising)+", but a reliable improvement is not established." if promising else "Neither side establishes a reliable improvement.")
            return {"stop":True,"outcome":"INCONCLUSIVE","reason":f"Practical evidence budget reached: four valid runs per side; {detail}. Another ordinary run is not expected to resolve that uncertainty reliably. {promise}"}
        return {"stop":True,"outcome":result.get("verdict") or "INCONCLUSIVE","reason":"Practical evidence budget reached with a completed comparison."}
    @classmethod
    def _trial_metric_report_lines(cls,result):
        baseline=result.get("baseline"); candidate=result.get("candidate")
        if not baseline or not candidate:return ["Canonical metric comparison unavailable until both sides have Gameplay evidence."]
        specs=(("Gameplay Avg FPS","gameplay_avg_fps"," FPS",True,False),("Gameplay P1","gameplay_p1_fps"," FPS",True,False),("P1/Avg consistency","consistency_pct","%",False,True),("Gameplay dips/hour","gameplay_dips_per_hour","/h",False,False),("Isolated hitches/hour","isolated_hitches_per_hour","/h",False,False),("Average GPU load","avg_gpu_load_pct","%",False,False),("Average junction","avg_junction_c","°C",False,False),("Maximum junction","max_junction_c","°C",False,False),("Board power","avg_power_w"," W",False,False),("FPS/W","fps_per_watt"," FPS/W",True,False),("Session duration","total_duration_seconds"," s",False,False))
        lines=[]
        for label,key,unit,pct,points in specs:
            a=baseline.get(key); b=candidate.get(key); display_a="Unavailable" if a is None else cls._format_session_metric(a,unit); display_b="Unavailable" if b is None else cls._format_session_metric(b,unit); lines.append(f"{label}: {display_a} → {display_b} • {cls._optimization_delta(b,a,unit.strip(),pct,points)}")
        lines.append(f"Evidence: baseline {baseline['session_count']} run(s), {baseline['raw_session_count']} replay • candidate {candidate['session_count']} run(s), {candidate['raw_session_count']} replay")
        return lines
    @classmethod
    def _trial_result_section_lines(cls,result,goal):
        baseline=result.get("baseline"); candidate=result.get("candidate")
        if not baseline or not candidate:return ["BASELINE vs CANDIDATE","Comparison unavailable until each side has an eligible Gameplay session.",*cls._trial_metric_report_lines(result)]
        metric,higher=cls._trial_goal_metric(goal); metric="gameplay_avg_fps" if metric=="balanced_score" else metric; labels={"gameplay_avg_fps":"Gameplay Avg FPS","gameplay_p1_fps":"Gameplay P1","consistency_pct":"P1/Avg consistency","avg_power_w":"Board power","avg_junction_c":"Average junction","fps_per_watt":"FPS/W"}; units={"gameplay_avg_fps":" FPS","gameplay_p1_fps":" FPS","consistency_pct":"%","avg_power_w":" W","avg_junction_c":"°C","fps_per_watt":" FPS/W"}; a=baseline.get(metric); b=candidate.get(metric); unit=units.get(metric,""); points=metric=="consistency_pct"; pct=metric not in ("consistency_pct","avg_power_w","avg_junction_c")
        primary=f"Primary goal — {labels.get(metric,metric)}: {cls._format_session_metric(a,unit)} → {cls._format_session_metric(b,unit)} • {cls._optimization_delta(b,a,unit.strip(),pct,points)}"
        direction="unavailable"
        if a is not None and b is not None:direction="candidate is higher" if b>a else ("candidate is lower" if b<a else "no observed difference")
        supporting=f"Supporting evidence: average FPS {cls._optimization_delta(candidate.get('gameplay_avg_fps'),baseline.get('gameplay_avg_fps'),'FPS',True)}; consistency {cls._optimization_delta(candidate.get('consistency_pct'),baseline.get('consistency_pct'),'',False,True)}; dips {cls._optimization_delta(candidate.get('gameplay_dips_per_hour'),baseline.get('gameplay_dips_per_hour'),'/h',False)}."
        tradeoffs=f"Tradeoffs: board power {cls._optimization_delta(candidate.get('avg_power_w'),baseline.get('avg_power_w'),'W',False)}; average junction {cls._optimization_delta(candidate.get('avg_junction_c'),baseline.get('avg_junction_c'),'°C',False)}."
        return ["BASELINE vs CANDIDATE",f"Outcome: {result.get('verdict','MORE EVIDENCE NEEDED')}",f"Confidence: {result.get('confidence','Low')}",primary,f"Interpretation: {direction}; {result.get('summary','')}",supporting,tradeoffs,"","RUN-TO-RUN EVIDENCE",*cls._trial_run_evidence_lines(result,goal),"",*cls._trial_metric_report_lines(result)]
    @staticmethod
    def _trial_metric_label(metric):
        return {"gameplay_p1_fps":"P1","gameplay_avg_fps":"average FPS","consistency_pct":"consistency","avg_power_w":"board power","avg_junction_c":"junction temperature","fps_per_watt":"FPS/W"}.get(metric,metric)
    @classmethod
    def _trial_run_values(cls,group,metric):
        values=[]
        for index,rec in (group or {}).get("rows",[]):
            if metric=="gameplay_dips_per_hour":
                duration=cls._session_num(rec.get("duration_seconds")); count=cls._session_num(rec.get("gameplay_dip_events")); value=(3600.0*count/duration) if duration and count is not None else None
            elif metric=="consistency_pct":
                avg=cls._session_num(rec.get("gameplay_avg_fps")); p1=cls._session_num(rec.get("gameplay_p1_fps")); value=(100.0*p1/avg) if avg and p1 is not None else None
            else:value=cls._session_num(rec.get(metric))
            if value is not None:values.append((index,float(value)))
        return values
    @classmethod
    def _trial_run_spread(cls,group,metric):
        indexed=cls._trial_run_values(group,metric); values=[value for _,value in indexed]
        if not values:return None
        mean=sum(values)/len(values); median=cls._percentile(values,.5); sd=None
        if len(values)>1:sd=math.sqrt(sum((value-mean)**2 for value in values)/(len(values)-1))
        unusual=[]
        if len(values)>=3:
            deviations=[abs(value-median) for value in values]; mad=cls._percentile(deviations,.5); threshold=max(3.0*1.4826*mad,.10*abs(median),.01)
            unusual=[(index,value) for index,value in indexed if abs(value-median)>threshold]
        return {"indexed":indexed,"mean":mean,"median":median,"min":min(values),"max":max(values),"range":max(values)-min(values),"sd":sd,"cv":(100.0*sd/mean) if sd is not None and mean else None,"se":(sd/math.sqrt(len(values))) if sd is not None else None,"unusual":unusual}
    @classmethod
    def _trial_run_evidence_lines(cls,result,goal):
        baseline=result.get("baseline"); candidate=result.get("candidate"); metric=cls._trial_goal_metric(goal)[0]; metric="gameplay_avg_fps" if metric=="balanced_score" else metric; lines=[]
        for title,key,unit in ((cls._trial_metric_label(metric),metric," FPS" if "fps" in metric else ""),("Gameplay Avg FPS","gameplay_avg_fps"," FPS"),("Gameplay dips/hour","gameplay_dips_per_hour","/h")):
            b=cls._trial_run_spread(baseline,key); c=cls._trial_run_spread(candidate,key)
            if not b and not c:continue
            def values(spread):return "Unavailable" if not spread else ", ".join(f"#{index} {value:.1f}" for index,value in spread["indexed"])
            def summary(spread):
                if not spread:return "Unavailable"
                variability="variance unavailable (one run)" if spread["sd"] is None else f"{spread['mean']:.1f} ± {spread['sd']:.1f}{unit}; median {spread['median']:.1f}; {spread['min']:.1f}–{spread['max']:.1f}; CV {spread['cv']:.1f}%"
                return variability
            lines.extend((title,f"  Baseline runs: {values(b)}",f"  Candidate runs: {values(c)}",f"  Baseline: {summary(b)}",f"  Candidate: {summary(c)}"))
            unusual=(b or {}).get("unusual",[])+(c or {}).get("unusual",[])
            if unusual:lines.append("  Unusual run retained: "+", ".join(f"#{index} {value:.1f}{unit}" for index,value in unusual)+"; it remains included and can materially affect the mean/spread.")
        return lines
    @classmethod
    def _trial_variable_established(cls,rec,variable):
        config=cls._trial_configuration(rec); fields={"graphics_preset":("graphics_preset","scaling"),"gpu_profile":("gpu_profile",),"power_limit_w":("power_limit_w",),"workload_profile":("workload_profile",)}.get(variable,(variable,))
        return all(config.get(field) not in (None,"","Unknown","—") for field in fields)
    @staticmethod
    def _trial_reconcile_candidate_selection(current,values,context_changed=False):
        values=list(values or [])
        if not values:return {"selection":"No valid candidate available","apply_enabled":False}
        if context_changed or current not in values:return {"selection":values[0],"apply_enabled":True}
        return {"selection":current,"apply_enabled":True}
    @staticmethod
    def _trial_candidate_value_available(variable,value,values):
        if variable=="power_limit_w":
            try:return any(abs(float(value)-float(item))<.01 for item in values)
            except Exception:return False
        return str(value) in {str(item) for item in values}
    @classmethod
    def _trial_active_candidate_state(cls,trial,values):
        variable=trial.get("tested_variable"); candidate=cls._trial_configuration(trial.get("candidate_configuration")).get(variable,"Unknown"); valid=cls._trial_candidate_value_available(variable,candidate,values)
        return {"candidate":candidate,"valid":valid,"warning":"" if valid else f"Active trial candidate unavailable: {candidate}. No replacement was selected; candidate actions are disabled."}
    @classmethod
    def _trial_exclude_baseline_candidate(cls,variable,values,baseline):
        current=cls._trial_configuration(baseline).get(variable)
        result=[]
        for value in values or []:
            same=str(value)==str(current)
            if variable=="power_limit_w":
                try:same=abs(float(value)-float(current))<.01
                except Exception:pass
            if not same:result.append(value)
        return result
