import pathlib, sys, unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from amd_linux_control_center import App

class DummyLabel:
    def __init__(self): self.kw={}
    def configure(self, **kw): self.kw.update(kw)

class DummyButton(DummyLabel):
    pass

class GamingInstallUIStateTests(unittest.TestCase):
    def make_app(self):
        app=App.__new__(App)
        app.gaming_install_status=DummyLabel()
        app.install_gamescope_btn=DummyButton()
        app.install_mangohud_btn=DummyButton()
        app.install_gamemode_btn=DummyButton()
        app._linux_os_release=lambda: {'PRETTY_NAME':'Test Linux'}
        return app

    def test_installed_gamemode_button_matches_detected_state(self):
        app=self.make_app()
        def which(name):
            return '/usr/bin/'+name if name in {'gamescope','mangohud','gamemoderun'} else None
        with patch('amd_linux_control_center.shutil.which',side_effect=which):
            app.refresh_gaming_install_status()
        self.assertEqual(app.install_gamemode_btn.kw.get('text'),'GameMode Installed')
        self.assertEqual(app.install_gamemode_btn.kw.get('state'),'disabled')
        self.assertIn('GameMode: installed',app.gaming_install_status.kw.get('text',''))

    def test_missing_gamemode_button_remains_actionable(self):
        app=self.make_app()
        def which(name):
            return '/usr/bin/'+name if name in {'gamescope','mangohud'} else None
        with patch('amd_linux_control_center.shutil.which',side_effect=which):
            app.refresh_gaming_install_status()
        self.assertEqual(app.install_gamemode_btn.kw.get('text'),'Install GameMode')
        self.assertEqual(app.install_gamemode_btn.kw.get('state'),'normal')
        self.assertIn('GameMode: not installed',app.gaming_install_status.kw.get('text',''))


    def test_bazzite_missing_gamemode_becomes_info_action(self):
        app=self.make_app()
        app._linux_os_release=lambda: {'ID':'bazzite','ID_LIKE':'fedora','PRETTY_NAME':'Bazzite'}
        def which(name):
            return '/usr/bin/'+name if name in {'gamescope','mangohud','rpm-ostree'} else None
        with patch('amd_linux_control_center.shutil.which',side_effect=which):
            app.refresh_gaming_install_status()
        self.assertEqual(app.install_gamemode_btn.kw.get('text'),'GameMode Info')
        self.assertEqual(app.install_gamemode_btn.kw.get('state'),'normal')
        self.assertIn('GameMode: unsupported on Bazzite',app.gaming_install_status.kw.get('text',''))

if __name__=='__main__': unittest.main()
