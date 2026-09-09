import os, pathlib, sys, tempfile, time
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/"app"))
from alcc_steam_discovery import *


def manifest(path,appid,name,installdir="Game"):
    pathlib.Path(path).write_text(f'"AppState"\n{{\n"appid" "{appid}"\n"name" "{name}"\n"installdir" "{installdir}"\n}}\n')


def test_manifest_parse_and_runtime_filter():
    with tempfile.TemporaryDirectory() as td:
        p=os.path.join(td,"appmanifest_1.acf"); manifest(p,"1","Real Game","RealGame")
        row=parse_appmanifest(p,td)
        assert row["appid"]=="1" and row["name"]=="Real Game" and row["installdir"]=="RealGame"
    assert manifest_is_game({"name":"Valheim"})
    assert not manifest_is_game({"name":"Proton Experimental"})
    assert not manifest_is_game({"name":"Steam Linux Runtime 3.0 (sniper)"})
    assert not manifest_is_game({"name":"Proton EasyAntiCheat Runtime"})


def test_library_and_game_discovery_deduplicates_and_filters():
    with tempfile.TemporaryDirectory() as td:
        root=os.path.join(td,"Steam"); extra=os.path.join(td,"Extra")
        os.makedirs(os.path.join(root,"steamapps")); os.makedirs(os.path.join(extra,"steamapps"))
        pathlib.Path(os.path.join(root,"steamapps","libraryfolders.vdf")).write_text(f'"path" "{extra}"\n')
        manifest(os.path.join(root,"steamapps","appmanifest_10.acf"),"10","Game B")
        manifest(os.path.join(extra,"steamapps","appmanifest_20.acf"),"20","Game A")
        manifest(os.path.join(extra,"steamapps","appmanifest_30.acf"),"30","Proton Hotfix")
        libs=library_paths([root])
        assert libs==[os.path.realpath(root),os.path.realpath(extra)]
        games=detect_games([root])
        assert [g["appid"] for g in games]==["20","10"]


def test_localconfig_candidates_newest_first():
    with tempfile.TemporaryDirectory() as td:
        root=os.path.join(td,"Steam")
        p1=os.path.join(root,"userdata","111","config","localconfig.vdf")
        p2=os.path.join(root,"userdata","222","config","localconfig.vdf")
        os.makedirs(os.path.dirname(p1)); os.makedirs(os.path.dirname(p2))
        pathlib.Path(p1).write_text("one"); pathlib.Path(p2).write_text("two")
        os.utime(p1,(100,100)); os.utime(p2,(200,200))
        rows=localconfig_candidates([root])
        assert [r["uid"] for r in rows]==["222","111"]


def test_process_running_from_fake_proc():
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td,"10")); pathlib.Path(td,"10","comm").write_text("bash\n")
        assert not process_running(td)
        os.makedirs(os.path.join(td,"20")); pathlib.Path(td,"20","comm").write_text("steamwebhelper\n")
        assert process_running(td)


def _fake_proc_entry(root,pid,comm,uid):
    d=pathlib.Path(root,str(pid)); d.mkdir()
    (d/"comm").write_text(comm+"\n")
    (d/"status").write_text(f"Name:\t{comm}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")


def test_client_pids_only_returns_same_user_real_steam_client():
    with tempfile.TemporaryDirectory() as td:
        _fake_proc_entry(td,10,"steam",1000)
        _fake_proc_entry(td,11,"steamwebhelper",1000)
        _fake_proc_entry(td,12,"steam",2000)
        _fake_proc_entry(td,13,"steam-runtime-supervisor",1000)
        assert client_pids(td,uid=1000)==[10]


def test_client_pids_ignores_zombie_steam_client():
    with tempfile.TemporaryDirectory() as td:
        _fake_proc_entry(td,20,"steam",1000)
        status=pathlib.Path(td,"20","status")
        status.write_text("Name:\tsteam\nState:\tZ (zombie)\nUid:\t1000\t1000\t1000\t1000\n")
        assert client_pids(td,uid=1000)==[]


def test_process_running_ignores_zombie_steam_helper():
    with tempfile.TemporaryDirectory() as td:
        _fake_proc_entry(td,21,"steamwebhelper",1000)
        status=pathlib.Path(td,"21","status")
        status.write_text("Name:\tsteamwebhelper\nState:\tZ (zombie)\nUid:\t1000\t1000\t1000\t1000\n")
        assert not process_running(td)
