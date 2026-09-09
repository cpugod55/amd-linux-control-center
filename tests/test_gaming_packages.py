import pathlib, sys, tempfile, unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from alcc_gaming_packages import (
    detect_package_family,
    install_status_text,
    installed_component_state,
    package_plan,
    bazzite_gamemode_guidance,
    read_os_release,
)


class GamingPackagesTests(unittest.TestCase):
    def test_read_os_release_parses_quotes(self):
        with tempfile.NamedTemporaryFile('w+', delete=False) as f:
            f.write('ID="ubuntu"\nVERSION_ID="26.04"\nPRETTY_NAME="Ubuntu 26.04 LTS"\n')
            path=f.name
        try:
            data=read_os_release(path)
        finally:
            pathlib.Path(path).unlink(missing_ok=True)
        self.assertEqual(data['ID'],'ubuntu')
        self.assertEqual(data['VERSION_ID'],'26.04')

    def test_ubuntu_apt_family(self):
        which=lambda name: '/usr/bin/'+name if name=='apt-get' else None
        self.assertEqual(detect_package_family({'ID':'ubuntu'},which),'apt')

    def test_arch_pacman_family(self):
        which=lambda name: '/usr/bin/'+name if name=='pacman' else None
        self.assertEqual(detect_package_family({'ID':'arch'},which),'pacman')

    def test_ubuntu_gamescope_candidate_uses_apt(self):
        which=lambda name: '/usr/bin/'+name if name=='apt-get' else None
        cmd,platform,note=package_plan(
            'gamescope',{'ID':'ubuntu','VERSION_ID':'26.04'},which,
            lambda cmd:'gamescope:\n  Candidate: 3.16.15-1\n'
        )
        self.assertEqual(cmd,['pkexec','apt-get','install','-y','gamescope'])
        self.assertEqual(platform,'ubuntu 26.04')
        self.assertIsNone(note)

    def test_ubuntu_gamescope_without_candidate_uses_multiverse_sentinel(self):
        which=lambda name: '/usr/bin/'+name if name=='apt-get' else None
        cmd,platform,note=package_plan(
            'gamescope',{'ID':'ubuntu','VERSION_ID':'26.04'},which,
            lambda cmd:'gamescope:\n  Candidate: (none)\n'
        )
        self.assertEqual(cmd,['__enable_ubuntu_multiverse__'])
        self.assertIn('multiverse',note)

    def test_mangohud_apt_keeps_mangoapp(self):
        which=lambda name: '/usr/bin/'+name if name=='apt-get' else None
        cmd,_,_=package_plan('mangohud',{'ID':'ubuntu'},which,lambda cmd:'')
        self.assertEqual(cmd,['pkexec','apt-get','install','-y','mangohud','mangoapp'])

    def test_gamemode_arch_plan(self):
        which=lambda name: '/usr/bin/'+name if name=='pacman' else None
        cmd,platform,note=package_plan('gamemode',{'ID':'arch'},which,lambda cmd:'')
        self.assertEqual(cmd,['pkexec','pacman','-S','--needed','gamemode'])
        self.assertEqual(platform,'arch')
        self.assertIsNone(note)


    def test_bazzite_prefers_atomic_family_over_dnf(self):
        which=lambda name: '/usr/bin/'+name if name in {'rpm-ostree','dnf'} else None
        self.assertEqual(detect_package_family({'ID':'bazzite','ID_LIKE':'fedora'},which),'rpm-ostree')

    def test_bazzite_gaming_install_refuses_host_layering(self):
        which=lambda name: '/usr/bin/'+name if name in {'rpm-ostree','dnf'} else None
        cmd,platform,note=package_plan('gamescope',{'ID':'bazzite','ID_LIKE':'fedora'},which,lambda cmd:'')
        self.assertIsNone(cmd)
        self.assertEqual(platform,'bazzite')
        self.assertIn('will not run dnf or layer',note)


    def test_bazzite_gamemode_guidance_marks_unsupported_and_exposes_manual_command(self):
        which=lambda name: '/usr/bin/'+name if name=='rpm-ostree' else None
        guide=bazzite_gamemode_guidance({'ID':'bazzite','ID_LIKE':'fedora'},which)
        self.assertIsNotNone(guide)
        self.assertFalse(guide['supported'])
        self.assertEqual(guide['button'],'GameMode Info')
        self.assertEqual(guide['command'],'rpm-ostree install gamemode')
        self.assertIn('not installed or supported',guide['note'])

    def test_installed_state_and_status_text(self):
        which=lambda name: '/usr/bin/'+name if name in {'gamescope','mangohud','mangoapp','gamemoderun'} else None
        state=installed_component_state(which)
        self.assertTrue(all(state.values()))
        text=install_status_text('Test Linux',state)
        self.assertIn('Gamescope: installed',text)
        self.assertIn('MangoHud: installed',text)
        self.assertIn('GameMode: installed',text)
        self.assertIn('mangoapp: installed',text)

if __name__=='__main__': unittest.main()
