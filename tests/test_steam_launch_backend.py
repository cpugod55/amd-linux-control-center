import pathlib, sys, tempfile
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/"app"))
from alcc_steam_launch import *

SAMPLE='''"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n\t\t\t\t"apps"\n\t\t\t\t{\n\t\t\t\t\t"892970"\n\t\t\t\t\t{\n\t\t\t\t\t\t"LaunchOptions"\t\t"MANGOHUD=1 %command%"\n\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n'''

def test_validate_and_read():
    assert validate_steam_localconfig_text(SAMPLE)
    with tempfile.NamedTemporaryFile('w+',delete=False) as f:
        f.write(SAMPLE); path=f.name
    assert read_launch_options_from_localconfig(path,'892970')=='MANGOHUD=1 %command%'

def test_patch_existing():
    out=patch_steam_launch_options_text(SAMPLE,'892970','gamescope -f -- %command%')
    assert 'gamescope -f -- %command%' in out and validate_steam_localconfig_text(out)

def test_insert_existing_app_without_launchoptions():
    text=SAMPLE.replace('\t\t\t\t\t\t"LaunchOptions"\t\t"MANGOHUD=1 %command%"\n','')
    out=patch_steam_launch_options_text(text,'892970','ABC')
    assert '"LaunchOptions"\t\t"ABC"' in out and validate_steam_localconfig_text(out)

def test_insert_new_app():
    out=patch_steam_launch_options_text(SAMPLE,'12345','XYZ')
    assert '"12345"' in out and '"LaunchOptions"\t\t"XYZ"' in out and validate_steam_localconfig_text(out)

def test_escape_roundtrip():
    value='A "quoted" \\ path'
    assert vdf_unescape(vdf_escape(value))==value

def test_invalid_rejected():
    try: validate_steam_localconfig_text('"UserLocalConfigStore" {')
    except RuntimeError: pass
    else: raise AssertionError('malformed VDF accepted')

def test_normalization():
    assert normalize_launch_options('  abc  ')=='abc'
    assert normalize_launch_options(None)==''
