from alcc_game_profiles import (
    adaptive_gpu_profile_titles,
    decode_gpu_profile_choice,
    gpu_profile_choice_values,
    rule_gpu_profile_display,
    rule_has_valid_gpu_profile,
)


def test_titles_stable():
    assert adaptive_gpu_profile_titles() == {
        "default":"Default", "gaming":"Gaming", "efficient":"Efficient Gaming",
        "quiet":"Quiet", "max":"Maximum Performance",
    }


def test_choice_values_filter_unsupported_and_sort_saved():
    vals=gpu_profile_choice_values(["zeta","Alpha"], lambda k: k in {"default","gaming"})
    assert vals == ["", "Adaptive: Default", "Adaptive: Gaming", "Saved: Alpha", "Saved: zeta"]


def test_decode_adaptive():
    assert decode_gpu_profile_choice("Adaptive: Maximum Performance", []) == {
        "type":"builtin", "name":"max", "display":"Adaptive: Maximum Performance"
    }


def test_decode_saved_prefixed_and_legacy_unprefixed():
    saved=["My Profile"]
    assert decode_gpu_profile_choice("Saved: My Profile", saved)["type"] == "saved"
    assert decode_gpu_profile_choice("My Profile", saved) == {
        "type":"saved", "name":"My Profile", "display":"Saved: My Profile"
    }


def test_decode_rejects_missing_saved_profile():
    got=decode_gpu_profile_choice("Saved: Missing", ["Other"])
    assert got == {"type":"", "name":"", "display":"Saved: Missing"}


def test_rule_display_builtin_saved_and_empty():
    assert rule_gpu_profile_display({"profile_type":"builtin","profile":"efficient"}) == "Adaptive: Efficient Gaming"
    assert rule_gpu_profile_display({"profile":"Custom One"}) == "Saved: Custom One"
    assert rule_gpu_profile_display({}) == "—"


def test_rule_validity_is_capability_driven():
    avail=lambda k: k == "gaming"
    assert rule_has_valid_gpu_profile({"profile_type":"builtin","profile":"gaming"}, [], avail)
    assert not rule_has_valid_gpu_profile({"profile_type":"builtin","profile":"quiet"}, [], avail)


def test_rule_validity_saved_profile():
    assert rule_has_valid_gpu_profile({"profile_type":"saved","profile":"One"}, ["One"], None)
    assert not rule_has_valid_gpu_profile({"profile_type":"saved","profile":"Missing"}, ["One"], None)
