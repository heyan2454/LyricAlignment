# 从官方 ckpt 重训（带漏斗验证）运行说明 · 2026-09-13

## 这次在跑什么
- **起点**：官方底座 `Qwen/Qwen3-ForcedAligner-0.6B-hf`（revision c07281df…），**不从旧 r1/r2 续**；
  已确认 r1 与 r2 是各自独立训的（projector 指纹不同、代码无阶段串联）。
- **形态**：`--stage r2`＝projector + LoRA（音频塔上半，r=8/α=16）联合训练，与现用最佳 ckpt 同构。
- **数据**：M4Singer（train 17,748 / validation 1,711）；seed 20260724（与旧 r2 同 seed，便于对照）。
- **学习率**：分段余弦 `cycle_len=2000`、每周期峰值 ×0.8、warmup 5%；峰值 projector 2e-5 / LoRA 5e-5。
- **保存**：每 50 步存**完整状态**（约 50MB；含优化器，可续训）；
  剩余磁盘 < 20GB 时自动降级为“仅权重”（17.6MB，评估能力不变，但那之后不能原样续训）。
- **验证（漏斗，全部现场算）**：
  - L1 每 50 步、25% 子集（按歌分层，l1⊂l2⊂l3）；
  - L2 只评**新晋**候选（UCB 过筛，最多 16 个）；
  - L3 每 1000 步、全集，每轮最多新纳 8 个、每个候选每层只评一次；
  - 每次评估一次前向出**三条判据**：`fixed`（官方单调化＝现交付链路）、`raw`（逐槽 argmax）、
    `raw+定向修复`；每首歌的数值都存下来（用于误差棒）。
  - 选点规则：**最优 −1SE 内取最早**（避免 800 次子集验证里挑噪声）。
  - 早停：L3 连续 2 轮未超出“最优 +1SE” ⇒ 停（写 `EARLY_STOP.json`）。
- **步数上限**：config 冻结为 12,000（不实际跑到）；随时可停、可续。

## 文件位置
| 内容 | 路径 |
|---|---|
| 运行目录 | `/home/hyan/Data/lyricalign/runs/20260913_qwen_fa_r2_from_official_seed20260724/` |
| 训练日志 | `/home/hyan/Data/lyricalign/runs/_launch_logs/20260913_qwen_fa_r2_from_official.log` |
| 完成哨兵 | 同目录 `…from_official.done`（python 退出后写入） |
| 榜单/选点 | 运行目录 `LEADERBOARD.json`（每轮 L3 后更新）+ `funnel_evals.jsonl`（逐次评估） |
| 早停记录 | 运行目录 `EARLY_STOP.json` |
| 漏斗配置 | 运行目录 `FUNNEL_CONFIG.json`（子集大小、判据、阈值） |

## 查看与干预
```bash
R=/home/hyan/Data/lyricalign/runs/20260913_qwen_fa_r2_from_official_seed20260724
L=/home/hyan/Data/lyricalign/runs/_launch_logs/20260913_qwen_fa_r2_from_official.log
tail -3 "$L"                     # 最新步数/损失
tail -2 "$R/funnel_evals.jsonl"   # 最近一次漏斗评估（三条判据 + 每歌数据在 LEADERBOARD.json）
df -h /root/autodl-tmp | tail -1  # 磁盘（<20GB 会自动降级为仅权重）
ps -ef | grep "[r]un_qwen_fa_lora.py"   # 进程是否活着
kill <PID>                        # 停：随时可停，已完成 ckpt 与榜单都在
```
**续训**（同一 config、不改 `max_steps`，身份校验才会通过）：
```bash
cd /home/hyan/LyricAlignment && source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
export HF_HUB_CACHE=/home/hyan/Data/lyricalign/models/hf_cache HF_HUB_OFFLINE=1 PYTHONPATH=src
python scripts/training/run_qwen_fa_lora.py --config configs/training/qwen_fa_lora_from_official_20260913.yaml \
  --run-dir "$R" --stage r2 --device cuda --local-files-only --resume "$R/checkpoints/<最近完整状态>"
```
注意：**仅权重**的 ckpt 不能续训（会显式报错），要从每 500 步之外的完整状态或最近完整状态恢复。

## 判读规则（跑完后）
1. 看 `LEADERBOARD.json` 的 `pick`：它给出 `selected_step`（1SE 最早）与来自哪一层；
2. 若 L3 的 best 相比旧 r2/step-000750 在同一判据下**没有提升** ⇒ 结论是“训练不是瓶颈”，
   资源转向数据（授权/伪标签）与后处理（不塌陷的定向修复），而不是继续堆步数；
