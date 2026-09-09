import os,sys,unittest
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,os.path.join(ROOT,'app'))
from alcc_session_trends import (
    trend_timestamp,trend_game_matches,trend_point,trend_sessions,
    trend_neighbor_index,trend_baseline,trend_baseline_cell_data,
    trend_summary_text,trend_comparison_pair,
)

class SessionTrendBackendTests(unittest.TestCase):
    def rec(self, game='Valheim', appid='892970', avg=120.0, p1=80.0, ended='2026-09-07 20:00:00', profile='Gaming', preset='High', scaling='Native'):
        return {'game':game,'steam_appid':appid,'started_iso':ended,'ended_iso':ended,'duration_seconds':1200,
                'gameplay_avg_fps':avg,'gameplay_p1_fps':p1,'avg_power_w':240,'avg_gpu_load_pct':98,
                'avg_gpu_clock_mhz':2300,'avg_junction_c':88,'max_junction_c':94,'paired_perf_samples':500,
                'avg_fps':avg,'max_gpu_load_pct':99,'gpu_profile':profile,'graphics_preset':preset,'scaling':scaling}

    def test_timestamp_parses_saved_iso(self):
        self.assertGreater(trend_timestamp(self.rec()),0)

    def test_game_match_prefers_steam_appid(self):
        self.assertTrue(trend_game_matches(self.rec(game='A'),self.rec(game='B')))
        self.assertFalse(trend_game_matches(self.rec(appid='1'),self.rec(appid='2')))

    def test_trend_point_derives_consistency_and_efficiency(self):
        p=trend_point(3,self.rec(avg=120,p1=90))
        self.assertEqual(p['history_index'],3)
        self.assertAlmostEqual(p['consistency_pct'],75.0)
        self.assertAlmostEqual(p['fps_per_watt'],0.5)

    def test_comparable_sessions_filter_setup_and_game(self):
        sessions=[self.rec(),self.rec(avg=125),self.rec(game='Other',appid='10'),self.rec(profile='Maximum Performance')]
        points,reasons=trend_sessions(sessions,0,True)
        self.assertEqual([p['history_index'] for p in points],[0,1])
        self.assertEqual(reasons['different game'],1)
        self.assertEqual(reasons['different graphics/scaling/GPU profile'],1)

    def test_neighbor_navigation(self):
        points=[{'history_index':1},{'history_index':4},{'history_index':9}]
        self.assertEqual(trend_neighbor_index(points,4,-1),1)
        self.assertEqual(trend_neighbor_index(points,4,1),9)
        self.assertIsNone(trend_neighbor_index(points,9,1))

    def test_baseline_excludes_selected_and_picks_representative(self):
        points=[trend_point(i,self.rec(avg=a,p1=a*.7)) for i,a in enumerate((100,110,130))]
        base=trend_baseline(points,2)
        self.assertEqual(base['sessions'],2)
        self.assertAlmostEqual(base['gameplay_avg'],105.0)
        self.assertIn(base['representative_history_index'],(0,1))

    def test_baseline_cell_data_formats_delta(self):
        point=trend_point(2,self.rec(avg=120,p1=90))
        base={'gameplay_avg':100,'gameplay_p1':80,'consistency_pct':80,'avg_junction':85,'avg_power':230,'fps_per_watt':0.45,'sessions':3}
        cells=trend_baseline_cell_data(point,base)
        self.assertEqual(cells['gameplay_avg'][0],'120.0 FPS')
        self.assertIn('+20.0 FPS',cells['gameplay_avg'][1])

    def test_summary_and_comparison_pair(self):
        records=[self.rec(avg=100,ended='2026-09-07 18:00:00'),self.rec(avg=110,ended='2026-09-07 19:00:00'),self.rec(avg=120,ended='2026-09-07 20:00:00'),self.rec(avg=130,ended='2026-09-07 21:00:00')]
        points,_=trend_sessions(records)
        text=trend_summary_text(points,True)
        self.assertIn('Sessions: 4',text)
        self.assertIn('Recent baseline change:',text)
        pair=trend_comparison_pair(points,3,'previous')
        self.assertEqual(pair[0]['history_index'],2)
        self.assertEqual(pair[1]['history_index'],3)

if __name__=='__main__': unittest.main()
