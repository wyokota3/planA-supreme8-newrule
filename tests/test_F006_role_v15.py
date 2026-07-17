"""T-Role v1.5(C-1c): salient_kind → 6 クラス role。後方互換(salient_kind 無=従来規則)。"""
import pytest

from supreme import role


def test_v15_human_salient_fires_source_human():
    assert role.classify({"salient_kind": "human"}) == role.SOURCE_HUMAN


def test_v15_object_salient_fires_source_object():
    assert role.classify({"salient_kind": "object"}) == role.SOURCE_OBJECT


def test_v15_vehicle_salient_fires_source_vehicle():
    assert role.classify({"salient_kind": "vehicle"}) == role.SOURCE_VEHICLE


def test_v15_speech_salient_fires_source_speech():
    assert role.classify({"salient_kind": "speech"}) == role.SOURCE_SPEECH


def test_v15_emergency_absolute_priority_over_salient():
    """has_alarm/siren は salient_kind=human でも source_alarm が絶対優先(Rc3)。"""
    assert role.classify({"salient_kind": "human", "has_alarm": True}) == role.SOURCE_ALARM
    assert role.classify({"salient_kind": "object", "has_siren": True}) == role.SOURCE_ALARM


def test_v15_unmapped_salient_kind_is_unknown():
    """noise 等 source に写らない category は unknown。"""
    assert role.classify({"salient_kind": "noise"}) == role.UNKNOWN


def test_v14_path_unchanged_when_no_salient_kind():
    """salient_kind 無(v1.4)は従来規則(has_alarm→source_alarm)。"""
    assert role.classify({"has_alarm": True}) == role.SOURCE_ALARM
    assert role.classify({"linked_speech_score": 0.5}) == role.SOURCE_SPEECH
    # salient_kind=None も v1.4 扱い
    assert role.classify({"has_alarm": True, "salient_kind": None}) == role.SOURCE_ALARM
