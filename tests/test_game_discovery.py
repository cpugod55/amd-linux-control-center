import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from alcc_game_discovery import ManualGameProvider, SteamGameProvider, normalized_game_record, stable_game_id


class GameDiscoveryTests(unittest.TestCase):
    def _library(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "steamapps"))
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        return root

    def _manifest(self, root, appid="3079210", name="Hell Let Loose: Vietnam", installdir="HLL"):
        path = pathlib.Path(root, "steamapps", f"appmanifest_{appid}.acf")
        path.write_text(
            f'"AppState" {{ "appid" "{appid}" "name" "{name}" "installdir" "{installdir}" "StateFlags" "4" }}',
            encoding="utf-8",
        )
        return path

    def test_steam_identity_is_appid(self):
        self.assertEqual(stable_game_id("steam", "3079210"), "steam:3079210")

    def test_manual_identity_is_stable_and_target_sensitive(self):
        a = stable_game_id("manual", launch_target="/games/a")
        self.assertEqual(a, stable_game_id("manual", launch_target="/games/a"))
        self.assertNotEqual(a, stable_game_id("manual", launch_target="/games/b"))

    def test_normalized_runtime_ready_depends_on_signatures(self):
        base = normalized_game_record(provider="steam", provider_id="1", display_name="Installed", installed=True)
        ready = normalized_game_record(provider="steam", provider_id="1", display_name="Installed", runtime_signatures=[{"kind":"exe","value":"game.exe"}])
        self.assertFalse(base["runtime_ready"])
        self.assertTrue(ready["runtime_ready"])

    def test_manifest_discovery(self):
        root = self._library()
        self._manifest(root)
        found = SteamGameProvider([root]).discover()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["steam_appid"], "3079210")
        self.assertEqual(found[0]["game_id"], "steam:3079210")
        self.assertTrue(found[0]["installed"])

    def test_multiple_libraries_and_appid_deduplication(self):
        a, b = self._library(), self._library()
        self._manifest(a, "10", "A", "A")
        self._manifest(b, "20", "B", "B")
        self.assertEqual(len(SteamGameProvider([a, b]).discover()), 2)
        self._manifest(b, "10", "A duplicate", "A")
        found = SteamGameProvider([a, b]).discover()
        self.assertEqual({g["steam_appid"] for g in found}, {"10", "20"})

    def test_libraryfolders_vdf(self):
        root, second = self._library(), self._library()
        pathlib.Path(root, "steamapps", "libraryfolders.vdf").write_text(
            f'"libraryfolders" {{ "1" {{ "path" "{second}" }} }}', encoding="utf-8"
        )
        self.assertIn(second, SteamGameProvider([root]).library_paths())

    def test_malformed_manifest_is_ignored(self):
        root = self._library()
        pathlib.Path(root, "steamapps", "appmanifest_bad.acf").write_text("not vdf", encoding="utf-8")
        self.assertEqual(SteamGameProvider([root]).discover(), [])

    def test_manual_provider(self):
        root = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        exe = os.path.join(root, "game")
        pathlib.Path(exe).write_text("", encoding="utf-8")
        records = ManualGameProvider([{"display_name":"Manual", "executable":exe}]).discover()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["provider"], "manual")
        self.assertTrue(records[0]["installed"])


if __name__ == "__main__":
    unittest.main()
