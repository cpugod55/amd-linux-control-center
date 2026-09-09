"""Steam installation/account discovery helpers for AMD Linux Control Center.

No Tk/UI, GPU writes, Steam shutdown/startup, or configuration writes live here.
The helpers only inspect the local Steam layout and process table and return
plain data for the orchestration layer.
"""
import os
import pathlib
import re


def root_candidates(home=None):
    home=os.path.expanduser(home or "~")
    roots=[
        os.path.join(home,".local/share/Steam"),
        os.path.join(home,".steam/root"),
        os.path.join(home,".steam/steam"),
        os.path.join(home,".var/app/com.valvesoftware.Steam/.local/share/Steam"),
        os.path.join(home,"snap/steam/common/.local/share/Steam"),
    ]
    out=[]; seen=set()
    for root in roots:
        real=os.path.realpath(root)
        if os.path.isdir(real) and real not in seen:
            seen.add(real); out.append(real)
    return out


def library_paths(roots):
    libs=[]; seen=set()
    for root in roots or ():
        real=os.path.realpath(root)
        if os.path.isdir(os.path.join(real,"steamapps")) and real not in seen:
            seen.add(real); libs.append(real)
        vdf=os.path.join(root,"steamapps","libraryfolders.vdf")
        if os.path.isfile(vdf):
            try:
                text=pathlib.Path(vdf).read_text(encoding="utf-8",errors="ignore")
                for path in re.findall(r'"path"\s*"([^"]+)"',text,re.I):
                    path=path.replace("\\\\","\\")
                    candidate=os.path.realpath(os.path.expanduser(path))
                    if os.path.isdir(os.path.join(candidate,"steamapps")) and candidate not in seen:
                        seen.add(candidate); libs.append(candidate)
            except Exception:
                pass
    return libs


def parse_appmanifest(path,library):
    try:text=pathlib.Path(path).read_text(encoding="utf-8",errors="ignore")
    except Exception:return None
    def field(name):
        m=re.search(r'"'+re.escape(name)+r'"\s*"([^"]*)"',text,re.I)
        return m.group(1).strip() if m else ""
    appid=field("appid"); name=field("name"); installdir=field("installdir")
    if not appid or not name:return None
    return {"appid":appid,"name":name,"installdir":installdir,"library":library,"manifest":path}


def manifest_is_game(game):
    if not game:return False
    low=str(game.get("name","") or "").strip().lower()
    exact_block={
        "steam linux runtime","steam linux runtime 1.0 (scout)",
        "steam linux runtime 2.0 (soldier)","steam linux runtime 3.0 (sniper)",
        "steam linux runtime 4.0","proton easyanticheat runtime","proton battleye runtime",
    }
    if low in exact_block:return False
    if low.startswith(("proton ","steam linux runtime","steamworks common redistributables")):return False
    if any(term in low for term in ("steam linux runtime","proton experimental","proton hotfix","easyanticheat runtime","battleye runtime")):return False
    return True


def detect_games(roots):
    games=[]
    for lib in library_paths(roots):
        steamapps=os.path.join(lib,"steamapps")
        try:names=os.listdir(steamapps)
        except Exception:continue
        for fn in names:
            if not (fn.startswith("appmanifest_") and fn.endswith(".acf")):continue
            game=parse_appmanifest(os.path.join(steamapps,fn),lib)
            if game and manifest_is_game(game):games.append(game)
    dedup={game["appid"]:game for game in games}
    return sorted(dedup.values(),key=lambda game:game["name"].lower())


def localconfig_candidates(roots):
    found=[]; seen=set()
    for root in roots or ():
        userdata=os.path.join(root,"userdata")
        if not os.path.isdir(userdata):continue
        try:userdirs=os.listdir(userdata)
        except Exception:continue
        for uid in userdirs:
            if not uid.isdigit():continue
            path=os.path.realpath(os.path.join(userdata,uid,"config","localconfig.vdf"))
            if path in seen or not os.path.isfile(path):continue
            seen.add(path)
            try:mtime=os.path.getmtime(path)
            except Exception:mtime=0
            found.append({"uid":uid,"path":path,"mtime":mtime,"root":root})
    return sorted(found,key=lambda item:item["mtime"],reverse=True)


def _proc_is_zombie(proc_dir):
    """Return True when a /proc PID entry is a zombie and cannot write Steam config."""
    try:
        status=pathlib.Path(proc_dir,"status").read_text(errors="ignore")
        m=re.search(r"^State:\s+([A-Z])",status,re.MULTILINE)
        return bool(m and m.group(1)=="Z")
    except Exception:
        return False


def process_running(proc_root="/proc"):
    names={"steam","steamwebhelper","steam-runtime-supervisor"}
    try:
        entries=os.scandir(proc_root)
    except Exception:return False
    try:
        for entry in entries:
            if not entry.name.isdigit():continue
            try:
                comm=pathlib.Path(entry.path,"comm").read_text(errors="ignore").strip().lower()
                if comm in names and not _proc_is_zombie(entry.path):return True
            except Exception:pass
    finally:
        try:entries.close()
        except Exception:pass
    return False


def client_pids(proc_root="/proc", uid=None):
    """Return live same-user PIDs whose process name is exactly the Steam client."""
    if uid is None:
        try:
            uid=os.getuid()
        except Exception:
            uid=None
    found=[]
    try:
        entries=os.scandir(proc_root)
    except Exception:
        return found
    try:
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                comm=pathlib.Path(entry.path,"comm").read_text(errors="ignore").strip().lower()
                if comm!="steam":
                    continue
                # A terminated Steam process can remain as a zombie until its
                # parent reaps it. It has no userspace execution left and cannot
                # rewrite localconfig.vdf, so it must not block a guarded write.
                if _proc_is_zombie(entry.path):
                    continue
                if uid is not None:
                    status=pathlib.Path(entry.path,"status").read_text(errors="ignore")
                    m=re.search(r"^Uid:\s+(\d+)",status,re.MULTILINE)
                    if not m or int(m.group(1))!=int(uid):
                        continue
                found.append(int(entry.name))
            except Exception:
                pass
    finally:
        try:
            entries.close()
        except Exception:
            pass
    return sorted(set(found))
