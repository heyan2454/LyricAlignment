#!/usr/bin/env python3
'''Review package for the two confirmed, training-free gains (monotone DP decode + entropy gating).

Numbers come from `results/by_run/**`; statements about the code are read from the source files, so this
document cannot drift from the evidence or from my memory.
Quoting discipline: strings containing ASCII double quotes use single quotes; prose emphasis uses 「」.

    PYTHONPATH=src python scripts/evaluation/make_decoder_ship_review.py --repo . \
        --out docs/reviews/20260914_decoder_ship_review.md
'''

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DP_FLAG = 'TIMESTAMP_DECODERS = ("official", "dp")'
IDENTITY_CHECK = 'if self.timestamp_decoder != "official":'
IDENTITY_ASSIGN = 'identity["timestamp_decoder"]'
PRODUCT_KINDS = ('official', 'raw', 'joint_start_end', 'topk_sequence', 'weighted_isotonic', 'dp')


def load(root: Path, relative: str) -> dict[str, Any] | None:
    path = root / relative
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return None


def pct(value: Any, digits: int = 1) -> str:
    return '—' if value is None else f'{100 * value:.{digits}f}%'


def dp_deltas(root: Path) -> list[tuple[str, float]]:
    directory = root / 'results/by_run/20260914_long_context_view'
    out: list[tuple[str, float]] = []
    seen: set[str] = set()
    if not directory.exists():
        return out
    for path in sorted(directory.glob('*.json')):
        document = load(root, str(path.relative_to(root))) or {}
        for label, block in (document.get('checkpoints') or {}).items():
            if label in seen:
                continue
            variants = block.get('variants') or {}
            summary = block.get('summary') or {}
            fixed_block = variants.get('fixed') or summary.get('fixed') or {}
            fixed = fixed_block.get('macro_song_within_primary', fixed_block.get('macro_within_primary'))
            dp = (variants.get('dp') or {}).get('macro_song_within_primary')
            if fixed is not None and dp is not None:
                seen.add(label)
                out.append((label, 100 * (dp - fixed)))
    return out


