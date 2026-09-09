import os,sys,unittest
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,os.path.join(ROOT,'app'))
from alcc_session_reports import (
    format_session_duration,format_session_metric,session_compare_number,
    performance_advisor_lines,game_session_details_text,game_session_comparison_text,
)

class SessionReportTests(unittest.TestCase):
    def rec(self):
        return {
            'game':'Valheim','steam_appid':'892970','started_iso':'2026-09-07 18:31:43','ended_iso':'2026-09-07 21:42:41','duration_seconds':11458,
            'schema_version':3,'telemetry_status':'Telemetry active','telemetry_method':'Automatic Steam launch options + identity-scoped MangoHud','telemetry_parser_status':'Valid FPS sample parsed',
            'raw_sampled_avg_fps':126.9,'raw_sampled_p1_fps':29.7,'gameplay_avg_fps':129.5,'gameplay_p1_fps':75.7,'live_reported_p1_fps':99.1,'live_p1_sources':['sampled_p1_60s'],'likely_menu_seconds':229,'paired_perf_samples':6000,
            'frame_cap_status':'No strong frame-cap evidence','frame_cap_confidence':'Low','frame_cap_plateau_fps':129.4,'frame_cap_occupancy_pct':41.2,'frame_cap_dispersion_pct':19.9,'frame_cap_duration_seconds':8576,'frame_cap_samples':5840,'frame_cap_continuity_pct':99.9,'frame_cap_avg_gpu_load_pct':98.9,'frame_cap_avg_power_w':263.4,'frame_cap_avg_gpu_clock_mhz':2309,'frame_cap_refresh_hz':144.0,
            'frame_dip_rating':'Significant dips','dip_analysis_status':'ok','dip_analysis_input_samples':5840,'gameplay_dip_events':35,'gameplay_dip_fraction_pct':3.7,'full_stall_candidates':0,'gameplay_median_fps':129.4,'frame_dip_threshold_fps':90.6,'frame_dip_events':35,'frame_dip_seconds':307,'frame_dip_fraction_pct':3.7,'gpu_bound_dip_events':35,'gpu_headroom_dip_events':0,'transition_dip_events':0,'mixed_dip_events':0,'worst_dip_kind':'GPU-saturated','worst_dip_avg_gpu_load':99.0,'worst_dip_avg_power_w':263.5,'worst_dip_avg_gpu_clock_mhz':2369,
            'isolated_hitch_candidates':38,'isolated_hitch_gpu_saturated':38,'isolated_hitch_gpu_headroom':0,'isolated_hitch_transition':0,'isolated_hitch_mixed':0,'worst_isolated_hitch_fps':24.1,'worst_isolated_hitch_kind':'GPU-saturated','worst_isolated_hitch_gpu_load':99.0,'worst_isolated_hitch_power_w':254.0,'worst_isolated_hitch_gpu_clock_mhz':2390,
            'dip_event_log':[{'clock':'19:18:36','kind':'GPU-saturated','min_fps':83.4,'avg_gpu_load':99.0,'avg_power_w':263.5,'avg_gpu_clock_mhz':2344}],
            'isolated_hitch_log':[{'clock':'19:20:36','kind':'GPU-saturated','fps':24.1,'gpu_load':99.0,'power_w':254.0,'gpu_clock_mhz':2390}],
            'avg_gpu_load_pct':96.6,'max_gpu_load_pct':99.0,'avg_edge_c':76.1,'max_edge_c':78.0,'avg_junction_c':90.8,'max_junction_c':95.0,'avg_temp_delta_c':14.7,'max_temp_delta_c':25.0,'avg_power_w':256.1,'max_power_w':266.0,'avg_gpu_clock_mhz':2251,'max_gpu_clock_mhz':2415,'avg_memory_clock_mhz':1000,'max_memory_clock_mhz':1000,'avg_vram_pct':27.5,'max_vram_pct':28.8,'gpu_profile':'—','graphics_preset':'—','scaling':'—','reason':'game exited',
        }

    def test_duration_formatting(self):
        self.assertEqual(format_session_duration(11458),'3h 10m 58s')
        self.assertEqual(format_session_duration(62),'1m 2s')
        self.assertEqual(format_session_duration('bad'),'—')

    def test_metric_formatting(self):
        self.assertEqual(format_session_metric(75.66,' FPS'),'75.7 FPS')
        self.assertEqual(format_session_metric(None,' W'),'—')

    def test_compare_number(self):
        self.assertEqual(session_compare_number({'x':'12.5'},'x'),12.5)
        self.assertIsNone(session_compare_number({'x':None},'x'))

    def test_advisor_lines_keep_ranked_recommendations(self):
        lines=performance_advisor_lines(self.rec(),raw_available=True)
        text='\n'.join(lines)
        self.assertIn('PERFORMANCE ADVISOR',text)
        self.assertIn('Strongly GPU-bound',text)
        self.assertIn('Ranked recommendations:',text)

    def test_details_report_preserves_key_sections(self):
        rec=self.rec()
        text=game_session_details_text(rec,analyzer_label='0.81.1',raw_available=True,history_sessions=[rec])
        self.assertIn('Game: Valheim    Steam AppID: 892970',text)
        self.assertIn('Duration: 3h 10m 58s',text)
        self.assertIn('Gameplay FPS: average 129.5 FPS    Gameplay P1 75.7 FPS',text)
        self.assertIn('• 19:18:36 sustained dip — GPU-saturated',text)
        self.assertIn('Session close reason: game exited',text)
        self.assertIn('PERFORMANCE ANALYSIS',text)

    def test_details_report_handles_invalid_selection(self):
        self.assertEqual(game_session_details_text(None),'No saved session selected.')

    def test_comparison_report_and_caution(self):
        newer=self.rec(); older=dict(newer)
        older.update(ended_iso='2026-09-07 18:29:06',duration_seconds=1200,gameplay_avg_fps=116.0,avg_gpu_load_pct=90.0,gpu_profile='Gaming')
        text=game_session_comparison_text(older,newer,raw_available_older=True,raw_available_newer=True)
        self.assertIn('SESSION COMPARISON',text)
        self.assertIn('COMPARISON CAUTION:',text)
        self.assertIn('Game/profile/preset/scaling setup is not identical',text)
        self.assertIn('Gameplay average FPS',text)
        self.assertIn('Change B-A',text)

if __name__=='__main__': unittest.main()
