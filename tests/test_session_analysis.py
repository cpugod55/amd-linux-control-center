import os, sys, unittest
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,os.path.join(ROOT,"app"))
from alcc_session_analysis import (game_session_quality,game_session_setup_key,thermal_delta_context,
    canonical_session_p1,performance_advisor,session_frame_dip_metrics,game_session_analysis)
class SessionAnalysisTests(unittest.TestCase):
    def test_gameplay_quality_from_paired_stream(self): self.assertEqual(game_session_quality({"duration_seconds":120,"avg_fps":60,"avg_gpu_load_pct":10,"paired_perf_samples":40}),"Gameplay")
    def test_idle_no_fps(self): self.assertEqual(game_session_quality({"duration_seconds":120,"max_gpu_load_pct":10}),"Idle / No FPS")
    def test_setup_key_exact_fields(self): self.assertEqual(game_session_setup_key({"game":"Valheim","gpu_profile":"Gaming","graphics_preset":"High","scaling":"—"}),("Valheim","Gaming","High","—"))
    def test_thermal_context_boundaries(self):
        self.assertEqual(thermal_delta_context({"max_temp_delta_c":19.9}),"ΔT compact"); self.assertEqual(thermal_delta_context({"max_temp_delta_c":26}),"ΔT moderate"); self.assertIn("ΔT large",thermal_delta_context({"max_temp_delta_c":31}))
    def test_canonical_p1_preference(self): self.assertEqual(canonical_session_p1({"gameplay_p1_fps":76.2,"raw_sampled_p1_fps":28.6,"live_reported_p1_fps":86.3}),76.2)
    def test_advisor_strong_gpu_bound(self):
        a=performance_advisor({"duration_seconds":1800,"paired_perf_samples":1000,"avg_gpu_load_pct":98,"frame_dip_rating":"Moderate dips","gameplay_dip_events":5,"gpu_bound_dip_events":5,"avg_power_w":250,"max_power_w":265},raw_available=True)
        self.assertEqual(a["primary_limiter"],"Strongly GPU-bound"); self.assertEqual(a["confidence"],"High"); self.assertTrue(any("render scale" in x.lower() for x in a["recommendations"]))
    def test_advisor_transition_only(self):
        a=performance_advisor({"duration_seconds":300,"paired_perf_samples":100,"avg_gpu_load_pct":98,"frame_dip_rating":"Good — transition/loading events only","transition_dip_events":2,"gameplay_dip_events":0},raw_available=True)
        self.assertIn("transition/loading",a["primary_limiter"].lower()); self.assertTrue(a["top_recommendation"].startswith("Do not change graphics settings"))
    def test_frame_dips_keep_gpu_saturated_low(self):
        rows=[]
        for i in range(30):
            fps=120.0
            if 10 <= i < 13: fps=60.0
            rows.append({"t":float(i),"fps":fps,"gpu_load":99.0,"power_w":263.0,"gpu_clock_mhz":2350.0})
        out=session_frame_dip_metrics({"paired_perf":rows,"started_at":1700000000.0})
        self.assertEqual(out["dip_analysis_status"],"ok")
        self.assertEqual(out["gpu_bound_dip_events"],1)
        self.assertEqual(out["gameplay_dip_events"],1)

    def test_frame_dips_transition_does_not_hurt_gameplay_severity(self):
        rows=[]
        for i in range(30):
            if 10 <= i < 13:
                rows.append({"t":float(i),"fps":20.0,"gpu_load":10.0,"power_w":40.0,"gpu_clock_mhz":400.0})
            else:
                rows.append({"t":float(i),"fps":120.0,"gpu_load":99.0,"power_w":263.0,"gpu_clock_mhz":2350.0})
        out=session_frame_dip_metrics({"paired_perf":rows,"started_at":1700000000.0})
        self.assertEqual(out["transition_dip_events"],1)
        self.assertEqual(out["gameplay_dip_events"],0)
        self.assertIn("transition/loading",out["frame_dip_rating"].lower())

    def test_frame_dips_background_30fps_is_filtered(self):
        rows=[]
        for i in range(40):
            rows.append({"t":float(i),"fps":120.0,"gpu_load":99.0,"power_w":263.0,"gpu_clock_mhz":2350.0})
        for i in range(12,18):
            rows[i]={"t":float(i),"fps":30.0,"gpu_load":30.0,"power_w":65.0,"gpu_clock_mhz":900.0}
        out=session_frame_dip_metrics({"paired_perf":rows,"started_at":1700000000.0})
        self.assertEqual(out["gameplay_dip_events"],0)

    def test_advisor_large_delta(self):
        a=performance_advisor({"duration_seconds":600,"paired_perf_samples":300,"avg_gpu_load_pct":90,"frame_dip_rating":"Smooth","avg_temp_delta_c":28,"max_temp_delta_c":34},raw_available=True)
        self.assertIn("Large hotspot delta",a["thermals"]); self.assertIn("cooling/contact",a["top_recommendation"].lower())

    def test_game_session_analysis_rejects_non_gameplay(self):
        self.assertEqual(game_session_analysis({"duration_seconds":10,"avg_fps":60},[]),["Limited analysis: this session is not classified as Gameplay."])

    def test_game_session_analysis_reports_gpu_bound_session(self):
        rec={"game":"Valheim","duration_seconds":600,"avg_fps":120,"gameplay_avg_fps":120,"gameplay_p1_fps":80,"paired_perf_samples":300,"avg_gpu_load_pct":98,"max_gpu_load_pct":99,"frame_dip_rating":"Moderate dips","dip_analysis_status":"ok","frame_dip_events":2,"gameplay_dip_events":2,"gameplay_dip_fraction_pct":2.0,"gpu_bound_dip_events":2,"gpu_headroom_dip_events":0,"transition_dip_events":0,"mixed_dip_events":0,"avg_power_w":255,"max_power_w":265,"max_junction_c":96,"max_temp_delta_c":25,"gpu_profile":"Gaming","graphics_preset":"High","scaling":"—"}
        lines=game_session_analysis(rec,[])
        text="\n".join(lines)
        self.assertIn("strongly GPU-bound",text)
        self.assertIn("upper-90s",text)
        self.assertIn("no prior exact-match Gameplay session",text)

    def test_game_session_analysis_personal_baseline_exact_match(self):
        rec={"game":"Valheim","duration_seconds":600,"avg_fps":120,"gameplay_avg_fps":120,"paired_perf_samples":300,"avg_gpu_load_pct":90,"gpu_profile":"Gaming","graphics_preset":"High","scaling":"—"}
        peer={"game":"Valheim","duration_seconds":600,"avg_fps":100,"gameplay_avg_fps":100,"paired_perf_samples":300,"avg_gpu_load_pct":90,"gpu_profile":"Gaming","graphics_preset":"High","scaling":"—"}
        mismatch=dict(peer,scaling="FSR Quality",gameplay_avg_fps=200,avg_fps=200)
        text="\n".join(game_session_analysis(rec,[peer,mismatch]))
        self.assertIn("20.0% above 1 prior comparable session(s) (100.0 FPS baseline)",text)

if __name__=="__main__": unittest.main()
