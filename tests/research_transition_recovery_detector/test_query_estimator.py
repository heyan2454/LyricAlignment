"""09_CODEX_REVIEWED_IMPLEMENTATION_PLAN §2.1 Density contract 最低测试。

canonical 名称只允许 units_per_sec；sec_per_unit 是显式 reciprocal 字段。
query density 单位倒置 bug（span/units_per_sec 除法）回归保护：expected_units 必须
是 span * units_per_sec，newboy 场景不得退化为 span * sec_per_unit。
"""

import pytest

from lyricalign.research_transition_recovery_detector.contracts import (
    TRANSITION_T2_CORE,
    TransitionState,
)
from lyricalign.research_transition_recovery_detector.query_estimator import (
    QueryEstimator,
    build_estimator,
    migrate_legacy_sec_per_unit,
)
from lyricalign.research_transition_recovery_detector.runner import build_query_ids


def test_units_per_sec_basic_240s_480units():
    est = QueryEstimator(n_units=480, effective_audio_sec=240.0)
    assert est.units_per_sec == pytest.approx(2.0)
    assert est.sec_per_unit == pytest.approx(0.5)
    assert est.expected_units(60.0) == pytest.approx(120.0)


def test_reciprocal_consistency():
    est = QueryEstimator(n_units=443, effective_audio_sec=231.5)
    assert est.sec_per_unit == pytest.approx(1.0 / est.units_per_sec)
    est2 = QueryEstimator(n_units=480, effective_audio_sec=240.0)
    assert est2.sec_per_unit == pytest.approx(1.0 / est2.units_per_sec)


def test_span_doubling_is_monotonic():
    est = QueryEstimator(n_units=480, effective_audio_sec=240.0)
    u60 = est.expected_units(60.0)
    u120 = est.expected_units(120.0)
    u240 = est.expected_units(240.0)
    assert u120 == pytest.approx(2 * u60)
    assert u240 == pytest.approx(2 * u120)


def test_n_units_halved_halves_units_per_sec():
    est_full = QueryEstimator(n_units=480, effective_audio_sec=240.0)
    est_half = QueryEstimator(n_units=240, effective_audio_sec=240.0)
    assert est_half.units_per_sec == pytest.approx(est_full.units_per_sec / 2)
    assert est_half.sec_per_unit == pytest.approx(2 * est_full.sec_per_unit)


def test_query_end_id_exclusive():
    est = QueryEstimator(n_units=480, effective_audio_sec=240.0)
    assert est.query_end_id_exclusive(60.0) == 120
    # 绝对语义：end 由 span 决定（120），start_id 只保底（不得双重计入偏移）
    assert est.query_end_id_exclusive(60.0, start_id=50) == 120
    assert est.query_end_id_exclusive(60.0, start_id=130) == 131


def test_build_estimator_equivalent_and_invalid_inputs():
    est = build_estimator(n_units=480, effective_audio_sec=240.0)
    assert isinstance(est, QueryEstimator)
    assert est.units_per_sec == pytest.approx(2.0)
    for n, d in [(0, 240.0), (-5, 240.0)]:
        with pytest.raises(ValueError):
            QueryEstimator(n_units=n, effective_audio_sec=d)
    with pytest.raises(ValueError):
        QueryEstimator(n_units=480, effective_audio_sec=0.0)
    with pytest.raises(ValueError):
        QueryEstimator(n_units=480, effective_audio_sec=-1.0)


def test_migrate_legacy_sec_per_unit():
    est = migrate_legacy_sec_per_unit(1.2, n_units=480)
    assert est.effective_audio_sec == pytest.approx(576.0)
    assert est.units_per_sec == pytest.approx(480.0 / 576.0)
    assert est.sec_per_unit == pytest.approx(1.2)


def test_newboy_fixture_regression_units_per_sec():
    est = QueryEstimator(n_units=443, effective_audio_sec=231.5)
    assert est.units_per_sec == pytest.approx(1.9136, abs=1e-3)
    assert est.expected_units(67.27) == pytest.approx(128.7, abs=0.5)


def test_newboy_fixture_query_ids_not_old_divide_bug():
    est = QueryEstimator(n_units=443, effective_audio_sec=231.5)
    state = TransitionState(
        song_id="newboy", transition=TRANSITION_T2_CORE, window_index=0,
        next_input_cursor=0, committed_end_exclusive=0,
    )
    ids = build_query_ids(
        transition=TRANSITION_T2_CORE,
        state=state,
        model_bounds=(0.0, 0.0, 57.27, 67.27),
        estimator=est,
        gt_timeline=None,
        lookback_units=8,
    )
    assert ids is not None
    assert len(ids) >= 100
    assert len(ids) <= 145
    # 单位倒置 bug 的产物：span * sec_per_unit ≈ 36，必须不出现
    assert len(ids) > 60
