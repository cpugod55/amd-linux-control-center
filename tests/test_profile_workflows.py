from alcc_profile_workflows import (
    profile_names,
    profile_summary_text,
    quick_profile_snapshot,
    startup_profile_status_text,
    startup_profile_target,
)


def test_profile_names_sorted_and_missing_safe():
    assert profile_names({"profiles": {"Zulu": {}, "Alpha": {}}}) == ["Alpha", "Zulu"]
    assert profile_names({}) == []


def test_profile_summary_preserves_existing_fields():
    text = profile_summary_text({"profiles": {"Gaming": {
        "performance_level": "manual",
        "power_profile_index": 1,
        "power_cap_w": 264,
        "dpm_mode": "manual",
        "dpm_requests": {"pp_dpm_sclk": {"mhz": 2300}},
        "fan_curve": [[40, 25], [80, 70]],
        "fan_mode": "curve",
    }}})
    assert "Gaming\n" in text
    assert "Performance: manual" in text
    assert "AMD profile: 1" in text
    assert "Power limit: 264 W" in text
    assert "sclk:2300MHz" in text
    assert "Fan: curve  [40°:25%, 80°:70%]" in text


def test_quick_profile_snapshots_are_capability_derived():
    profiles = [(0, "BOOTUP_DEFAULT", True), (1, "3D_FULL_SCREEN", False), (2, "POWER_SAVING", False)]
    quiet = quick_profile_snapshot("Quiet", 250, 150, 300, profiles)
    perf = quick_profile_snapshot("Performance", 250, 150, 300, profiles)
    default = quick_profile_snapshot("Default", 250, 150, 300, profiles)
    assert (quiet["power_profile_index"], quiet["power_cap_w"], quiet["fan_mode"]) == (2, 150, "curve")
    assert (perf["power_profile_index"], perf["power_cap_w"], perf["fan_mode"]) == (1, 300, "curve")
    assert (default["power_profile_index"], default["power_cap_w"], default["fan_mode"]) == (0, 250, "automatic")


def test_startup_target_resolution():
    settings = {"last_used_profile": {"type": "saved", "name": "My Profile"}}
    assert startup_profile_target("Gaming", settings) == {"type": "builtin", "name": "gaming"}
    assert startup_profile_target("Last used profile", settings) == {"type": "saved", "name": "My Profile"}
    assert startup_profile_target("Do nothing", settings) is None


def test_startup_status_text_matches_read_only_policy():
    settings = {"launch_at_login": True, "last_used_profile": {"type": "builtin", "name": "gaming"}}
    assert startup_profile_status_text("Do nothing", settings) == "Startup restore is disabled."
    assert startup_profile_status_text("Gaming", settings) == (
        "Gaming selected. GUI startup is read-only; use Apply Now to apply it.  Launch-at-login is enabled."
    )
    assert startup_profile_status_text("Last used profile", settings) == (
        "Last used: Gaming built-in profile  Launch-at-login is enabled."
    )
