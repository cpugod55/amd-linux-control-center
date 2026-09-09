import os,sys,unittest
from pathlib import Path
APP=Path(__file__).resolve().parents[1]/"app"
sys.path.insert(0,str(APP))
from alcc_session_runtime import build_session_state,ingest_session_sample,should_finish_session,build_completed_record

class SessionRuntimeTests(unittest.TestCase):
    def base(self):
        return build_session_state(identity="steam:1",game="Test",steam_appid="1",started_at=1000.0,gpu_profile="Gaming",graphics_preset="High",scaling="FSR Quality",render_resolution="1920×1080",output_resolution="2560×1440",power_limit_w=264.0,workload_profile="3D_FULL_SCREEN",telemetry_identity="steam:1",telemetry_method="Automatic",display_refresh_hz=144.0)
    def test_state_defaults(self):
        s=self.base(); self.assertEqual(s["telemetry_status"],"Game detected — waiting for telemetry"); self.assertEqual(s["paired_perf"],[])
    def test_ingest_pairs_recent_fps_and_gpu(self):
        s=self.base(); times=iter([10.0,10.2]); sample=ingest_session_sample(s,{"fps":120,"low":90,"low_kind":"sampled_p1_60s"},{"busy":98,"power_w":260,"sclk":2300,"mclk":1000,"temps":{"edge":70,"junction":85},"vram_used":4,"vram_total":16},now_monotonic=lambda:next(times)); self.assertEqual(len(s["paired_perf"]),1); self.assertEqual(sample["fps"],120.0); self.assertEqual(sample["junction_c"],85.0); self.assertEqual(s["vram_pct"],[25.0])
    def test_ingest_does_not_pair_stale_fps(self):
        s=self.base(); s["_last_fps"]=100.0; s["_last_fps_time"]=1.0; sample=ingest_session_sample(s,{}, {"busy":95},now_monotonic=lambda:4.0); self.assertIsNone(sample); self.assertEqual(s["paired_perf"],[])
    def test_sample_retention_compacts(self):
        s=self.base(); s["fps"]=[1.0]*30001; ingest_session_sample(s,{}, {},now_monotonic=lambda:1.0); self.assertLessEqual(len(s["fps"]),15001)
    def test_finish_gate(self):
        self.assertTrue(should_finish_session({},10.0,5.0,now_monotonic=lambda:15.0)); self.assertFalse(should_finish_session({},10.0,5.0,now_monotonic=lambda:14.9)); self.assertFalse(should_finish_session(None,10.0,5.0,now_monotonic=lambda:20.0))
    def test_completed_record_preserves_analysis_and_quality(self):
        s=self.base(); s["fps"]=[100,120]; s["p1"]=[80]; s["edge"]=[70,72]; s["gpu_load"]=[98,99]; r=build_completed_record(s,reason="game exited",ended_at=1060.0,analyzed={"gameplay_avg_fps":110.0},encoded_raw="abc",encoded_count=2,analyzer_version="x",quality=lambda rec:"Gameplay"); self.assertEqual(r["duration_seconds"],60.0); self.assertEqual(r["avg_fps"],110.0); self.assertEqual(r["gameplay_avg_fps"],110.0); self.assertEqual(r["quality"],"Gameplay"); self.assertEqual(r["raw_paired_telemetry_samples"],2)

if __name__=="__main__":unittest.main()
