"""Provider-neutral runtime process detection for AMD Linux Control Center.

This module owns the non-UI runtime learning/matching backend.  It intentionally
keeps Tk dialogs, persistence writes, profile application, and monitor event
orchestration in the main application while making /proc inspection and exact
runtime identity matching independently testable.
"""
import os
import pathlib
import re
import shlex
import threading
import time

from alcc_game_discovery import normalized_game_record


class RuntimeDetectionMixin:
    @staticmethod
    def _runtime_signature_label(signature):
        return str(signature.get("value") or signature.get("process_name") or "Unknown") if isinstance(signature,dict) else str(signature)

    @staticmethod
    def _runtime_basename(value):
        return str(value or "").replace("\\","/").rstrip("/").rsplit("/",1)[-1]

    @staticmethod
    def _generic_runtime_helper(name):
        low=RuntimeDetectionMixin._runtime_basename(name).casefold().removesuffix(".exe")
        exact={"wine","wine64","wineserver","winedevice","proton","pressure-vessel","pressure-vessel-wrap","gamescope","steam","steamwebhelper","steam-runtime-supervisor","python","python3","bash","dash","sh","cmd","explorer","services","rpcss","plugplay","svchost","conhost","start"}
        helper_fragments=("iscriptevaluator","script-evaluator","crashhandler","crashpad","werfault","redist","vcredist","dxsetup","installer","uninstaller","updater","updatehelper","bootstrapper")
        return low in exact or any(fragment in low for fragment in helper_fragments)


    @staticmethod
    def _runtime_infrastructure_process(proc):
        """Identify launcher/browser/container infrastructure that is never a useful
        learned Steam-game executable unless it resolves inside the game's tree or
        exposes a concrete Windows executable token.
        """
        text=" ".join((str(proc.get("comm") or ""),str(proc.get("exe") or ""),str(proc.get("cmdline") or ""))).casefold()
        markers=(
            "steam-runtime-launcher-service","steam-runtime-launcher-interface",
            "pressure-vessel","pressure-vessel-wrap","/pressure-vessel/from-host/",
            "pv-bwrap","steamwebhelper","steam-runtime-supervisor","reaper",
            "/app/vivaldi/","/app/chromium/","/app/google-chrome/",
            "--type=renderer","--type=gpu-process","crashpad-handler",
        )
        return any(marker in text for marker in markers)

    @classmethod
    def _runtime_selected_steam_launch_seen(cls,before,after,game):
        appid=str((game or {}).get("steam_appid") or "")
        if not appid:
            return True
        new_pids=set(after or {})-set(before or {})
        if not new_pids:
            return False
        # Steam/Proton commonly puts AppID evidence on a wrapper or parent rather
        # than the final game executable. Treat any newly appeared process tree
        # carrying the selected AppID as proof that the user actually launched it.
        for pid in new_pids:
            current=pid; seen=set(); depth=0
            while current in (after or {}) and current not in seen and depth<16:
                seen.add(current); proc=(after or {})[current]
                if appid in cls._runtime_process_steam_ids(proc):
                    return True
                current=proc.get("ppid"); depth+=1
        return False

    @staticmethod
    def _runtime_process_classification(proc,windows=None):
        command=str(proc.get("cmdline") or "").casefold(); exe=str(proc.get("exe") or "").casefold()
        if windows or any(word in command for word in ("wine","proton","compatdata/")):return "Wine/Proton"
        if "pressure-vessel" in command or "steam-runtime" in command:return "Container/runtime"
        return "Native" if exe else "Process"

    @staticmethod
    def _runtime_candidate_key(candidate):
        signature=candidate.get("signature") or {}
        return (str(signature.get("kind") or "").casefold(),os.path.normcase(str(signature.get("value") or "")).casefold(),os.path.normcase(str(signature.get("executable_path") or "")).casefold())

    @classmethod
    def _runtime_candidates(cls,before,after,game=None,first_seen=None,now=None):
        candidates=[]; now=float(time.monotonic() if now is None else now); install_path=os.path.realpath(str((game or {}).get("install_path") or "")) if (game or {}).get("install_path") else ""
        all_after=after or {}; new_pids=set(all_after)-set(before or {})
        def descendant_depth(pid):
            depth=0; seen=set()
            while pid in all_after and pid not in seen and depth<12:
                seen.add(pid); parent=all_after[pid].get("ppid")
                if parent in new_pids:return depth+1
                pid=parent; depth+=1
            return 0
        for pid,proc in (after or {}).items():
            if pid in (before or {}):continue
            command=str(proc.get("cmdline") or ""); exe=str(proc.get("exe") or ""); name=str(proc.get("comm") or os.path.basename(exe))
            try:tokens=shlex.split(command)
            except ValueError:tokens=command.split()
            windows=next((token.strip('"\'') for token in reversed(tokens) if token.strip('"\'').casefold().endswith(".exe") and not cls._generic_runtime_helper(token.strip('"\''))),None)
            value=windows or exe or name
            if not value or cls._generic_runtime_helper(value):continue
            install_match=False
            for possible in (exe,windows):
                if not possible or not install_path:continue
                local=str(possible).replace("\\","/")
                if re.match(r"^[A-Za-z]:/",local):local=local[2:] if local[0].casefold()=="z" else local
                try:install_match=os.path.commonpath((install_path,os.path.realpath(local)))==install_path
                except (OSError,ValueError):pass
            if cls._runtime_infrastructure_process(proc) and not install_match and not windows:
                continue
            age=max(0.0,now-float((first_seen or {}).get(pid,now))); depth=descendant_depth(pid)
            host_helper=cls._generic_runtime_helper(name) or cls._generic_runtime_helper(exe)
            score=(70 if install_match else 0)+(35 if windows else 20 if exe else 5)+min(20,int(age*2))+(min(depth,4)*3)-(25 if host_helper else 0)
            classification=cls._runtime_process_classification(proc,windows)
            reasons=[]
            if install_match:reasons.append("inside selected game install tree")
            if windows:reasons.append("Windows game executable behind Wine/Proton")
            elif exe:reasons.append("resolved native executable path")
            if age>=3:reasons.append(f"observed for {age:.0f}s")
            if depth:reasons.append(f"new process-tree descendant (depth {depth})")
            if host_helper:reasons.append("generic host wrapper de-prioritized")
            signature={"kind":"windows_executable" if windows else "executable_path" if exe else "process_name","value":cls._runtime_basename(windows) if windows else value,"process_name":name,"executable_path":exe or None,"command_contains":cls._runtime_basename(windows) if windows else None,"observed_parent_pid":proc.get("ppid")}
            candidates.append({"pid":pid,"score":score,"signature":signature,"cmdline":command,"classification":classification,"reason":"; ".join(reasons) or "new same-user process","age_seconds":age,"install_tree_match":install_match,"parent_pid":proc.get("ppid")})
        dedup={}
        for candidate in candidates:
            key=cls._runtime_candidate_key(candidate); current=dedup.get(key)
            if current is None or (candidate["score"],candidate["age_seconds"],-candidate["pid"])>(current["score"],current["age_seconds"],-current["pid"]):dedup[key]=candidate
        return sorted(dedup.values(),key=lambda item:(-item["score"],-item["age_seconds"],item["pid"]))

    @staticmethod
    def _runtime_learning_decision(candidates,confirmed_index=None):
        if not candidates:return {"status":"none","signature":None}
        if confirmed_index is None:return {"status":"confirmation_required","signature":None,"candidates":candidates}
        if not (0<=confirmed_index<len(candidates)):return {"status":"cancelled","signature":None}
        return {"status":"confirmed","signature":candidates[confirmed_index]["signature"]}

    @staticmethod
    def _process_snapshot(proc_root="/proc"):
        result={}; uid=os.getuid()
        try:entries=os.scandir(proc_root)
        except (OSError,PermissionError):return result
        with entries:
            for entry in entries:
                if not entry.name.isdigit():continue
                try:
                    if entry.stat(follow_symlinks=False).st_uid!=uid:continue
                    cmd=pathlib.Path(entry.path,"cmdline").read_bytes().replace(b"\0",b" ").decode("utf-8","ignore").strip(); comm=pathlib.Path(entry.path,"comm").read_text(errors="ignore").strip()
                    try:exe=os.readlink(os.path.join(entry.path,"exe"))
                    except OSError:exe=""
                    stat=pathlib.Path(entry.path,"stat").read_text(errors="ignore"); close=stat.rfind(")"); fields=stat[close+2:].split(); ppid=int(fields[1]) if len(fields)>1 else None
                    steam_ids=[]
                    try:
                        env=pathlib.Path(entry.path,"environ").read_bytes()
                        for item in env.split(b"\0"):
                            match=re.match(br"(?:SteamAppId|SteamGameId|STEAM_COMPAT_APP_ID)=([0-9]+)$",item,re.I)
                            if match:steam_ids.append(match.group(1).decode("ascii"))
                            compat=re.match(br"STEAM_COMPAT_DATA_PATH=.*compatdata/([0-9]+)(?:/)?$",item,re.I)
                            if compat:steam_ids.append(compat.group(1).decode("ascii"))
                    except (OSError,PermissionError):pass
                    result[int(entry.name)]={"pid":int(entry.name),"cmdline":cmd,"comm":comm,"exe":exe,"ppid":ppid,"steam_appids":sorted(set(steam_ids))}
                except (OSError,PermissionError,ValueError):continue
        return result

    def _runtime_process_snapshot_cached(self,max_age=0.75):
        """Return the latest same-user /proc snapshot without blocking Tk.

        Runtime detection has multiple consumers (dashboard + automatic profile
        monitor).  A full /proc walk can take long enough to cause visible Tk
        scroll/tab hitches, especially when repeated by more than one consumer.
        Refresh the snapshot on a daemon worker and let UI callers use the most
        recently completed snapshot.  Detection can therefore lag process start
        by roughly one normal polling interval, but the UI thread never waits for
        the scan.
        """
        if not bool(self.__dict__.get("_runtime_nonblocking_enabled",False)):
            return self._process_snapshot()
        now=time.monotonic()
        cached=self.__dict__.get("_runtime_process_snapshot_cache")
        rows=cached[1] if cached else {}
        stamp=float(cached[0]) if cached else 0.0
        busy=bool(self.__dict__.get("_runtime_process_snapshot_busy",False))
        if (not busy) and (not cached or now-stamp>=float(max_age)):
            self.__dict__["_runtime_process_snapshot_busy"]=True
            def _refresh():
                try:
                    fresh=self._process_snapshot()
                    self.__dict__["_runtime_process_snapshot_cache"]=(time.monotonic(),fresh)
                finally:
                    self.__dict__["_runtime_process_snapshot_busy"]=False
            threading.Thread(target=_refresh,name="alcc-runtime-scan",daemon=True).start()
        return rows

    def _running_process_text(self,snapshot=None):
        rows=snapshot if isinstance(snapshot,dict) else self._runtime_process_snapshot_cached(); chunks=[]
        for proc in rows.values():
            chunks.extend((str(proc.get("comm") or ""),str(proc.get("cmdline") or ""),str(proc.get("exe") or "")))
            chunks.extend(f"steam_compat_app_id={appid}" for appid in proc.get("steam_appids",[]))
        return "\n".join(chunks).lower()

    @classmethod
    def _runtime_command_tokens(cls,value):
        """Tokenize /proc cmdline while retaining Windows/Proton path spelling."""
        text=str(value or "").replace("\0"," ")
        rows=re.findall(r'"([^"\n]*)"|\'([^\'\n]*)\'|([^\s]+)',text)
        return [next((part for part in row if part),"").strip() for row in rows if any(row)]

    @classmethod
    def _runtime_normalized_token(cls,value):
        value=str(value or "").strip().strip('"\'').replace("\\","/").rstrip("/")
        return value.casefold()

    @classmethod
    def _runtime_signature_process_match(cls,signature,proc):
        """Return exact field evidence for one learned signature/process pair."""
        if not isinstance(signature,dict) or not isinstance(proc,dict):return None
        kind=str(signature.get("kind") or ""); learned=str(signature.get("value") or signature.get("command_contains") or "").strip()
        if not learned or cls._generic_runtime_helper(learned):return None
        learned_norm=cls._runtime_normalized_token(learned); learned_base=cls._runtime_basename(learned_norm).casefold()
        comm=str(proc.get("comm") or ""); exe=str(proc.get("exe") or ""); tokens=cls._runtime_command_tokens(proc.get("cmdline"))
        fields=[("comm",comm),("exe",exe)]+[("cmdline token",token) for token in tokens]
        for field,value in fields:
            normalized=cls._runtime_normalized_token(value); basename=cls._runtime_basename(normalized).casefold()
            if kind=="executable_path" and field=="exe" and normalized==learned_norm:return {"field":field,"value":value}
            if kind=="process_name" and field=="comm" and basename==learned_base:return {"field":field,"value":value}
            if kind=="windows_executable" and learned_base.endswith(".exe") and basename==learned_base and not cls._generic_runtime_helper(basename):return {"field":field,"value":value}
            # Compatibility for v0.87.0/v0.87.1 signatures: command_contains was
            # intended as an executable basename, never an unrestricted substring.
            if signature.get("command_contains") and basename==cls._runtime_basename(signature["command_contains"]).casefold() and field=="cmdline token":return {"field":field,"value":value}
        return None

    @staticmethod
    def _runtime_process_steam_ids(proc):
        ids={str(value) for value in proc.get("steam_appids",[]) if str(value).isdigit()}
        text=str(proc.get("cmdline") or "")
        patterns=(r"steam(?:launch\s+)?appid\s*[= ]\s*([0-9]+)",r"steam_compat_app_id=([0-9]+)",r"compatdata[/\\]([0-9]+)",r"steam://rungameid/([0-9]+)")
        for pattern in patterns:ids.update(re.findall(pattern,text,re.I))
        return ids

    def _runtime_game_records(self):
        now=time.monotonic(); cached=self.__dict__.get("_runtime_game_cache")
        if cached and now-cached[0]<15:return cached[1]
        records=list(self.__dict__.get("unified_games",[]) or [])
        if not records:
            try:records=self._discover_unified_games()
            except Exception:records=[]
        known={str(row.get("game_id")):row for row in records if isinstance(row,dict)}
        for game_id,signatures in self.game_profile_data.get("game_runtime_signatures",{}).items():
            if game_id not in known:
                provider,_,provider_id=str(game_id).partition(":")
                known[game_id]=normalized_game_record(game_id=game_id,provider=provider,provider_id=provider_id,display_name=f"Steam AppID {provider_id}" if provider=="steam" else "Registered game",runtime_signatures=signatures)
            else:known[game_id]["runtime_signatures"]=list(signatures if isinstance(signatures,list) else [])
        for rule in self.game_profile_data.get("rules",[]):
            appid=str(rule.get("steam_appid") or ""); game_id=str(rule.get("alcc_game_id") or (f"steam:{appid}" if appid else ""))
            if not game_id or game_id in known:continue
            known[game_id]=normalized_game_record(game_id=game_id,provider="steam" if appid else "manual",provider_id=appid or None,display_name=rule.get("steam_title") or rule.get("title") or rule.get("match") or "Configured game",runtime_signatures=self.game_profile_data.get("game_runtime_signatures",{}).get(game_id,[]))
        records=list(known.values()); self._runtime_game_cache=(now,records); return records

    def _runtime_rule_for_game(self,game):
        if game.get("steam_appid"):hit=self._rule_for_steam_appid(game["steam_appid"])
        else:hit=self._rule_for_alcc_game_id(game.get("game_id"))
        return hit

    def _runtime_unconfigured_rule(self,game):
        return {"match":game.get("display_name") or "Game","steam_title":game.get("display_name") or "Game","steam_appid":str(game.get("steam_appid") or ""),"alcc_game_id":game.get("game_id"),"profile":"","profile_type":"none","graphics_preset":"","_runtime_unconfigured":True}

    def _detect_runtime_game(self,snapshot=None,games=None):
        """Canonical provider-neutral identity matcher for every runtime consumer."""
        processes=snapshot if isinstance(snapshot,dict) else self._runtime_process_snapshot_cached(); records=list(games if games is not None else self._runtime_game_records())
        # Steam AppID is strongest where the runtime exposes it.
        for game in records:
            appid=str(game.get("steam_appid") or "")
            if not appid:continue
            for pid,proc in processes.items():
                if appid in self._runtime_process_steam_ids(proc):
                    hit=self._runtime_rule_for_game(game); rule=hit[1] if hit else self._runtime_unconfigured_rule(game)
                    return {"game":game,"game_id":game.get("game_id"),"steam_appid":appid,"pid":pid,"field":"Steam AppID","value":appid,"rule_hit":hit,"hit":hit or (f"game:{game.get('game_id')}",rule),"configured":bool(hit)}
        # Confirmed learned signatures augment AppID detection and survive final
        # Proton process handoff when Steam identity variables are absent.
        store=self.game_profile_data.get("game_runtime_signatures",{})
        for game in records:
            for signature in store.get(str(game.get("game_id")),game.get("runtime_signatures",[])):
                for pid,proc in processes.items():
                    evidence=self._runtime_signature_process_match(signature,proc)
                    if evidence:
                        hit=self._runtime_rule_for_game(game); rule=hit[1] if hit else self._runtime_unconfigured_rule(game)
                        return {"game":game,"game_id":game.get("game_id"),"steam_appid":str(game.get("steam_appid") or ""),"pid":pid,"field":evidence["field"],"value":evidence["value"],"signature":signature,"rule_hit":hit,"hit":hit or (f"game:{game.get('game_id')}",rule),"configured":bool(hit)}
        return None
