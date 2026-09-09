import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import alcc_storage as storage


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.dir = pathlib.Path(self.root.name)

    def path(self, name):
        return str(self.dir / name)

    def test_profiles_missing_and_round_trip(self):
        path = self.path("profiles.json")
        self.assertEqual(storage.load_profiles(path), {"profiles": {}})
        payload = {"profiles": {"Gaming": {"power": 200}}}
        storage.save_profiles(path, payload)
        self.assertEqual(storage.load_profiles(path), payload)
        self.assertFalse(pathlib.Path(path + ".tmp").exists())

    def test_malformed_json_falls_back(self):
        path = pathlib.Path(self.path("app_settings.json"))
        path.write_text("{broken", encoding="utf-8")
        self.assertEqual(storage.load_app_settings(str(path)), storage.app_settings_defaults())

    def test_app_settings_merge_defaults(self):
        path = self.path("app_settings.json")
        pathlib.Path(path).write_text(json.dumps({"start_minimized": True}), encoding="utf-8")
        data = storage.load_app_settings(path)
        self.assertTrue(data["start_minimized"])
        self.assertTrue(data["close_to_tray"])
        self.assertEqual(data["startup_profile"], "Do nothing")

    def test_game_profile_normalization(self):
        path = self.path("game_profiles.json")
        pathlib.Path(path).write_text(json.dumps({"manual_games": {}, "graphics_presets": [], "telemetry_policy": []}), encoding="utf-8")
        data = storage.load_game_profiles(path)
        self.assertEqual(data["manual_games"], [])
        self.assertEqual(data["graphics_presets"], {})
        self.assertEqual(data["telemetry_policy"], {})
        self.assertIn("global_upscaling", data)

    def test_history_retains_latest_100(self):
        path = self.path("history.json")
        storage.save_game_session_history(path, {"sessions": [{"n": i} for i in range(125)]})
        sessions = storage.load_game_session_history(path)["sessions"]
        self.assertEqual(len(sessions), 100)
        self.assertEqual(sessions[0]["n"], 25)
        self.assertEqual(sessions[-1]["n"], 124)

    def test_trials_format_and_retention(self):
        path = self.path("trials.json")
        storage.save_optimization_trials(path, {"trials": [{"n": i} for i in range(60)], "active_trial_id": "x"}, 1)
        data = storage.load_optimization_trials(path, 1)
        self.assertEqual(len(data["trials"]), 50)
        self.assertEqual(data["trials"][0]["n"], 10)
        self.assertEqual(data["active_trial_id"], "x")
        self.assertEqual(storage.load_optimization_trials(path, 2)["trials"], [])

    def test_trials_ignore_non_dict_rows_on_load(self):
        path = self.path("trials.json")
        pathlib.Path(path).write_text(json.dumps({"format_version": 1, "trials": [1, {"ok": True}], "active_trial_id": None}), encoding="utf-8")
        self.assertEqual(storage.load_optimization_trials(path, 1)["trials"], [{"ok": True}])

    def test_game_profiles_round_trip(self):
        path = self.path("game_profiles.json")
        payload = storage.game_profile_defaults(); payload["enabled"] = True
        storage.save_game_profiles(path, payload)
        self.assertTrue(storage.load_game_profiles(path)["enabled"])


if __name__ == "__main__":
    unittest.main()
