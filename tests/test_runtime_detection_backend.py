import os,sys,time,threading,unittest
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,os.path.join(ROOT,'app'))
from alcc_runtime_detection import RuntimeDetectionMixin
from amd_linux_control_center import App


class Dummy(RuntimeDetectionMixin):
    def __init__(self):
        self.game_profile_data={'game_runtime_signatures':{},'rules':[]}
        self.unified_games=[]
    def _rule_for_steam_appid(self,appid):
        for i,row in enumerate(self.game_profile_data.get('rules',[])):
            if str(row.get('steam_appid') or '')==str(appid):return (i,row)
        return None
    def _rule_for_alcc_game_id(self,game_id):
        for i,row in enumerate(self.game_profile_data.get('rules',[])):
            if str(row.get('alcc_game_id') or '')==str(game_id):return (i,row)
        return None
    def _discover_unified_games(self):
        return list(self.unified_games)


class RuntimeDetectionExtractionTests(unittest.TestCase):
    def test_app_uses_runtime_detection_mixin(self):
        self.assertTrue(issubclass(App,RuntimeDetectionMixin))
        self.assertNotIn('_detect_runtime_game',App.__dict__)
        self.assertIn('_detect_runtime_game',RuntimeDetectionMixin.__dict__)

    def test_generic_runtime_helpers_are_rejected(self):
        self.assertTrue(RuntimeDetectionMixin._generic_runtime_helper('/usr/bin/steam'))
        self.assertTrue(RuntimeDetectionMixin._generic_runtime_helper('wine64'))
        self.assertFalse(RuntimeDetectionMixin._generic_runtime_helper('valheim.x86_64'))

    def test_bazzite_runtime_infrastructure_is_not_a_game_candidate(self):
        before={1:{'pid':1}}
        after={
            1:{'pid':1},
            10:{'pid':10,'ppid':1,'cmdline':'/app/vivaldi/vivaldi --type=renderer','exe':'/app/vivaldi/vivaldi','comm':'vivaldi','steam_appids':[]},
            11:{'pid':11,'ppid':1,'cmdline':'steam-runtime-launcher-service --alongside-steam','exe':'/var/home/u/.local/share/Steam/steamrt64/steam-runtime-launcher-service','comm':'steam-runtime-launcher-service','steam_appids':[]},
            12:{'pid':12,'ppid':1,'cmdline':'/usr/lib/pressure-vessel/from-host/libexec/steam-runtime-tools-0/pressure-vessel-wrap','exe':'/usr/lib/pressure-vessel/from-host/libexec/pressure-vessel-wrap','comm':'pressure-vessel-wrap','steam_appids':[]},
        }
        rows=RuntimeDetectionMixin._runtime_candidates(before,after,game={'provider':'steam','install_path':'/games/Dispatch'},first_seen={10:90,11:90,12:90},now=100)
        self.assertEqual(rows,[])

    def test_selected_steam_launch_requires_target_appid_after_learning_started(self):
        game={'provider':'steam','steam_appid':'2592160','display_name':'Dispatch'}
        before={1:{'pid':1,'ppid':0,'cmdline':'steam','exe':'/usr/bin/steam','comm':'steam','steam_appids':[]}}
        no_game={**before,10:{'pid':10,'ppid':1,'cmdline':'steam-runtime-launcher-service','exe':'/x/steam-runtime-launcher-service','comm':'steam-runtime-launcher-service','steam_appids':[]}}
        self.assertFalse(RuntimeDetectionMixin._runtime_selected_steam_launch_seen(before,no_game,game))
        launched={**no_game,20:{'pid':20,'ppid':1,'cmdline':'pressure-vessel-wrap','exe':'/usr/bin/pressure-vessel-wrap','comm':'pressure-vessel-wrap','steam_appids':['2592160']}}
        self.assertTrue(RuntimeDetectionMixin._runtime_selected_steam_launch_seen(before,launched,game))

    def test_selected_steam_launch_can_inherit_appid_from_new_parent(self):
        game={'provider':'steam','steam_appid':'2592160'}
        before={1:{'pid':1,'ppid':0,'cmdline':'steam','exe':'/usr/bin/steam','comm':'steam','steam_appids':[]}}
        after={**before,20:{'pid':20,'ppid':1,'cmdline':'pressure-vessel-wrap','exe':'/usr/bin/pressure-vessel-wrap','comm':'pressure-vessel-wrap','steam_appids':['2592160']},21:{'pid':21,'ppid':20,'cmdline':'Dispatch.exe','exe':'/usr/bin/wine64','comm':'wine64','steam_appids':[]}}
        self.assertTrue(RuntimeDetectionMixin._runtime_selected_steam_launch_seen(before,after,game))

    def test_runtime_candidates_prefer_selected_install_tree(self):
        before={1:{'pid':1}}
        after={
            1:{'pid':1},
            10:{'pid':10,'ppid':1,'cmdline':'/games/Valheim/valheim.x86_64','exe':'/games/Valheim/valheim.x86_64','comm':'valheim.x86_64'},
            11:{'pid':11,'ppid':1,'cmdline':'/usr/bin/pressure-vessel-wrap','exe':'/usr/bin/pressure-vessel-wrap','comm':'pressure-vessel-wrap'},
        }
        rows=RuntimeDetectionMixin._runtime_candidates(before,after,game={'install_path':'/games/Valheim'},first_seen={10:90,11:90},now=100)
        self.assertEqual(rows[0]['pid'],10)
        self.assertTrue(rows[0]['install_tree_match'])

    def test_exact_windows_signature_token_match(self):
        sig={'kind':'windows_executable','value':'valheim.exe','command_contains':'valheim.exe'}
        good={'cmdline':'wine64 "Z:\\games\\valheim.exe" -windowed','exe':'/usr/bin/wine64','comm':'wine64'}
        bad={'cmdline':'wine64 Z:\\games\\not-valheim.exe-helper','exe':'/usr/bin/wine64','comm':'wine64'}
        self.assertIsNotNone(RuntimeDetectionMixin._runtime_signature_process_match(sig,good))
        self.assertIsNone(RuntimeDetectionMixin._runtime_signature_process_match(sig,bad))

    def test_steam_identity_is_strongest_runtime_match(self):
        app=Dummy()
        game={'game_id':'steam:892970','provider':'steam','steam_appid':'892970','display_name':'Valheim','runtime_signatures':[]}
        app.unified_games=[game]
        snapshot={77:{'pid':77,'cmdline':'valheim.x86_64','comm':'valheim.x86_64','exe':'/games/Valheim/valheim.x86_64','steam_appids':['892970']}}
        found=app._detect_runtime_game(snapshot=snapshot,games=[game])
        self.assertEqual(found['game_id'],'steam:892970')
        self.assertEqual(found['field'],'Steam AppID')
        self.assertFalse(found['configured'])

    def test_learned_signature_survives_missing_steam_environment(self):
        app=Dummy()
        game={'game_id':'steam:892970','provider':'steam','steam_appid':'892970','display_name':'Valheim','runtime_signatures':[]}
        app.game_profile_data['game_runtime_signatures']={'steam:892970':[{'kind':'executable_path','value':'/games/Valheim/valheim.x86_64'}]}
        snapshot={88:{'pid':88,'cmdline':'/games/Valheim/valheim.x86_64','comm':'valheim.x86_64','exe':'/games/Valheim/valheim.x86_64','steam_appids':[]}}
        found=app._detect_runtime_game(snapshot=snapshot,games=[game])
        self.assertEqual(found['game_id'],'steam:892970')
        self.assertEqual(found['field'],'exe')

    def test_process_steam_ids_accepts_legacy_command_evidence(self):
        ids=RuntimeDetectionMixin._runtime_process_steam_ids({'steam_appids':['111'],'cmdline':'STEAM_COMPAT_APP_ID=892970 /x/compatdata/555/ steam://rungameid/444'})
        self.assertEqual(ids,{'111','892970','555','444'})

    def test_runtime_snapshot_refresh_is_nonblocking_and_cached(self):
        app=Dummy(); app._runtime_nonblocking_enabled=True; started=threading.Event(); release=threading.Event()
        snapshot={77:{'pid':77,'cmdline':'valheim.x86_64','comm':'valheim.x86_64','exe':'/games/Valheim/valheim.x86_64','steam_appids':['892970']}}
        def slow_snapshot():
            started.set(); release.wait(1.0); return snapshot
        app._process_snapshot=slow_snapshot
        begin=time.monotonic(); first=app._runtime_process_snapshot_cached(max_age=0.0); elapsed=time.monotonic()-begin
        self.assertEqual(first,{})
        self.assertLess(elapsed,0.10)
        self.assertTrue(started.wait(0.5))
        release.set()
        deadline=time.monotonic()+1.0
        while time.monotonic()<deadline and not app.__dict__.get('_runtime_process_snapshot_cache'):
            time.sleep(0.01)
        second=app._runtime_process_snapshot_cached(max_age=60.0)
        self.assertEqual(second,snapshot)

if __name__=='__main__':unittest.main()
