import base64
import gzip
import json

from alcc_analysis_lab import AnalysisLabEngineMixin
from amd_linux_control_center import App


class Harness(AnalysisLabEngineMixin):
    @staticmethod
    def _session_num(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def test_app_uses_extracted_analysis_lab_mixin():
    assert issubclass(App, AnalysisLabEngineMixin)
    assert "_analyze_raw_session" not in App.__dict__


def test_raw_telemetry_codec_round_trip():
    raw=[{"t":1.0,"fps":60.0,"gpu_load":99.0,"power_w":200.0}]
    encoded,count=Harness._encode_raw_telemetry(raw)
    assert count==1
    rec={"raw_paired_telemetry_gzip_base64":encoded}
    assert Harness._stored_raw_telemetry(rec)==raw


def test_raw_telemetry_legacy_list_is_supported():
    raw=[{"t":0,"fps":90,"gpu_load":80}]
    assert Harness._stored_raw_telemetry({"raw_paired_telemetry":raw})==raw


def test_invalid_encoded_raw_telemetry_fails_closed():
    assert Harness._stored_raw_telemetry({"raw_paired_telemetry_gzip_base64":"not-base64"})==[]


def test_simulator_presets_remain_available():
    presets=Harness._telemetry_simulator_presets()
    assert presets and all(isinstance(item,dict) for item in presets.values())


def test_simulator_generation_is_bounded_and_has_fps():
    config=Harness._telemetry_simulator_presets()["Smooth 90 FPS"]
    config.update(duration=10,interval=1)
    rows,meta=Harness._generate_simulated_telemetry(config)
    assert rows and meta["sample_count"]==10
    assert len(rows)<=30000
    assert all("fps" in row and "gpu_load" in row for row in rows)
