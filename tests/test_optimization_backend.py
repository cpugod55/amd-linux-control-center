import os,sys,unittest
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,os.path.join(ROOT,'app'))
from alcc_optimization import OptimizationEngineMixin
from amd_linux_control_center import App

class OptimizationBackendExtractionTests(unittest.TestCase):
    def setUp(self):
        self.app=App.__new__(App)

    def rec(self, avg=120.0, p1=80.0, profile='Gaming', scaling='Native', preset='High', duration=1800, idx=0):
        return {
            'game':'Valheim','steam_appid':'892970','quality':'Gameplay','duration_seconds':duration,
            'started_at_epoch':1000+idx,'started_iso':'2026-09-07 18:00:00','ended_iso':'2026-09-07 18:30:00',
            'gameplay_avg_fps':avg,'gameplay_p1_fps':p1,'avg_fps':avg,'avg_power_w':240.0,
            'avg_gpu_load_pct':98.0,'avg_gpu_clock_mhz':2300.0,'avg_junction_c':88.0,'max_junction_c':94.0,
            'paired_perf_samples':500,'gpu_profile':profile,'graphics_preset':preset,'scaling':scaling,
            'gameplay_dip_events':2,'isolated_hitch_candidates':1,
        }

    def test_app_uses_optimization_mixin(self):
        self.assertTrue(issubclass(App,OptimizationEngineMixin))
        self.assertNotIn('_optimization_fingerprint',App.__dict__)
        self.assertIn('_optimization_fingerprint',OptimizationEngineMixin.__dict__)

    def test_fingerprint_keeps_setup_identity(self):
        fp=self.app._optimization_fingerprint(self.rec())
        self.assertEqual(fp[0],('appid','892970'))
        self.assertIn('High',fp)
        self.assertIn('Gaming',fp)

    def test_candidate_validation_requires_one_changed_variable(self):
        base={'gpu_profile':'Gaming','graphics_preset':'High'}
        good={'gpu_profile':'Maximum Performance','graphics_preset':'High'}
        bad={'gpu_profile':'Maximum Performance','graphics_preset':'Low'}
        self.assertTrue(self.app._trial_candidate_validation(base,good,'gpu_profile')['valid'])
        self.assertFalse(self.app._trial_candidate_validation(base,bad,'gpu_profile')['valid'])

    def test_candidate_reconcile_and_availability(self):
        state=self.app._trial_reconcile_candidate_selection('old',['new'],context_changed=True)
        self.assertEqual(state['selection'],'new')
        self.assertTrue(state['apply_enabled'])
        self.assertTrue(self.app._trial_candidate_value_available('power_limit_w','264.0',['264']))

    def test_optimization_groups_aggregate_comparable_runs(self):
        rows=[self.rec(avg=120,p1=80,idx=0),self.rec(avg=124,p1=84,idx=1)]
        groups=self.app._optimization_groups(rows,rows[-1])
        self.assertEqual(len(groups),1)
        self.assertEqual(groups[0]['session_count'],2)
        self.assertAlmostEqual(groups[0]['gameplay_avg_fps'],122.0)

    def test_trial_result_compares_baseline_candidate(self):
        sessions=[self.rec(avg=100,p1=70,profile='Gaming',idx=0),self.rec(avg=101,p1=71,profile='Gaming',idx=1),
                  self.rec(avg=115,p1=82,profile='Maximum Performance',idx=2),self.rec(avg=116,p1=83,profile='Maximum Performance',idx=3)]
        self.app.game_session_history={'sessions':sessions}
        trial={'goal':'Higher average FPS','tested_variable':'gpu_profile','baseline_configuration':{'gpu_profile':'Gaming'},
               'candidate_configuration':{'gpu_profile':'Maximum Performance'},'baseline_session_indexes':[0,1],
               'candidate_session_indexes':[2,3],'trial_complete':False,'waiting_for':None}
        result=self.app._optimization_trial_result(trial)
        self.assertEqual(result['verdict'],'KEEP CANDIDATE')
        self.assertGreater(result['delta'],0)

    def test_stopping_rule_preserves_evidence_budget(self):
        group={'session_count':4,'rows':[(i,self.rec(avg=100+i,idx=i)) for i in range(4)],
               'gameplay_avg_fps':101.5,'gameplay_fps_sd':1.3,'gameplay_p1_fps':75,'gameplay_p1_sd':1,
               'consistency_pct':74,'consistency_sd':1,'avg_junction_c':88,'avg_junction_sd':1,'fps_per_watt':.42,'fps_per_watt_sd':.01}
        result={'baseline':group,'candidate':dict(group),'verdict':'TOO CLOSE TO CALL','evidence':'Too close to call','metric':'gameplay_avg_fps','delta':0.2}
        decision=self.app._trial_stopping_decision({},result)
        self.assertTrue(decision['stop'])
        self.assertEqual(decision['outcome'],'INCONCLUSIVE')

    def test_trial_report_lines_remain_available(self):
        group={'session_count':2,'raw_session_count':0,'total_duration_seconds':3600,'gameplay_avg_fps':120,'gameplay_p1_fps':80,
               'consistency_pct':66.7,'gameplay_dips_per_hour':2,'isolated_hitches_per_hour':1,'avg_gpu_load_pct':98,
               'avg_junction_c':88,'max_junction_c':94,'avg_power_w':240,'fps_per_watt':0.5,'rows':[]}
        result={'baseline':group,'candidate':dict(group),'verdict':'TOO CLOSE TO CALL','confidence':'Moderate','summary':'test'}
        lines=self.app._trial_metric_report_lines(result)
        self.assertTrue(any('Gameplay Avg FPS' in line for line in lines))
        self.assertTrue(any('Evidence:' in line for line in lines))

if __name__=='__main__': unittest.main()
