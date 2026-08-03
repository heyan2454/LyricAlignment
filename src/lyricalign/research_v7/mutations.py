"""v7 文本 mutation 目录 — 生成合法到不合法输入的百分比扰动。

对应 docs/research_v7_align_behavior/00_EXECUTION_PLAN.md §7/§8/§5：
- extra：过量文本 (+10/+25/+50/+100/+200%)，来源可区分（lookahead/future/错段/跨歌）。
- missing：文本不足 (10/25/50/75/90%)，可头部/尾部/中间连续/分散。
- replace：部分替换，保持总长不变，donor text 填坑 (10/25/50/75/100%)。
- no-match donor：跨歌 strict 规则（donor song != target，同语言/同 unit mode/等长）。
实现使用纯函数 + 固定 seed；不依赖模型/磁盘。可单元测试。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from random import Random
from typing import Iterable, Sequence


@dataclass(frozen=True)
class DonorSpec:
    """跨歌 donor 文本来源标识（用于 no-match / replace）。"""

    donor_song_id: str
    donor_start_index: int
    donor_units: tuple[str, ...]
    language: str
    unit_mode: str
    overlap_metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Mutation:
    """一次 mutation 的结果：扰动的文本、类型、比例与实际符合度。"""

    mutation_type: str          # extra / missing / replace / no_match
    base_units: tuple[str, ...]
    mutated_units: tuple[str, ...]
    base_count: int
    mutated_count: int
    requested_ratio: float
    actual_ratio: float
    position: str               # head / tail / middle / dispersed / whole
    source: str                 # lookahead / future / cross_song / repeated / wrong_section ...
    donor: DonorSpec | None = None


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #

def _first_n(units: Sequence[str], n: int) -> tuple[str, ...]:
    return tuple(units[:n])


def _is_close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


# --------------------------------------------------------------------------- #
# extra —— 过量文本
# --------------------------------------------------------------------------- #

def extra_ratio(
    base: Sequence[str],
    ratio: float,
    *,
    source: str = "future",
    extra_units: Sequence[str] | None = None,
    position: str = "tail",
) -> Mutation:
    """在 base 末尾追加过量文本。

    extra_units 若提供则使用之（须先来自 base 未来文本/错段/跨歌）；否则从 base 循环取（lookahead）。
    ratio>0 表示过量的比例（相对 base 长度），+10%=ratio 0.1。
    """
    b = tuple(base)
    n = len(b)
    add = int(round(n * ratio))
    if extra_units is not None:
        src = tuple(extra_units)
    else:
        # 默认视为“同歌未来正确歌词已在 lookahead”，循环取 base 前段充数
        src = b
    added = tuple(src[i % len(src)] for i in range(add)) if src else ()
    mutated = (b + added) if position == "tail" else (added + b)
    return Mutation(
        mutation_type="extra",
        base_units=b,
        mutated_units=mutated,
        base_count=n,
        mutated_count=len(mutated),
        requested_ratio=ratio,
        actual_ratio=(len(mutated) - n) / n if n else 0.0,
        position=position,
        source=source,
    )


# --------------------------------------------------------------------------- #
# missing —— 文本不足
# --------------------------------------------------------------------------- #

def missing_ratio(
    base: Sequence[str],
    ratio: float,
    *,
    position: str = "tail",
    seed: int = 0,
) -> Mutation:
    """移除 base 中的文本（不足）。

    ratio 表示移除比例（0.1~0.9）。position=head/tail/middle 连续移除对应区段，
    dispersed 则按 random 均匀移除固定比例。
    """
    b = tuple(base)
    n = len(b)
    remove = min(n - 1 if n else 0, int(round(n * ratio)))
    if n == 0 or remove <= 0:
        return Mutation("missing", b, b, n, n, ratio, 0.0, position, "missing")
    if position == "tail":
        mutated = b[: n - remove]
    elif position == "head":
        mutated = b[remove:]
    elif position == "middle":
        start = (n - remove) // 2
        mutated = b[:start] + b[start + remove :]
    else:  # dispersed
        rng = Random(seed)
        idx = set(rng.sample(range(n), remove))
        mutated = tuple(u for i, u in enumerate(b) if i not in idx)
    return Mutation(
        "missing", b, mutated, n, len(mutated), ratio,
        (n - len(mutated)) / n if n else 0.0, position, "missing",
    )


# --------------------------------------------------------------------------- #
# replace —— 部分替换（保持总长不变）
# --------------------------------------------------------------------------- #

def replace_ratio(
    base: Sequence[str],
    ratio: float,
    *,
    donor: DonorSpec,
    position: str = "whole",
    seed: int = 0,
) -> Mutation:
    """把 base 中 ratio 比例的文本替换为 donor 文本（长度不变）。

    position=whole 均匀全局替换；head/tail/middle 替换对应区段。
    donor 需与 base 等长（或至少提供足够长度）。
    """
    b = tuple(base)
    n = len(b)
    replace_n = int(round(n * ratio))
    donor_u = tuple(donor.donor_units)
    mutated = list(b)
    if replace_n > 0 and donor_u:
        if position == "whole":
            rng = Random(seed)
            idx = sorted(rng.sample(range(n), min(replace_n, n)))
        elif position == "head":
            idx = list(range(min(replace_n, n)))
        elif position == "tail":
            idx = list(range(n - min(replace_n, n), n))
        else:  # middle
            start = (n - replace_n) // 2
            idx = list(range(max(start, 0), min(start + replace_n, n)))
        for k, i in enumerate(idx):
            mutated[i] = donor_u[k % len(donor_u)]
    m = Mutation(
        "replace", b, tuple(mutated), n, n, ratio, replace_n / n if n else 0.0,
        position, "replace", donor=donor,
    )
    return m


# --------------------------------------------------------------------------- #
# no_match —— 完全不对应文本（跨歌 strict donor）
# --------------------------------------------------------------------------- #

def no_match(
    base: Sequence[str],
    *,
    donor: DonorSpec,
    language: str,
    unit_mode: str,
) -> Mutation:
    """整段替换为跨歌真实歌词（等长连续片段），构成 strict no-match。

    donor 必须满足 00 §8 C6 规则：donor song != target；同语言/同 unit mode；
    连续片段长度 >= base 长度。overlap_metrics 由调用方冻结。
    """
    b = tuple(base)
    n = len(b)
    donor_u = tuple(donor.donor_units)
    if len(donor_u) < n:
        # 容忍不等长：循环/截断到 n（正式 pilot 会冻结 donor manifest 保证等长）
        filled = tuple((donor_u[i % max(len(donor_u), 1)]) for i in range(n))
    else:
        filled = donor_u[:n]
    return Mutation(
        "no_match", b, filled, n, n, 1.0, 1.0, "whole", "cross_song", donor=donor,
    )


# --------------------------------------------------------------------------- #
# MutationCatalog —— 从 yaml/字典描述批量构造
# --------------------------------------------------------------------------- #

@dataclass
class MutationCatalog:
    """一组 mutation 规格。seed 用于可复现扰动。"""

    spec: dict[str, object]
    seed: int = 0

    def build(self, base_units: Sequence[str]) -> list[Mutation]:
        """按 spec['mutations'] 逐个生成（每项含 type/ratio/position/source/donor)。"""
        out: list[Mutation] = []
        base = tuple(base_units)
        for m in self.spec.get("mutations", []):
            mtype = m.get("type")
            ratio = float(m.get("ratio", 1.0))
            pos = m.get("position", "tail")
            if mtype == "extra":
                out.append(extra_ratio(base, ratio, source=m.get("source", "future"), position=pos))
            elif mtype == "missing":
                out.append(missing_ratio(base, ratio, position=pos, seed=self.seed))
            elif mtype in ("replace", "no_match"):
                donor = m.get("donor")
                if not donor:
                    continue
                dspec = DonorSpec(
                    donor_song_id=donor["donor_song_id"],
                    donor_start_index=donor.get("donor_start_index", 0),
                    donor_units=tuple(donor["donor_units"]),
                    language=donor.get("language", ""),
                    unit_mode=donor.get("unit_mode", ""),
                    overlap_metrics=dict(donor.get("overlap_metrics", {})),
                )
                if mtype == "no_match":
                    out.append(no_match(base, donor=dspec, language=dspec.language, unit_mode=dspec.unit_mode))
                else:
                    out.append(replace_ratio(base, ratio, donor=dspec, position=pos, seed=self.seed))
        return out


def build_mutation(catalog: MutationCatalog, base_units: Sequence[str]) -> list[Mutation]:
    return catalog.build(base_units)