3. 三判据若排序不同（例如 `raw` 挑的点与 `fixed` 不同），就把两个点都留下，
   交主线决定上线用哪个后处理——这正是本次同时记三条判据的目的。

## 已知缺陷：本次运行的漏斗在 step 900 之后“饿死”（2026-09-13 10:15 发现）
`l2_max` 原本是**总量**预算且**按到达顺序**录取，于是 16 个 L2 名额被 step ≤ 900 的早期 ckpt
全部吃掉；之后每个 ckpt 只做 L1，`pending()` 再也产不出新的 L3 任务，`EARLY_STOP.json` 也自
step 1000 起不再更新（提前停止永远不会触发）。实测 L1 曲线在 step 1050 之后仍在缓慢上升
（step 1250 的 L1 = 0.9469 > step 900 的 0.9348），也就是说**当时 `pick`（step 900）不是最优点**。

已在代码里改成**按质量录取（保留最好的，可被顶替）**，对**将来**的运行生效（本次进程已加载旧
代码、不受影响）：
- `l2_max` 现在表示"决赛名额数"（finalist set），不再是"先到先得的总量"；
- 名额满了以后，新候选只有在"看起来比当前**最弱决赛者**还好"（用便宜层的 UCB 比较）时才值得
  多做一次中层评估 —— 这就是"堆/保留最好的"语义，晚到的强候选不会被早到的弱候选永久挤掉；
- 顶替机制要额外花评估次数，所以新增 `l2_budget` 作为**真正的成本上限**（默认 = `l2_max`，
  即不顶替；建议 `2 * l2_max`）；
- `l2_per_round: N` 仍可按 `l3_every` 轮次平滑发放，避免第一轮把预算一次花光
  （注意：只靠 `l2_per_round` 不够——每轮录取的是"当时已知的领先者"，填充阶段仍会先塞进早期
  候选，必须配合上面的顶替规则）；
- `run_qwen_fa_lora.py` 的提前停止改为在**每个 `l3_every` 边界**记账（用当前 L3/L2/L1 的领先者），
  即使本轮没有新的 L3 任务也能停。

新 config 建议写法：`l2_max: 16, l2_budget: 32, l2_per_round: 2`（12 轮 × 2 = 24 ≤ 32，
全程都有名额，且早期弱候选可被顶替）。

## 跑完后的权威选点：top-up 复评（本次必做）
因为上面的缺陷没法热修，本次运行的**权威选点**由事后脚本给出，协议与训练内完全一致
（同样本、同三判据、同容差、同 1SE 规则）：
```bash
cd /home/hyan/LyricAlignment && source /root/miniconda3/etc/profile.d/conda.sh && conda activate lyricalign-qwen
export HF_HUB_CACHE=/home/hyan/Data/lyricalign/models/hf_cache HF_HUB_OFFLINE=1 PYTHONPATH=src
R=/home/hyan/Data/lyricalign/runs/20260913_qwen_fa_r2_from_official_seed20260724
OLD=/home/hyan/Data/lyricalign/runs/20260724_qwen_fa_r2_full_seed20260724/checkpoints/step-000750
python scripts/training/run_funnel_topup.py --run-dir "$R" --dry-run --top-k 8   # 只出计划，不占 GPU
python scripts/training/run_funnel_topup.py --run-dir "$R" --verify-weights --device cpu  # 权重可装载性
python scripts/training/run_funnel_topup.py --run-dir "$R" --levels l2,l3 --top-k 8 --l3-top-k 3 \
  --extra old-r2-750=$OLD        # 真正复评，写 TOPUP.json + topup_evals.jsonl（追加，不覆盖任何旧文件）
```
成本：L2 = 918 项 ≈ 100 s/ckpt，L3 = 1711 项 ≈ 210 s/ckpt；8 个 L2 + 3 个 L3 ≈ 24 min（单卡）。
`TOPUP.json` 里 `pick_by_variant` 同时给 `fixed` / `raw` / `raw_targeted` 三条判据各自的选点。

## 第二臂（仅在本次提前结束、时间富余时）
软标签版（目标桶 ±1 格三角/高斯权重）。**必须先实现自定义 soft-CE**（模型自带 CE 只支持硬标签），
约 25–30 行 + 单测；其余（数据/seed/预算/漏斗）保持不变，这样两臂只差一个变量。
