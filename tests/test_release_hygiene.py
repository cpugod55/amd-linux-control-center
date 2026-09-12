from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _runtime_release_files():
    yield ROOT / "install.sh"
    yield ROOT / "setup-passwordless-gpu.sh"
    yield ROOT / "system-check.sh"
    yield from (ROOT / "app").glob("*.py")
    yield from (ROOT / "polkit").glob("*.policy")


def test_runtime_and_packaging_do_not_contain_unrelated_development_vendor_metadata():
    # Construct the development-tool name so the hygiene test itself does not
    # put that unrelated vendor string back into source-release grep results.
    unrelated_vendor = "".join(("open", "ai"))
    offenders=[]
    for path in _runtime_release_files():
        text=path.read_text(encoding="utf-8", errors="ignore").lower()
        if unrelated_vendor in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_policykit_metadata_uses_project_owned_namespace_and_url():
    policies=list((ROOT / "polkit").glob("*.policy"))
    assert [path.name for path in policies] == ["io.github.cpugod55.amd-linux-control-center.policy"]
    text=policies[0].read_text(encoding="utf-8")
    assert 'action id="io.github.cpugod55.amd-linux-control-center.gpu-control"' in text
    assert '<vendor_url>https://github.com/cpugod55/amd-linux-control-center</vendor_url>' in text
