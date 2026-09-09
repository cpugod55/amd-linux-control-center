import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from alcc_telemetry import (
    detect_likely_capped_menu_samples,
    parse_mangohud_csv_text,
    percentile,
    session_gameplay_fps_metrics,
)


class TelemetryTests(unittest.TestCase):
    def test_percentile_interpolates(self):
        self.assertEqual(percentile([], 0.5), None)
        self.assertEqual(percentile([10], 0.5), 10.0)
        self.assertAlmostEqual(percentile([10, 20], 0.5), 15.0)

    def test_parse_provider_columns(self):
        text = "fps,frametime,1% low,gpu frametime,cpu frametime\n100,10,80,7,3\n120,8.3,90,6,2.3\n"
        d = parse_mangohud_csv_text(text)
        self.assertEqual(d["fps"], 120.0)
        self.assertEqual(d["low"], 90.0)
        self.assertEqual(d["low_kind"], "provider")
        self.assertEqual(d["frametime_kind"], "provider")
        self.assertEqual(d["gpu_frame"], 6.0)
        self.assertEqual(d["cpu_frame"], 2.3)

    def test_parse_derives_frametime_and_sampled_p1(self):
        rows = ["fps"] + [str(100 + (i % 5)) for i in range(30)]
        d = parse_mangohud_csv_text("\n".join(rows))
        self.assertEqual(d["fps"], 104.0)
        self.assertEqual(d["frametime_kind"], "derived")
        self.assertEqual(d["low_kind"], "sampled_p1_60s")
        self.assertEqual(len(d["samples"]), 30)

    def test_parse_legacy_first_numeric_column(self):
        d = parse_mangohud_csv_text("not,a,header\n60,foo\n61,bar\n")
        self.assertEqual(d["fps"], 61.0)
        self.assertEqual(d["samples"], [60.0, 61.0])

    def test_parse_rejects_no_valid_fps(self):
        self.assertIsNone(parse_mangohud_csv_text("fps\n0\n"))
        self.assertIsNone(parse_mangohud_csv_text("hello\nworld\n"))

    def test_menu_detector_requires_load_drop_and_plateau(self):
        paired = []
        for i in range(8):
            paired.append({"t": i, "fps": 100 + i % 2, "gpu_load": 95})
        for i in range(8, 13):
            paired.append({"t": i, "fps": 60.0, "gpu_load": 45})
        marked, q75 = detect_likely_capped_menu_samples(paired)
        self.assertGreaterEqual(q75, 90)
        self.assertEqual(marked, set(range(8, 13)))

    def test_menu_detector_does_not_mark_normal_60fps_gameplay(self):
        paired = [{"t": i, "fps": 60.0, "gpu_load": 92.0} for i in range(20)]
        marked, _ = detect_likely_capped_menu_samples(paired)
        self.assertEqual(marked, set())

    def test_common_30fps_background_cap_with_idle_gpu_is_filtered(self):
        paired = [
            {"t": i, "fps": 120.0, "gpu_load": 98.0, "power_w": 260.0, "gpu_clock_mhz": 2300.0}
            for i in range(20)
        ]
        # Sparse, non-consecutive unfocused samples: typical game background cap.
        paired[5] = {"t": 5, "fps": 30.0, "gpu_load": 31.0, "power_w": 62.0, "gpu_clock_mhz": 800.0}
        paired[11] = {"t": 11, "fps": 29.8, "gpu_load": 39.0, "power_w": 68.0, "gpu_clock_mhz": 900.0}
        marked, _ = detect_likely_capped_menu_samples(paired)
        self.assertIn(5, marked)
        self.assertIn(11, marked)

    def test_background_transition_edges_are_absorbed_when_power_and_clock_are_idle(self):
        paired = [
            {"t": i, "fps": 120.0, "gpu_load": 98.0, "power_w": 263.0, "gpu_clock_mhz": 2320.0}
            for i in range(24)
        ]
        # Confirmed background samples.
        paired[10] = {"t": 10, "fps": 30.0, "gpu_load": 35.0, "power_w": 65.0, "gpu_clock_mhz": 850.0}
        paired[11] = {"t": 11, "fps": 30.0, "gpu_load": 38.0, "power_w": 68.0, "gpu_clock_mhz": 900.0}
        # Entry/exit edges resemble the Valheim case: utilization has not fully
        # fallen yet, but power and clocks already have.
        paired[9] = {"t": 9, "fps": 26.0, "gpu_load": 67.0, "power_w": 106.0, "gpu_clock_mhz": 1266.0}
        paired[12] = {"t": 12, "fps": 29.4, "gpu_load": 68.5, "power_w": 71.5, "gpu_clock_mhz": 1291.0}
        marked, _ = detect_likely_capped_menu_samples(paired)
        self.assertTrue({9, 10, 11, 12}.issubset(marked))

    def test_background_transition_does_not_absorb_adjacent_high_power_low_fps(self):
        paired = [
            {"t": i, "fps": 120.0, "gpu_load": 98.0, "power_w": 263.0, "gpu_clock_mhz": 2320.0}
            for i in range(24)
        ]
        paired[10] = {"t": 10, "fps": 30.0, "gpu_load": 35.0, "power_w": 65.0, "gpu_clock_mhz": 850.0}
        paired[11] = {"t": 11, "fps": 30.0, "gpu_load": 38.0, "power_w": 68.0, "gpu_clock_mhz": 900.0}
        # Adjacent low FPS is a real loaded-GPU event and must remain gameplay.
        paired[12] = {"t": 12, "fps": 30.0, "gpu_load": 72.0, "power_w": 245.0, "gpu_clock_mhz": 2250.0}
        marked, _ = detect_likely_capped_menu_samples(paired)
        self.assertNotIn(12, marked)

    def test_learned_background_state_recovers_sparse_high_utilization_samples(self):
        paired = [
            {"t": i, "fps": 110.0, "gpu_load": 99.0, "power_w": 263.0, "gpu_clock_mhz": 2360.0}
            for i in range(40)
        ]
        # Positively identified background plateau seeds.
        for i in (10, 11, 12, 13):
            paired[i] = {"t": i, "fps": 30.0, "gpu_load": 35.0, "power_w": 66.0, "gpu_clock_mhz": 900.0}
        # Sparse Valheim-like background/transition samples later in the session:
        # utilization looks surprisingly high, but power and clocks match the
        # learned unfocused operating state.
        paired[24] = {"t": 24, "fps": 29.8, "gpu_load": 78.5, "power_w": 66.0, "gpu_clock_mhz": 1372.0}
        paired[31] = {"t": 31, "fps": 24.0, "gpu_load": 80.2, "power_w": 71.9, "gpu_clock_mhz": 1372.0}
        marked, _ = detect_likely_capped_menu_samples(paired)
        self.assertIn(24, marked)
        self.assertIn(31, marked)

    def test_learned_background_state_keeps_same_fps_when_gpu_is_loaded(self):
        paired = [
            {"t": i, "fps": 110.0, "gpu_load": 99.0, "power_w": 263.0, "gpu_clock_mhz": 2360.0}
            for i in range(30)
        ]
        for i in (10, 11, 12, 13):
            paired[i] = {"t": i, "fps": 30.0, "gpu_load": 35.0, "power_w": 66.0, "gpu_clock_mhz": 900.0}
        paired[22] = {"t": 22, "fps": 29.8, "gpu_load": 99.0, "power_w": 264.0, "gpu_clock_mhz": 2310.0}
        marked, _ = detect_likely_capped_menu_samples(paired)
        self.assertNotIn(22, marked)

    def test_30fps_at_saturated_gpu_is_not_filtered(self):
        paired = [
            {"t": i, "fps": 120.0, "gpu_load": 98.0, "power_w": 260.0, "gpu_clock_mhz": 2300.0}
            for i in range(20)
        ]
        paired[7] = {"t": 7, "fps": 30.0, "gpu_load": 99.0, "power_w": 264.0, "gpu_clock_mhz": 2310.0}
        marked, _ = detect_likely_capped_menu_samples(paired)
        self.assertNotIn(7, marked)

    def test_30fps_low_gpu_without_idle_evidence_is_not_guessed(self):
        paired = [
            {"t": i, "fps": 120.0, "gpu_load": 98.0, "power_w": 260.0, "gpu_clock_mhz": 2300.0}
            for i in range(20)
        ]
        # Could be a CPU/game-engine bottleneck: low load, but power/clock remain active.
        paired[9] = {"t": 9, "fps": 30.0, "gpu_load": 45.0, "power_w": 230.0, "gpu_clock_mhz": 2200.0}
        marked, _ = detect_likely_capped_menu_samples(paired)
        self.assertNotIn(9, marked)

    def test_session_metrics_remove_detected_menu_samples(self):
        paired = []
        for i in range(12):
            paired.append({"t": i, "fps": 100.0, "gpu_load": 95.0})
        for i in range(12, 17):
            paired.append({"t": i, "fps": 60.0, "gpu_load": 40.0})
        d = session_gameplay_fps_metrics({"paired_perf": paired, "fps": []})
        self.assertEqual(d["raw_samples"], 17)
        self.assertEqual(d["gameplay_samples"], 12)
        self.assertEqual(d["likely_menu_samples"], 5)
        self.assertAlmostEqual(d["gameplay_avg"], 100.0)


if __name__ == "__main__":
    unittest.main()
