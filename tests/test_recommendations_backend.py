import os,sys,unittest
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,os.path.join(ROOT,'app'))
from alcc_recommendations import RecommendationEngineMixin
from amd_linux_control_center import App

class RecommendationBackendExtractionTests(unittest.TestCase):
    def setUp(self):
        self.app=App.__new__(App)

    def cfg(self,profile='Gaming',preset='High',power=240,workload='3D_FULL_SCREEN'):
        return {'gpu_profile':profile,'graphics_preset':preset,'scaling':'Native','render_resolution':'3440×1440',
                'output_resolution':'3440×1440','power_limit_w':power,'workload_profile':workload}

    def test_app_uses_recommendation_mixin(self):
        self.assertTrue(issubclass(App,RecommendationEngineMixin))
        self.assertNotIn('_derive_game_recommendation',App.__dict__)
        self.assertIn('_derive_game_recommendation',RecommendationEngineMixin.__dict__)

    def test_known_configuration_matching_is_conservative(self):
        self.assertTrue(self.app._recommendation_configuration_known(self.cfg()))
        self.assertTrue(self.app._recommendation_config_matches(self.cfg(),self.cfg()))
        unknown={k:'Unknown' for k in self.cfg()}
        self.assertFalse(self.app._recommendation_configuration_known(unknown))
        self.assertFalse(self.app._recommendation_config_matches(unknown,self.cfg()))

    def test_frame_cap_majority_is_detected(self):
        rows=[(0,{'frame_cap_status':'Frame-rate cap / synchronization likely'}),
              (1,{'frame_cap_status':'No strong frame-cap evidence'}),
              (2,{'frame_cap_status':'Frame-rate cap / synchronization likely'})]
        self.assertTrue(self.app._recommendation_group_frame_cap({'rows':rows}))

    def test_recommendation_changes_only_known_mutable_fields(self):
        current=self.cfg(profile='Gaming',preset='High',power=240)
        wanted=self.cfg(profile='Maximum Performance',preset='Medium',power=264)
        changes=self.app._recommendation_changes(current,wanted)
        keys=[row[0] for row in changes]
        self.assertEqual(keys,['gpu_profile','graphics_preset','power_limit_w'])

    def test_placeholder_target_is_never_actionable_change(self):
        current={k:'Unknown' for k in self.cfg()}
        wanted={k:'Unknown' for k in self.cfg()}
        wanted['gpu_profile']='—'
        self.assertEqual(self.app._recommendation_changes(current,wanted),[])

    def test_all_placeholder_spellings_are_non_actionable(self):
        for value in (None,'','-','—','Unknown','unknown','Unavailable','none','not configured','N/A','na'):
            with self.subTest(value=value):
                self.assertFalse(self.app._recommendation_value_known(value))

    def test_trial_context_prefers_matching_game_and_newest(self):
        trials={'trials':[{'game_id':'steam:892970','created_at':10},{'game_id':'steam:1','created_at':99},
                          {'steam_appid':'892970','completed_at':20}]}
        rows=self.app._recommendation_trial_context(trials,{'game_id':'steam:892970','steam_appid':'892970'})
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0].get('completed_at'),20)

    def test_failed_multi_change_apply_rolls_back_prior_change(self):
        current=self.cfg(profile='Gaming',preset='High')
        wanted=self.cfg(profile='Maximum Performance',preset='Medium')
        rec={'game':{'game_id':'steam:892970','steam_appid':'892970'},'current_configuration':current,'recommended_configuration':wanted}
        calls=[]
        def apply(key,value):
            calls.append((key,value))
            if key=='graphics_preset' and value=='Medium': return False
            return True
        result=self.app._apply_recommended_configuration(rec,apply)
        self.assertFalse(result['applied'])
        self.assertEqual(calls[0],('gpu_profile','Maximum Performance'))
        self.assertIn(('gpu_profile','Gaming'),calls)

if __name__=='__main__': unittest.main()
