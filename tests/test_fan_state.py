from app.alcc_fan_state import (
    DEFAULT_FAN_CURVE,
    fan_preferences,
    normalize_fan_curve,
    store_fan_preferences,
)


def test_normalize_fan_curve_clamps_and_keeps_speed_non_decreasing():
    points=[[100, 70], [40, 25], [55, 10], [85, 120], [70, 45]]
    assert normalize_fan_curve(points) == [
        (40, 25),
        (55, 25),
        (70, 45),
        (85, 100),
        (100, 100),
    ]


def test_invalid_curve_falls_back_to_defaults():
    assert normalize_fan_curve([[40, 20]]) == list(DEFAULT_FAN_CURVE)


def test_fan_preferences_default_to_automatic():
    points, mode=fan_preferences({})
    assert points == list(DEFAULT_FAN_CURVE)
    assert mode == "automatic"


def test_store_and_load_curve_preferences_round_trip():
    settings={"other_setting": True}
    store_fan_preferences(
        settings,
        [(40, 25), (55, 35), (70, 45), (85, 55), (100, 75)],
        "curve",
    )
    points, mode=fan_preferences(settings)
    assert points == [(40, 25), (55, 35), (70, 45), (85, 55), (100, 75)]
    assert mode == "curve"
    assert settings["other_setting"] is True


def test_unknown_saved_mode_falls_back_to_automatic():
    _, mode=fan_preferences({"fan_curve_mode": "mystery"})
    assert mode == "automatic"
