import ast
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MAIN=ROOT/'app'/'amd_linux_control_center.py'
MOD=ROOT/'app'/'alcc_live_intelligence.py'

def test_mixin_wired():
    text=MAIN.read_text()
    assert 'from alcc_live_intelligence import LiveIntelligenceMixin' in text
    assert 'class App(LiveIntelligenceMixin,' in text

def test_backend_methods_extracted():
    main=ast.parse(MAIN.read_text())
    app=next(n for n in main.body if isinstance(n,ast.ClassDef) and n.name=='App')
    names={n.name for n in app.body if isinstance(n,ast.FunctionDef)}
    for name in ('_new_live_intelligence_state','_live_regime_signature','_analyze_live_intelligence','_live_intelligence_ingest','_suspend_live_intelligence'):
        assert name not in names
    mod=ast.parse(MOD.read_text())
    mix=next(n for n in mod.body if isinstance(n,ast.ClassDef) and n.name=='LiveIntelligenceMixin')
    mnames={n.name for n in mix.body if isinstance(n,ast.FunctionDef)}
    for name in ('_new_live_intelligence_state','_live_regime_signature','_analyze_live_intelligence','_live_intelligence_ingest','_suspend_live_intelligence'):
        assert name in mnames
