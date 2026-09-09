"""Per-game recommendation backend helpers for AMD Linux Control Center.

This mixin owns advisory recommendation derivation and safe application planning.
It contains no Tk widget construction, persistence orchestration, game launch, or
implicit setting changes. It relies on OptimizationEngineMixin for shared
configuration, grouping, trial, and evidence helpers.
"""

import json
import math


class RecommendationEngineMixin:
    @staticmethod
    def _recommendation_goal_metric(goal):
        return {"Higher average FPS":("gameplay_avg_fps",True),"Better P1 / lows":("gameplay_p1_fps",True),"Better consistency":("consistency_pct",True),"Lower power":("avg_power_w",False),"Lower temperature":("avg_junction_c",False),"Better FPS/W":("fps_per_watt",True)}.get(goal,("balanced_score",True))

    @classmethod
    def _recommendation_configuration(cls,source):
        if isinstance(source,dict) and source.get("rows"):source=source["rows"][-1][1]
        return cls._trial_configuration(source)

    @staticmethod
    def _recommendation_value_known(value):
        """Return False for display/place-holder values that are not actionable settings."""
        if value is None:
            return False
        return str(value).strip().casefold() not in {"","-","—","unknown","unavailable","none","not configured","n/a","na"}

    @classmethod
    def _recommendation_known_fields(cls,configuration):
        configuration=cls._trial_configuration(configuration)
        return {key:value for key,value in configuration.items() if cls._recommendation_value_known(value)}

    @classmethod
    def _recommendation_configuration_known(cls,configuration):
        return bool(cls._recommendation_known_fields(configuration))

    @classmethod
    def _recommendation_config_matches(cls,left,right):
        left=cls._recommendation_known_fields(left); right=cls._recommendation_known_fields(right)
        return bool(left) and bool(right) and all(key in left and left[key]==value for key,value in right.items())

    @staticmethod
    def _recommendation_group_frame_cap(group):
        values=[str(rec.get("frame_cap_status") or "") for _,rec in (group or {}).get("rows",[])]
        likely=[value.startswith("Frame-rate cap / synchronization likely") for value in values]
        return bool(values) and (likely[-1] or sum(likely)>=max(1,math.ceil(len(values)/2)))

    @classmethod
    def _recommendation_balanced_scores(cls,groups):
        capped=any(cls._recommendation_group_frame_cap(group) for group in groups)
        specs=(("gameplay_avg_fps",.10 if capped else .18,True,"average FPS"),("gameplay_p1_fps",.12 if capped else .22,True,"P1"),("consistency_pct",.20 if capped else .15,True,"consistency"),("gameplay_dips_per_hour",.15 if capped else .12,False,"fewer dips"),("isolated_hitches_per_hour",.10 if capped else .08,False,"fewer hitches"),("avg_power_w",.14 if capped else .10,False,"lower power"),("avg_junction_c",.10 if capped else .08,False,"lower junction"),("fps_per_watt",.09 if capped else .07,True,"FPS/W"))
        for group in groups:
            used=[]
            for metric,weight,higher,label in specs:
                values=[float(row[metric]) for row in groups if row.get(metric) is not None]; value=group.get(metric)
                if value is None or len(values)<2:continue
                low,high=min(values),max(values); normalized=.5 if high==low else (float(value)-low)/(high-low); normalized=normalized if higher else 1-normalized; used.append((label,weight,normalized))
            total=sum(weight for _,weight,_ in used); group["balanced_score"]=100*sum(weight*value for _,weight,value in used)/total if total and len(used)>=3 else None; group["recommendation_components"]=[f"{label}: {value*100:.0f}% of observed range" for label,_,value in used]
        return capped

    @classmethod
    def _recommendation_trial_context(cls,trials,game):
        gid=str(game.get("game_id") or ""); appid=str(game.get("steam_appid") or game.get("provider_id") or "")
        rows=[trial for trial in (trials or {}).get("trials",[]) if isinstance(trial,dict) and ((gid and str(trial.get("game_id") or "")==gid) or (appid and str(trial.get("steam_appid") or "")==appid))]
        return sorted(rows,key=lambda trial:float(trial.get("completed_at") or trial.get("created_at") or 0),reverse=True)

    def _derive_game_recommendation(self,game,goal="Balanced",current_configuration=None,sessions=None,trials=None,telemetry_policy=None):
        """Derive advisory state without mutating Session History or trial storage."""
        game=dict(game or {}); sessions=list(sessions if sessions is not None else self.game_session_history.get("sessions",[])); trials=trials if trials is not None else self.optimization_trials; current=self._trial_configuration(current_configuration if current_configuration is not None else self._trial_current_configuration(game))
        reference={"game":game.get("display_name") or game.get("game") or "Game","steam_appid":str(game.get("steam_appid") or game.get("provider_id") or ""),"telemetry_identity":game.get("game_id")}; groups=self._optimization_groups(sessions,reference)
        output=current.get("output_resolution"); compatible=[group for group in groups if output in (None,"Unknown") or group["fingerprint"][4] in ("Unknown",output)]; groups=compatible or groups
        capped=self._recommendation_balanced_scores(groups); metric,higher=self._recommendation_goal_metric(goal); usable=[group for group in groups if group.get(metric) is not None]; usable.sort(key=lambda group:group[metric],reverse=higher)
        current_group=next((group for group in groups if self._recommendation_config_matches(self._recommendation_configuration(group),current)),None); policy=telemetry_policy or self._telemetry_policy_record(game.get("game_id")).get("state")
        result={"game":game,"goal":goal,"current_configuration":current,"recommended_configuration":None,"type":"No recommendation available","confidence":"Low","status":"No measured recommendation yet","reason":"Play normally to collect a Gameplay session.","evidence":[],"limitations":[],"groups":groups,"best":None,"alternative":None,"apply_available":False,"frame_cap":capped}
        if policy in ("disabled_by_user","compatibility_failed"):
            result["limitations"].append("FPS telemetry is disabled for this game; FPS/P1-focused recommendations are unavailable and ALCC will not re-enable telemetry.")
            if goal not in ("Lower power","Lower temperature"):usable=[]
        trial_target=None; trial_note=None; trial_conflict=None
        for trial in self._recommendation_trial_context(trials,game):
            clone=json.loads(json.dumps(trial)); trial_result=self._optimization_trial_result(clone); decision=self._trial_stopping_decision(clone,trial_result); outcome=str(trial.get("trial_outcome") or (decision.get("outcome") if decision.get("stop") else "")).upper(); final_value=trial.get("final_choice") or {}; final=str(final_value.get("choice") if isinstance(final_value,dict) else final_value)
            if outcome=="KEEP CANDIDATE":trial_target=trial.get("candidate_configuration"); trial_note="A completed controlled trial supported the candidate configuration."
            elif outcome in ("KEEP BASELINE","REVERT TO BASELINE"):trial_target=trial.get("baseline_configuration"); trial_note="A completed controlled trial supported retaining the baseline configuration."
            elif outcome=="INCONCLUSIVE" or (trial.get("trial_complete") and final=="no_change"):trial_target=current; trial_note="The completed A/B trial was inconclusive; no reliable improvement over the current configuration was established."
            if trial_note:
                if final in ("baseline","candidate") and not self._recommendation_config_matches(trial.get(f"{final}_configuration"),trial_target):trial_conflict="The user's final choice differs from the measured outcome; both are shown rather than silently overriding evidence."
                break
        if not groups:
            if trial_note:result.update({"recommended_configuration":self._trial_configuration(trial_target),"type":"Trial-supported recommendation","confidence":"Conservative","status":"Retain current configuration","reason":trial_note}); result["evidence"].append(trial_note)
            return result
        if len(groups)==1:
            only=groups[0]; measured=self._recommendation_configuration(only); known=self._recommendation_configuration_known(measured); result.update({"best":only,"recommended_configuration":measured if known else None,"type":"Preliminary recommendation" if known else "Insufficient evidence","confidence":"Low" if only["session_count"]<2 or not known else only["confidence"],"status":"Current configuration is performing as observed" if known else "Insufficient comparative evidence","reason":"Only one measured configuration is available; no alternative has enough evidence for comparison." if known else "The sessions contain valid performance evidence, but their controlled configuration cannot be reconstructed from stored fields. No configuration change is recommended."}); result["evidence"]=[f"{only['session_count']} comparable Gameplay run(s), {self._format_session_duration(only['total_duration_seconds'])} total.",f"Average {self._format_session_metric(only.get('gameplay_avg_fps'),' FPS')} • P1 {self._format_session_metric(only.get('gameplay_p1_fps'),' FPS')}."]
            if self._recommendation_group_frame_cap(only):result["evidence"].append("Frame-cap/synchronization evidence is strong; added GPU performance is not assumed to raise capped FPS.")
            result["apply_available"]=bool(known and self._recommendation_configuration_known(current) and not self._recommendation_config_matches(current,measured))
            return result
        if not usable:result.update({"status":"Insufficient evidence","type":"Insufficient evidence","reason":"Comparable configurations exist, but the selected goal metric is unavailable."}); return result
        best=usable[0]; alternative=usable[1] if len(usable)>1 else None; evidence=self._optimization_difference(best,alternative,metric) if alternative else "Insufficient evidence"; recommended=best; confidence=best.get("confidence","Low"); kind="Best observed configuration"; status="Preliminary recommendation"
        spread=self._trial_run_spread(best,metric) if metric!="balanced_score" else None; sensitive=bool(spread and spread.get("unusual"))
        if evidence=="Likely meaningful" and not sensitive:kind=status="Measured recommendation"
        elif evidence in ("Too close to call","Insufficient evidence") or sensitive:recommended=current_group or best; confidence="Low" if sensitive else "Conservative"; status="Insufficient evidence"; kind="Preliminary recommendation"
        if trial_target:
            matched=next((group for group in groups if self._recommendation_config_matches(self._recommendation_configuration(group),trial_target)),None); recommended=matched or current_group or recommended; kind="Trial-supported recommendation"; confidence="Moderate"; status="Retain current configuration" if "inconclusive" in trial_note.casefold() else kind
        # A trial recommends its persisted controlled configuration, not incidental
        # runtime power/workload fields observed in the newest associated session.
        wanted=self._trial_configuration(trial_target) if trial_target else self._recommendation_configuration(recommended); result.update({"best":recommended,"alternative":alternative if alternative is not recommended else next((row for row in usable if row is not recommended),None),"recommended_configuration":wanted,"type":kind,"confidence":confidence,"status":status,"reason":trial_note or f"{evidence} for the selected goal across comparable configuration groups."})
        result["evidence"]=[f"{sum(group['session_count'] for group in groups)} comparable Gameplay runs across {len(groups)} configurations.",f"Recommended group: {recommended['session_count']} run(s), {self._format_session_duration(recommended['total_duration_seconds'])}."]
        if trial_note:result["evidence"].append("Broader Session History grouping remains observational and does not override the completed controlled-trial conclusion.")
        else:result["evidence"].append(f"Comparison strength: {evidence}."); result["evidence"].extend(recommended.get("recommendation_components",[])[:3])
        if capped:result["evidence"].append("Frame-cap context shifts Balanced interpretation toward consistency, power, and thermals.")
        if sensitive:result["limitations"].append("The apparent advantage is sensitive to an unusual retained run; confidence is reduced.")
        if trial_conflict:result["limitations"].append(trial_conflict)
        result["apply_available"]=bool(self._recommendation_configuration_known(current) and self._recommendation_configuration_known(wanted) and not self._recommendation_config_matches(current,wanted)); return result

    @classmethod
    def _recommendation_changes(cls,current,recommended):
        current=cls._trial_configuration(current); recommended=cls._trial_configuration(recommended); changes=[]
        for key,label in (("gpu_profile","GPU profile"),("graphics_preset","Scaling/graphics preset"),("power_limit_w","Power limit"),("workload_profile","Workload profile")):
            old=current.get(key); new=recommended.get(key)
            if not cls._recommendation_value_known(new):
                continue
            if cls._recommendation_value_known(old) and old==new:
                continue
            changes.append((key,label,old,new))
        return changes

    def _apply_recommended_configuration(self,recommendation,apply_callback=None):
        changes=self._recommendation_changes(recommendation.get("current_configuration"),recommendation.get("recommended_configuration")); applied=[]
        for key,label,old,new in changes:
            trial={"tested_variable":key,"game_id":recommendation["game"].get("game_id"),"steam_appid":recommendation["game"].get("steam_appid")}
            try:
                ok=apply_callback(key,new) if apply_callback else self._apply_trial_change(trial,recommendation["recommended_configuration"])
                if ok is False:raise RuntimeError(f"{label} application was not verified")
                applied.append((key,label,old,new))
            except Exception as exc:
                rollback_errors=[]
                for old_key,old_label,old_value,_ in reversed(applied):
                    try:
                        ok=apply_callback(old_key,old_value) if apply_callback else self._apply_trial_change({**trial,"tested_variable":old_key},recommendation["current_configuration"])
                        if ok is False:raise RuntimeError("readback failed")
                    except Exception as rollback_exc:rollback_errors.append(f"{old_label}: {rollback_exc}")
                return {"applied":False,"error":str(exc)+(f"; rollback incomplete ({'; '.join(rollback_errors)})" if rollback_errors else "; prior changes restored"),"changes":applied}
        return {"applied":True,"changes":applied}
