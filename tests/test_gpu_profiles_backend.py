#!/usr/bin/env python3
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))

from alcc_gpu_profiles import (
    active_power_profile_raw,
    builtin_profile_plan,
    detect_builtin_gpu_profile,
    friendly_power_profile,
)


class FakeGpu:
    def __init__(self,root,*,default=264.0,current=264.0,lo=227.0,hi=264.0,active='3D_FULL_SCREEN'):
        self.device=os.path.join(root,'device')
        self.hwmon=os.path.join(root,'hwmon')
        os.makedirs(self.device,exist_ok=True)
        os.makedirs(self.hwmon,exist_ok=True)
        Path(self.device,'power_dpm_force_performance_level').write_text('high\n')
        Path(self.device,'pp_power_profile_mode').write_text('1 3D_FULL_SCREEN*:\n')
        Path(self.hwmon,'power1_cap').write_text(f'{int(current*1_000_000)}\n')
        self._default=default; self._lim=(current,lo,hi); self._active=active
    def perf_levels(self): return ['auto','low','high','manual']
    def performance_profiles(self):
        return [(0,'BOOTUP_DEFAULT',self._active=='BOOTUP_DEFAULT'),(1,'3D_FULL_SCREEN',self._active=='3D_FULL_SCREEN'),(2,'POWER_SAVING',self._active=='POWER_SAVING')]
    def power_cap_limits(self): return self._lim
    def power_cap_default_w(self): return self._default


class GpuProfileBackendTests(unittest.TestCase):
    def setUp(self):
        self.td=tempfile.TemporaryDirectory(); self.gpu=FakeGpu(self.td.name)
    def tearDown(self): self.td.cleanup()

    def test_friendly_names(self):
        self.assertEqual(friendly_power_profile('3D_FULL_SCREEN'),'3D Full Screen')
        self.assertEqual(friendly_power_profile('future_profile'),'Future Profile')

    def test_gaming_plan_uses_exposed_driver_default(self):
        pairs,desc,expected=builtin_profile_plan(self.gpu,'gaming')
        self.assertEqual(expected,{'perf':'high','profile':'3D_FULL_SCREEN','power':264.0})
        self.assertTrue(any(v=='264000000' for _p,v in pairs))
        self.assertIn('Power: driver default 264 W',desc)

    def test_quiet_power_is_default_derived_and_range_safe(self):
        _pairs,desc,expected=builtin_profile_plan(self.gpu,'quiet')
        self.assertAlmostEqual(expected['power'],237.6)
        self.assertEqual(expected['profile'],'POWER_SAVING')
        self.assertIn('Power: adaptive quiet target 238 W',desc)

    def test_efficient_power_is_meaningful_default_derived_reduction(self):
        _pairs,desc,expected=builtin_profile_plan(self.gpu,'efficient')
        self.assertAlmostEqual(expected['power'],250.8)
        self.assertEqual(expected['profile'],'3D_FULL_SCREEN')
        self.assertIn('Power: adaptive efficiency target 251 W',desc)

    def test_narrow_below_default_range_does_not_pretend_one_watt_is_adaptive(self):
        gpu=FakeGpu(self.td.name,default=264.0,current=264.0,lo=263.0,hi=281.0)
        pairs,desc,expected=builtin_profile_plan(gpu,'efficient')
        self.assertNotIn('power',expected)
        self.assertFalse(any(path.endswith('power1_cap') for path,_value in pairs))
        self.assertIn('Power: driver range leaves no meaningful reduction below default; power target unchanged.',desc)

    def test_active_profile(self):
        self.assertEqual(active_power_profile_raw(self.gpu),'3D_FULL_SCREEN')

    def test_duplicate_live_state_uses_verified_last_choice(self):
        self.assertEqual(detect_builtin_gpu_profile(self.gpu,{'type':'builtin','name':'gaming'}),'gaming')
        self.assertEqual(detect_builtin_gpu_profile(self.gpu,{'type':'builtin','name':'max'}),'max')

    def test_duplicate_live_state_without_history_is_unmatched(self):
        self.assertIsNone(detect_builtin_gpu_profile(self.gpu,None))

    def test_non_builtin_history_cannot_disambiguate(self):
        self.assertIsNone(detect_builtin_gpu_profile(self.gpu,{'type':'saved','name':'Gaming'}))

    def test_missing_interfaces_produce_no_writes(self):
        for p in (Path(self.gpu.device,'power_dpm_force_performance_level'),Path(self.gpu.device,'pp_power_profile_mode'),Path(self.gpu.hwmon,'power1_cap')):
            p.unlink()
        pairs,desc,expected=builtin_profile_plan(self.gpu,'gaming')
        self.assertEqual(pairs,[]); self.assertEqual(expected,{})


if __name__=='__main__': unittest.main()
