#!/usr/bin/env python3
"""Launch Gamescope while asking KWin/Wayland to place its outer window on a named output.

This helper is intentionally narrow.  It is only used by ALCC on KDE Plasma Wayland
when a user explicitly chooses a preferred monitor.  If KWin scripting is unavailable,
it falls back to launching the command unchanged rather than blocking the game.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import threading
import time


def _log(message: str) -> None:
    try:
        path = pathlib.Path.home()/".config"/"amd-linux-control-center"/"kwin-placement.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    except Exception:
        pass


def _qdbus() -> str | None:
    for name in ("qdbus-qt6", "qdbus6", "qdbus"):
        hit = shutil.which(name)
        if hit:
            return hit
    return None


def _js_for_output(output_name: str, expected_pid: int) -> str:
    target = json.dumps(str(output_name))
    pid = int(expected_pid)
    return f'''const targetName = {target};
const expectedPid = {pid};
let placedWindow = null;
let baselineIds = {{}};

function idOf(w) {{
    try {{ return String(w.internalId || w.windowId || ""); }} catch (e) {{ return ""; }}
}}
function rememberBaseline() {{
    const list = workspace.stackingOrder || [];
    for (let i = 0; i < list.length; ++i) baselineIds[idOf(list[i])] = true;
}}
function targetOutput() {{
    const screens = workspace.screens || [];
    for (let i = 0; i < screens.length; ++i) {{
        const s = screens[i];
        if (String(s.name || "") === targetName) return s;
    }}
    return null;
}}
function text(v) {{ try {{ return String(v || "").toLowerCase(); }} catch (e) {{ return ""; }} }}
function directMatch(w) {{
    if (!w) return false;
    try {{ if (Number(w.pid || -1) === expectedPid) return true; }} catch (e) {{}}
    const rc = text(w.resourceClass);
    const rn = text(w.resourceName);
    const cap = text(w.caption);
    return rc.indexOf("gamescope") >= 0 || rn.indexOf("gamescope") >= 0 || cap.indexOf("gamescope") >= 0;
}}
function newFullscreenCandidate(w) {{
    if (!w) return false;
    const wid = idOf(w);
    if (wid && baselineIds[wid]) return false;
    try {{
        if (w.desktopWindow || w.dock || w.notification || w.popupWindow || !w.managed) return false;
    }} catch (e) {{}}
    try {{ if (w.fullScreen === true) return true; }} catch (e) {{}}
    return false;
}}
function enforce(w, reason) {{
    if (!w) return false;
    const out = targetOutput();
    if (!out) {{ print("ALCC_KWIN_OUTPUT_NOT_FOUND " + targetName); return false; }}
    try {{
        const wasFull = (w.fullScreen === true);
        // On Plasma 6 a fullscreen Wayland/XWayland client can immediately re-assert
        // placement on the cursor screen.  Move it while temporarily non-fullscreen,
        // then restore fullscreen and keep an outputChanged guard attached.
        if (wasFull) w.fullScreen = false;
        workspace.sendClientToScreen(w, out);
        if (wasFull) w.fullScreen = true;
        placedWindow = w;
        print("ALCC_KWIN_PLACED " + targetName + " reason=" + reason + " pid=" + String(w.pid || -1));
        try {{
            w.outputChanged.connect(function() {{
                try {{
                    if (placedWindow !== w) return;
                    const want = targetOutput();
                    if (want && w.output !== want) workspace.sendClientToScreen(w, want);
                }} catch (e) {{}}
            }});
        }} catch (e) {{}}
        return true;
    }} catch (e) {{
        print("ALCC_KWIN_PLACE_FAILED " + targetName + " " + e);
        return false;
    }}
}}
function consider(w, reason) {{
    if (!w) return;
    if (directMatch(w)) {{ enforce(w, reason + ":direct"); return; }}
    // Gamescope's managed outer client can be owned by an SDL/XWayland helper PID
    // instead of the process PID we launched.  A newly-added fullscreen client while
    // this one-shot script is armed is therefore the safe fallback.
    if (newFullscreenCandidate(w)) enforce(w, reason + ":new-fullscreen");
}}

rememberBaseline();
workspace.windowAdded.connect(function(w) {{ consider(w, "windowAdded"); }});
workspace.windowActivated.connect(function(w) {{ consider(w, "windowActivated"); }});
const existing = workspace.stackingOrder || [];
for (let i = 0; i < existing.length; ++i) consider(existing[i], "initial-scan");
'''

def _load_kwin_script(output_name: str, expected_pid: int):
    qdbus = _qdbus()
    if not qdbus:
        _log("KWin placement unavailable: qdbus executable not found")
        return None
    runtime = pathlib.Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
    runtime.mkdir(parents=True, exist_ok=True)
    fd, script_path = tempfile.mkstemp(prefix="alcc-kwin-place-", suffix=".js", dir=str(runtime))
    os.close(fd)
    pathlib.Path(script_path).write_text(_js_for_output(output_name, expected_pid), encoding="utf-8")
    label = f"alcc-place-{os.getpid()}"
    try:
        load = subprocess.run(
            [qdbus, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.loadScript", script_path, label],
            check=True, capture_output=True, text=True, timeout=5,
        )
        script_id = (load.stdout or "").strip().splitlines()[-1].strip()
        if not script_id or not script_id.lstrip("-").isdigit():
            raise RuntimeError(f"unexpected KWin script id: {script_id!r}")
        obj = f"/Scripting/Script{script_id}"
        subprocess.run([qdbus, "org.kde.KWin", obj, "org.kde.kwin.Script.run"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        _log(f"KWin placement armed for output={output_name!r} pid={expected_pid} script_id={script_id}")
        return qdbus, obj, label, script_path
    except Exception as exc:
        _log(f"KWin placement setup failed for output={output_name!r}: {exc}")
        try:
            os.unlink(script_path)
        except OSError:
            pass
        return None


def _cleanup_later(state, delay: float = 20.0) -> None:
    if not state:
        return
    qdbus, obj, label, script_path = state
    def worker():
        time.sleep(delay)
        try:
            subprocess.run([qdbus, "org.kde.KWin", obj, "org.kde.kwin.Script.stop"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except Exception:
            pass
        try:
            subprocess.run([qdbus, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript", label],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except Exception:
            pass
        try:
            os.unlink(script_path)
        except OSError:
            pass
        _log(f"KWin placement helper cleanup complete label={label!r}")
    threading.Thread(target=worker, daemon=True).start()


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--output", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    ns = parser.parse_args()
    command = list(ns.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        _log("No command supplied to KWin placement helper")
        return 2

    desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or "").lower()
    session = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
    state = None
    try:
        # Start Gamescope first so KWin matching can use its real PID.  The script
        # immediately scans stackingOrder as well as listening for windowAdded,
        # so it is safe whether the SDL window appears just before or after the
        # script is armed.
        proc = subprocess.Popen(command)
        if session == "wayland" and ("kde" in desktop or "plasma" in desktop):
            state = _load_kwin_script(ns.output, proc.pid)
        else:
            _log(f"KWin placement bypassed: desktop={desktop!r} session={session!r}")
        _cleanup_later(state)
        _log(f"Gamescope launched pid={proc.pid} target_output={ns.output!r}")
        return proc.wait()
    except FileNotFoundError as exc:
        _log(f"Launch failed: {exc}")
        return 127
    except Exception as exc:
        _log(f"Launch failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