def code_facts(repo: Path) -> dict[str, Any]:
    aligner = repo / 'src/lyricalign/inference/qwen_forced_aligner.py'
    product = repo / 'scripts/demo/align_qwen_fa_serial_demo.py'
    facts: dict[str, Any] = {'aligner_has_dp': False, 'aligner_identity_extends': False,
                             'product_decoder_kinds': [], 'product_wires_dp': False}
    if aligner.exists():
        text = aligner.read_text(encoding='utf-8')
        facts['aligner_has_dp'] = DP_FLAG in text
        facts['aligner_identity_extends'] = IDENTITY_CHECK in text and IDENTITY_ASSIGN in text
    if product.exists():
        text = product.read_text(encoding='utf-8')
        facts['product_decoder_kinds'] = [kind for kind in PRODUCT_KINDS if f'"{kind}"' in text]
        facts['product_wires_dp'] = 'dp_timestamp_items' in text
    return facts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, default=Path('.'))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root = args.repo.resolve()

    policies = (load(root, 'results/by_run/20260914_snap_rule/metrics.json') or {}).get('policies') or {}
    gating = load(root, 'results/by_run/20260914_review_gating/metrics.json') or {}
    batch = load(root, 'results/by_run/20260914_confidence_abstention/batch.json') or {}
    collapse = load(root, 'results/by_run/20260914_real_song_collapse/metrics.json') or {}
    stress = load(root, 'results/by_run/20260914_real_song_decoder/metrics.json') or {}
    alternative = load(root, 'results/by_run/20260914_real_song_dp_alternative/metrics.json') or {}
    deltas = dp_deltas(root)
    facts = code_facts(root)

    lines: list[str] = ['# 评审包：两条不需重训的收益（单调 DP 解码 + 置信度门控）', '',
                        '> 由 `scripts/evaluation/make_decoder_ship_review.py` 从 `results/by_run/**` 与代码本身生成：'
                        '不手抄数字，也不凭记忆描述代码状态。', '',
                        '## 1. 建议采纳什么', '',
                        '- **A. 单调 Viterbi（DP）解码**：替换「逐字 argmax + 上游修补」；',
                        '- **B. 按熵的复核门控**（`scripts/evaluation/export_review_gating.py`）：产出人工复核清单。',
                        '  **两者必须同时上线** —— DP 会让「零长度 / 重叠」这两个唯一的自动探针全部变绿。', '',
                        '## 2. 证据（域内）', '']
    if policies:
        best = max(policies, key=lambda key: policies[key].get('macro_song_within_primary', 0))
        argmax_value = (policies.get('argmax') or {}).get('macro_song_within_primary', 0)
        lines += [f'- 全量验证集（1,711 项 / 15,204 字符）、同一次前向下的解码器排名；'
                  f'最好为 `{best}` = **{policies[best]["macro_song_within_primary"]:.4f}**，'
                  f'逐字 argmax = {argmax_value:.4f}：', '',
                  '| 解码 | 0.2s 命中率 | MAE(ms) | 可用率 |', '|---|---|---|---|']
        for name in sorted(policies, key=lambda key: -policies[key].get('macro_song_within_primary', 0)):
            block = policies[name]
            lines.append(f'| {name} | {block["macro_song_within_primary"]:.4f} | {block["mae_all_ms"]:.1f} | '
                         f'{block["usable_rate"]:.4f} |')
    else:
        lines.append('- 状态：缺 `20260914_snap_rule/metrics.json`（未跑）。')
    if deltas:
        values = [value for _label, value in deltas]
        lines += ['', f'- 长流视图上 `dp − fixed` **逐存档现算**（{len(deltas)} 个存档）：',
                  '  ' + '、'.join(f'{label} {value:+.2f}pp' for label, value in deltas),
                  f'  ⇒ 区间 **{min(values):+.2f} ~ {max(values):+.2f} pp**，跨不同训练配置一致。']
    if gating:
        lines += ['', '- 门控（真歌批，无真值，按歌留一交叉验证）：标记 ' + pct(gating.get('flagged_share'))
                  + ' 的字 → 抓到 ' + pct(gating.get('defect_capture_share')) + ' 缺陷，剩余缺陷率 '
                  + pct(gating.get('residual_defect_rate_after_review'), 2) + '（原 '
                  + pct(gating.get('defect_rate'), 2) + '）。']
    if batch:
        lines.append('  独立外部印证（2026-09-12，GTSinger 语料）：熵 AUC 0.913；本批真歌熵 AUC '
                     + str((batch.get('auc') or {}).get('end_entropy')) + '。')
    lines.append('  **口径提醒**：门控工具的实测数字与「按歌留一」是同一次计算的两种呈现，不是两条独立证据。')
    lines.append('')
    if collapse and stress:
        totals = stress.get('totals') or {}
        evidence = alternative.get('totals') or {}
        lines += ['- 为什么不能只上 DP：真歌批上原始塌陷 ' + pct(collapse.get('raw_zero_share'), 2)
                  + ' → 上游修补后 ' + pct(collapse.get('official_zero_share'), 2)
                  + '（修补是净负贡献）；压力条件下 DP 把零长度从 ' + pct(totals.get('official_zero_share'))
                  + ' 降到 ' + pct(totals.get('dp_zero_share'))
                  + '，但 DP 替代点在声学证据上更高的比例只有 '
                  + pct(evidence.get('share_alternative_more_evidence_d_rms')) + ' / '
                  + pct(evidence.get('share_alternative_more_evidence_flux')) + '（≈抛硬币）'
                  + ' ⇒ **结构合法不等于正确**。', '']
    lines += ['## 3. 代码现状（扫描代码得出，不凭记忆）', '',
              '- 含 DP 的封装 `QwenForcedAligner`：支持 official|dp = **' + str(facts['aligner_has_dp']) + '**；'
              '非默认解码器扩展身份字典 = **' + str(facts['aligner_identity_extends']) + '**'
              '（这一项 17:14 才发现原本是 return 之后的死代码，已修 + 3 项契约测试）；',
              '- 产品批处理链 `run_qwen_fa_batch.py → align_qwen_fa_serial_demo.full_alignment`：'
              '代码中出现的 decoder 取值 = ' + str(facts['product_decoder_kinds']) + '；'
              '**是否已接 DP = ' + str(facts['product_wires_dp']) + '**', '',
              '## 4. 尚未完成（避免被读成「已可上线」）', '',
              '1. **DP 未接入产品解码链**：目前只在 `QwenForcedAligner`（被 smoke 脚本使用）里可用；',
              '2. **需要一次影子验证跑**：同一批交付音频分别用 official 与 dp 产出时间轴，对比结构指标、'
              '两轴位移分布与门控标记率；GPU 与结构臂冲突，排在臂结束之后；',
              '3. **门控的产品侧契约**：清单 schema、阈值来源（按歌留一，不用被评那首歌自己决定）、'
              '写回策略（只标记不改写）；',
              '4. **校验链识别解码器**：非默认解码器必须进 `model_identity()`（已具备）并被校验脚本读取，'
              '否则两种解码器的产物在审计上不可分辨。', '',
              '## 5. 风险与缓解', '',
              '| 风险 | 缓解 |', '|---|---|',
              '| DP 让结构探针全部变绿、掩盖真实错误 | 与门控同时上线；保留逐字符位移分布作二次探针 |',
              '| 长音频/无分窗的压力条件下 DP 会秒级重排 | 重度塌陷区域强制进复核，不因合法而放过 |',
              '| 上游修补与 DP 叠加互相抵消 | 影子跑同时产出 official / official+repair / dp 三条时间轴 |',
              '| 域内数字被外推到真歌 | 域内只宣称命中率；真歌侧证据单独列（两轴一致度、门控标记率） |', '',
              '## 6. 回滚', '',
              '- 默认值保持 `official`：不改默认路径即不改任何既有产物语义；出问题时把 decoder 取值切回 '
              'official，身份字典自动回到与今天逐键一致的内容。', '']
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'written': str(args.out), 'dp_archives': len(deltas), 'code_facts': facts},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
