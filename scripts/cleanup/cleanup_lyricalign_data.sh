#!/usr/bin/env bash
# =============================================================================
# lyricalign 数据清理脚本（专注 demo_diagnostics 的 A/B 两组，2026-08-01）
#
# 用法：
#   bash /home/hyan/a.sh            # 预览：只打印“将删除什么”，不真正删（DRY-RUN）
#   bash /home/hyan/a.sh --apply    # 真正执行删除
#
# 清理对象（见 docs/data_cleanup_checklist_lyricalign.md ## 二）：
#   A 类 —— demo_diagnostics/ 下早于 v8 的历史迭代 root（结果已由 v8 汇总），整目录删除：
#       lazy_v1/v2/v4/v5/v6/v7、smoke_e9/_v2.._v7。
#   B 类 —— inline_realign_formal_v3/v4/v5 的 items/ 中间产物（每 item 仅保留
#       item_summary.json；删 branches/experimental_alignments/shadow/trials/visuals 等），
#       另删 v3 的冗余 items.zip。
#
# 不会碰（安全）：
#   - demo_diagnostics 下的 v8 正式 root（formal/complete.json、research_summary、
#     run_status、manifest、item_summary 均保留）
#   - models/、tools/fonts/、outputs/、evidence*、derived 被引用的 4 个目录、runs 被引用的
#     checkpoint（清单里标“保留”的项一律不涉及；本脚本只动 demo_diagnostics 的 A/B）。
#   - 其他项目（ast_data/、datasets/、lyricalign 源码）不碰。
# =============================================================================

set -Eeuo pipefail

# ---- 参数：默认 DRY-RUN（只预览），加 --apply 才真删 -----------------------
APPLY=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    *) echo "未知参数：$arg（可用 --apply 表示真正删除）" >&2; exit 2 ;;
  esac
done

# ---- 根目录（如在别的机器跑，改这一处）-------------------------------------
DD=/root/autodl-tmp/AST_storage/Data/lyricalign/demo_diagnostics

die() { echo "ERROR: $*" >&2; exit 1; }

echo "===== lyricalign 数据清理（默认=预览；--apply=执行）====="

# ---------------------------------------------------------------------------
# 通用删除函数：预览时只打印，--apply 时才 rm -rf
# ---------------------------------------------------------------------------
print_and_rm() { # $1 = 完整路径
  echo "  DEL  $1"
  if [[ "$APPLY" -eq 1 ]]; then
    rm -rf -- "$1"
  fi
}

if [[ ! -d "$DD" ]]; then
  die "demo_diagnostics 不存在：$DD"
fi

echo "  根目录：$DD"

# ---------------------------------------------------------------------------
# A 类 —— 早于 v8 的历史迭代 root，整目录删除
# ---------------------------------------------------------------------------
echo; echo "== A 类：历史迭代 root（已由 v8 汇总，整目录删除）=="
A_ROOTS=(
  "alignment_research_v6_formal_20260731_e9_lazy_v1"
  "alignment_research_v6_formal_20260731_e9_lazy_compact_v2"
  "alignment_research_v6_formal_20260731_e9_lazy_compact_v4_metrics_only"
  "alignment_research_v6_formal_20260731_e9_lazy_compact_v5_tracefix_recovery"
  "alignment_research_v6_formal_20260731_e9_lazy_compact_v6_shortaudiofix"
  "alignment_research_v6_formal_20260731_e9_lazy_compact_v7_inputcache_e9scope"
  "alignment_research_v6_smoke_20260731_e9"
  "alignment_research_v6_smoke_20260731_e9_v2"
  "alignment_research_v6_smoke_20260731_e9_v3"
  "alignment_research_v6_smoke_20260731_e9_v4"
  "alignment_research_v6_smoke_20260731_e9_v5"
  "alignment_research_v6_smoke_20260731_e9_v6"
  "alignment_research_v6_smoke_20260731_e9_v7"
)
for r in "${A_ROOTS[@]}"; do
  if [[ -d "$DD/$r" ]]; then
    print_and_rm "$DD/$r"
  else
    echo "  [skip] 不存在：$DD/$r"
  fi
done

# ---------------------------------------------------------------------------
# B 类 —— inline v3/v4/v5 的 items/ 中间产物，仅保留 item_summary.json
# ---------------------------------------------------------------------------
echo; echo "== B 类：inline v3/v4/v5 的 items/ 中间产物（保留 item_summary.json）=="
keep_summary_rm() { # $1 = items 根目录；删除每个 item 子目录内除 item_summary.json 外的所有条目
  local items_root="$1"
  if [[ ! -d "$items_root" ]]; then
    echo "  [skip] 不存在：$items_root"
    return
  fi
  local item entry base
  # 遍历每个 item 子目录
  while IFS= read -r -d '' item; do
    if [[ ! -d "$item" ]]; then
      # 非目录（如散落文件）直接处理
      print_and_rm "$item"
      continue
    fi
    # item 目录为“保留”本身（只留它，含其 item_summary.json 等全部内容）——本设计只保 item_summary，
    # 故对 item 目录内每条目，仅保留名为 item_summary.json 的。
    while IFS= read -r -d '' entry; do
      base="$(basename "$entry")"
      if [[ "$base" == "item_summary.json" ]]; then
        echo "  KEEP  $entry"
      else
        print_and_rm "$entry"
      fi
    done < <(find "$item" -mindepth 1 -maxdepth 1 -print0 2>/dev/null || true)
  done < <(find "$items_root" -mindepth 1 -maxdepth 1 -print0 2>/dev/null || true)
}

keep_summary_rm "$DD/inline_realign_formal_v3_20260728/items"
keep_summary_rm "$DD/inline_realign_formal_v4_20260729/items"
keep_summary_rm "$DD/inline_realign_formal_v5_60main_20260729/items"

# v3 的冗余 items.zip（items/ 已解压，双份）
if [[ -f "$DD/inline_realign_formal_v3_20260728/items.zip" ]]; then
  print_and_rm "$DD/inline_realign_formal_v3_20260728/items.zip"
else
  echo "  [skip] 不存在：$DD/inline_realign_formal_v3_20260728/items.zip"
fi

# ---------------------------------------------------------------------------
# 收尾
# ---------------------------------------------------------------------------
echo; echo "===== 完成 ====="
if [[ "$APPLY" -eq 1 ]]; then
  echo "已按 --apply 真正删除 lyricalign demo_diagnostics 的 A/B 内容。剩余磁盘："
  df -h "$(dirname "$DD")" | tail -1
else
  echo "以上是预览（DRY-RUN），未删除任何文件。确认无误后请运行："
  echo "  bash /home/hyan/a.sh --apply"
fi
