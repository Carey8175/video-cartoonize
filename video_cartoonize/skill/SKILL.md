---
name: video-cartoonize
description: >
  End-to-end real-video → anime/manga-style video pipeline driven by the
  `cartoonize` CLI. Splits a live-action video into clips, extracts key frames
  (sub-shot first frames + last frame) per clip, identifies recurring characters
  with InsightFace, generates anime character references for protagonists and
  supporting roles, converts key frames to cartoon style via Seedream 5.0 I2I
  with per-frame character refs, generates per-clip Seedance prompts via Seed
  2.0 Lite video analysis, uploads everything through the ModelArk Assets API
  (required to bypass privacy filter), submits each clip to Seedance 2.0 with
  key frame cartoon refs + multi-beat prompt, muxes original audio back, and
  merges all clips into one final video.

  Use this skill whenever the user mentions: cartoonize video, video
  cartoonization, 视频卡通化, 卡通化视频, cartoon style video, 动漫风格视频,
  cartoon pipeline, video to cartoon, 视频转卡通, 视频动漫化, video to anime,
  or asks to apply cartoon/anime/Pixar style to a real-life video using Seedance.
---

# Video Cartoonize Pipeline (CLI version)

## 安装 CLI

**首次使用前，先确认 `cartoonize` 命令是否可用：**

```bash
cartoonize --help
```

如果命令不存在，用一键脚本安装：

```bash
curl -fsSL https://raw.githubusercontent.com/Carey8175/video-cartoonize/main/install.sh | bash
```

安装完成后，脚本会自动：
1. 将 `cartoonize` 命令安装到 `~/.local/bin/`
2. 将本 skill 复制到 `~/.claude/skills/video-cartoonize/`

安装后如果 `cartoonize` 找不到，把路径加到 shell：
```bash
export PATH="$HOME/.local/bin:$PATH"
```

**安装完成后，配置凭证（只需一次）：**

```bash
cartoonize doctor    # 检查缺少哪些凭证
```

凭证文件位置：`~/.config/video-cartoonize/`

| 文件 | 必填内容 | 用途 |
|------|---------|------|
| `ark_api_key.txt` | ARK API Key（一行）| Seedream / VLM / Seedance 生成 |
| `ark_ak_sk.json` | `{"ak":"...","sk":"..."}` | Assets API + TOS 上传（共用同一组密钥）|
| `tos_credentials.json` | `{"bucket":"your-bucket"}` | TOS bucket 名（AK/SK 自动复用上面那组）|

> **说明**：ARK AK/SK 和 TOS AK/SK 是同一组密钥，无需重复填写。  
> TOS endpoint 默认 `tos-ap-southeast-1.bytepluses.com`，无需填写；如需覆盖可在 `tos_credentials.json` 中加 `"endpoint"` 字段。

也可以用环境变量：`ARK_API_KEY`、`ARK_AK` / `ARK_SK`、`TOS_BUCKET`。

---

## 架构说明

`cartoonize` CLI **每次只执行一步**，输出 JSON 结果供 agent 读取。  
**你（agent）负责控制流程**：读输出、判断结果、决定下一步。  
CLI 路径：安装后全局可用 `cartoonize`，或 `~/.local/bin/cartoonize`。

```
Input video
    │
    ▼
cartoonize init        → 初始化项目，写 state.json
    │
    ▼
cartoonize split       → Phase 1: 场景切分 + 像素缩放
    │
    ▼
cartoonize keyframes   → Phase 2a: 子镜头关键帧提取
    │                    ★ 检查 keyframes/ 目录，确认关键帧合理再继续
    ▼
cartoonize identify    → Phase 2a-opt: InsightFace 人物识别 + 主角/配角/路人分类 + keyframe 角色映射
    │                    ★ 新流程必须跑；首次会下载 buffalo_l 模型，需 insightface/onnxruntime
    ▼
cartoonize char-refs   → Phase 2a-opt: Seedream I2I 生成主角/配角动漫参考图
    │                    ★ 后续 cartoon 会自动给对应 keyframe 注入角色参考图，提升人物一致性
    ▼
cartoonize cartoon  ──┐ Phase 2b: Seedream I2I 卡通化（自动使用角色 refs）
cartoonize vlm      ──┘ Phase 3:  VLM 场景分析      ← 两个可以并行启动
    │
    ▼
cartoonize upload      → Phase 4: TOS 上传 + Assets API 注册（★ 必须）
    │
    ▼
cartoonize submit      → Phase 5a: 批量提交 Seedance 任务
    │
    ▼
cartoonize poll        → Phase 5b: 查询进度（重复直到 exit 0）
cartoonize verify      → Phase 5c: VLM 校验是否动漫风格，失败可自动重试
    │
    ▼
cartoonize mux         → Phase 6: 下载 + 合并原始音轨
    │
    ▼
cartoonize merge       → Phase 7: 拼接最终视频

cartoonize billing     → 查看项目 Seedream/VLM/Seedance 用量
cartoonize estimate    → 预估项目总成本
cartoonize status      → 查看当前流水线进度
cartoonize logs --clip-id N → 看某个 clip 的完整事件日志
```

> CLI 会**自动**把每个 clip 的事件（run/poll/verify/auto_resubmit/mux）追加到
> `<work_dir>/logs/clip_NN.jsonl`。Agent 不需要自己保存日志，事后排查时
> `cartoonize logs --clip-id N` 看完整时间线即可。

---

## ⚠️ Critical Gotchas（先读这里）

### #1 — 真人视频必须走 Assets API

直接 HTTPS URL 传给 Seedance 会返回：
```
HTTP 400  InputVideoSensitiveContentDetected.PrivacyInformation
"The request failed because the input video may contain real person."
```
卡通化关键帧（虚拟人像）同样受限：`InputImageSensitiveContentDetected`。  
`cartoonize upload` 已处理此问题，**不要跳过这步**。

### #2 — Seedance 输出无声

Seedance video-edit 模式只输出画面，无音频。  
`cartoonize mux` 会把原始音轨贴回去，不要忘记执行。

### #3 — 关键帧质量决定最终效果

Phase 2a 提取的关键帧（子镜头首帧 + 片尾帧）直接影响 Seedream 风格转换质量。  
执行 `keyframes` 后，**检查 `<work-dir>/keyframes/clip_XX/` 目录**，确认：
- 帧画面清晰（不是黑帧/转场模糊帧）
- 每个 clip 至少有 1 帧
- 如果关键帧太少/太多，调整 `--subshot-threshold`（默认 27.0，越低越多）

> **0.14.6+**：PySceneDetect 对 K-Drama 软切 / 单场景长镜头普遍欠采样（同景别
> 复用 + 同色调 = 帧间 HSV 差值低于阈值）。verify 失败时 `cartoonize poll` 会
> **自动 append 关键帧**：attempt 2 用 3s 时间保底补齐间隔，attempt 3 把总数补到
> 10 张。**不重画已有 cartoon**，只对新增帧调 Seedream，成本可控。

### #4 — poll 在 verify 失败时会变慢（0.14.6+）

之前 `cartoonize poll --clip-id N` 是秒级返回；从 0.14.6 起，若 verify 失败触发
attempt 2 / 3 自动重试，poll 会**同步**跑 ffmpeg 抽新帧 + Seedream I2I 画新帧 +
TOS/Assets 上传，单次调用可能 30-90s。`while ! cartoonize poll; do sleep 30; done`
循环仍然正常工作，只是某一次会停顿一下。

### #5 — 新流程必须先做人脸/角色一致性（0.14.10+）

`cartoonize identify` 会用 InsightFace 从原视频采样做人脸检测与聚类，把角色分为
protagonist / supporting / extra，并把每张 keyframe 映射到出现的主角/配角。
`cartoonize char-refs` 会为主角/配角生成动漫角色参考图。之后 `cartoonize cartoon`
会自动给对应 keyframe 注入这些角色参考图，提升跨镜头人物一致性。

首次运行 `identify` 可能自动下载 InsightFace `buffalo_l` 模型（约 300MB），并要求
本地环境已安装 `insightface` 和 `onnxruntime`。如果缺依赖，先在 cartoonize 的 venv
里安装它们，不要跳过人物流程。

---

## Runbook — 逐步执行

### Step 0 — 初始化项目

```bash
cartoonize init \
  --input /path/to/video.mp4 \
  --work-dir ./my_output \
  --style anime \
  --ratio 9:16 \
  --seedance-model standard      # 或 fast，或自定义 endpoint ID
```

可用风格：`manhwa` / `anime` / `manhua` / `pixar` / `comic` / `noir` / `custom`  
自定义风格需加 `--ref-images a.jpg b.jpg`

**Seedance 模型（`--seedance-model`）：**

| 值 | 实际 endpoint ID | 说明 |
|---|---|---|
| `standard`（默认）| `dreamina-seedance-2-0-260128` | 质量更高，更慢更贵 |
| `fast` | `dreamina-seedance-2-0-fast-260128` | 质量略低，速度快约 2-3 倍 |
| 任意 endpoint ID | 同上 | 自定义模型，原样使用 |

输出：
```json
{
  "status": "ok",
  "work_dir": "/path/to/my_output",
  "input_video": "/path/to/video.mp4",
  "style": "anime",
  "seedance_model": "dreamina-seedance-2-0-260128"
}
```

**保存 `work_dir`，后续所有步骤都要带 `--work-dir`。**

凭证（init 之前先确认）：
```bash
cartoonize doctor --work-dir ./my_output
```
检查项：ffmpeg、ARK API Key、ARK AK/SK（同时用于 Assets API 和 TOS）、TOS bucket。  
凭证文件位置：`~/.config/video-cartoonize/`

---

### Step 1 — 场景切分 + 缩放

```bash
cartoonize split --work-dir ./my_output
```

输出：
```json
{
  "status": "ok",
  "clips": 12,
  "paths": ["/path/my_output/resized/video-Clip-001.mp4", ...]
}
```

**判断**：clips 数量一般 5–30 个。如果太多（>50），考虑提高 `--scene-threshold`（重新 init）。

---

### Step 2a — 关键帧提取

```bash
cartoonize keyframes --work-dir ./my_output
```

输出：
```json
{
  "status": "ok",
  "clips": [
    {"clip_id": 0, "keyframes": 3, "paths": ["...sub_00.jpg", "...sub_01.jpg", "...last_frame.jpg"]},
    {"clip_id": 1, "keyframes": 2, "paths": ["..."]},
    ...
  ]
}
```

**★ 执行完后检查 `my_output/keyframes/clip_XX/` 里的图片**，确认帧质量再继续。  
如果某个 clip 的 `keyframes` 为 0，说明提取失败，记录下来但可以继续（该 clip 会在后续跳过）。

---

### Step 2b — 人物识别 + 角色参考图（0.14.10+，★ 新流程必须使用）

先运行人物识别。它会从原视频采样，用 InsightFace 聚类人脸，分类主角/配角/路人，
并在 keyframes 已存在时生成 `char_keyframe_map`：

```bash
cartoonize identify --work-dir ./my_output
```

输出：
```json
{
  "status": "ok",
  "protagonists": 1,
  "supporting": 2,
  "total_chars": 5,
  "kf_mapped_clips": 12,
  "characters": [
    {"char_id": 0, "role": "protagonist", "freq": 0.42, "face_ref": ".../characters/char_00_face.jpg"}
  ]
}
```

再为主角/配角生成动漫角色参考图：

```bash
cartoonize char-refs --work-dir ./my_output
```

输出：
```json
{
  "status": "ok",
  "generated": 3,
  "total": 5,
  "characters": [
    {"char_id": 0, "role": "protagonist", "anime_ref": ".../characters/char_00_anime.jpg"}
  ]
}
```

**判断与注意：**
- `identify` 依赖 `insightface` + `onnxruntime`；缺依赖时先安装，不要跳过新流程。
- 首次运行会下载 InsightFace `buffalo_l` 模型，耗时较长属于正常。
- `identify` 最好在 `keyframes` 之后跑；如果先跑了 identify，需在 keyframes 后重跑一次 identify，以生成 `char_keyframe_map`。
- `char-refs` 只会为 protagonist/supporting 生成参考图，extra 不生成。
- 后续 `cartoonize run --clip-id N` 内部调用 `cartoon` 时，会自动读取 `characters` + `char_keyframe_map`，给对应 keyframe 注入角色动漫参考图；agent 不需要手动传参数。

---

### Step 2c–5a — 两阶段提交 + 收割模式（★ 必须使用）

**Agent 唯一需要调度的命令是 `cartoonize run --clip-id N`**——它一站式跑 cartoon+vlm+upload+submit，返回 task_id。

```
阶段 A：只提交，不 poll（限并发 6）
  cartoonize run --clip-id N    ← 内部并行 cartoon+vlm, 串行 upload→submit
  ↓ 返回 {task_id, mode}
  clip 获得 task_id

阶段 B：所有 clip 都已提交后，再统一收割
  cartoonize poll --clip-id N   ← 对所有 pending clip 轮询；CLI 内部自动 verify + retry
    ↓ exit 0 → clip done（pass 或 fallback）
    ↓ exit 1 → clip still running（下轮继续）
```

**核心原则：** 阶段 A 只负责把所有 clip 尽快提交到 Seedance 队列。不要在提交阶段穿插
`poll`，因为 `cartoonize poll --clip-id N` 可能触发 verify 失败后的关键帧补齐、
Seedream I2I、Assets 上传和自动 resubmit，单次会卡 30-180s，拖慢后续 clip 的提交。
等全部 clip 都有 `task_id` 后，再进入阶段 B 做全量收割。

这里的“poll all”是指 agent 遍历所有 pending clip 执行
`cartoonize poll --clip-id N`。不要依赖无 `--clip-id` 的 `cartoonize poll` 做最终收割：
无 `--clip-id` 是旧的状态查询模式，只查 Seedance 状态，不集成 verify / retry。

#### ★ 并发控制规则

| 项 | 限制 |
|---|---|
| 阶段 A 的 `cartoonize run` 并发 | **最多 6 个同时** |
| 阶段 A 是否 poll | **不要 poll**，只提交所有未提交 clip |
| Seedance 队列大小 | 不限，全部提交给服务端排队 |
| 阶段 B 的 poll 方式 | 遍历 pending clip，逐个 `cartoonize poll --clip-id N` |
| poll 轮次间隔 | 每轮 sweep 后 sleep 30s；单个 poll 可能因 retry 耗时 30-180s |
| verify / retry | 由 `poll --clip-id` 内部处理，agent 不直接调 `verify` |

#### Agent 调度伪代码（极简：只用 run + poll，2 个 exit code）

```python
N = 6
all_clips = list(range(total_clips))

# Phase A: submit everything first. Do not poll in this phase.
todo = [cid for cid in all_clips if not state.clip[cid].task_id]
while todo:
    batch = pop_up_to(todo, N)
    results = run_in_parallel([
        f"cartoonize run --work-dir ./out --clip-id {cid}"
        for cid in batch
    ])
    retry_once_for_failed_runs(results)

# Phase B: sweep all pending clips until all have output_url.
while True:
    pending = [
        cid for cid in all_clips
        if state.clip[cid].status != "success" or not state.clip[cid].output_url
    ]
    if not pending:
        break

    for cid in pending:
        res = run(f"cartoonize poll --work-dir ./out --clip-id {cid}")
        if res.exit == 0:
            mark_done(cid)          # pass 或 fallback 都算 done
        else:
            keep_for_next_sweep(cid)

    sleep(30)
```

> **`cartoonize poll --clip-id N` 是 agent 唯一需要的查询命令**。CLI 内部已集成：
> - Seedance 状态查询
> - VLM 风格校验（成功后自动跑）
> - 失败时**自动 resubmit Seedance**（第 3 次切 image-only）
> - 3 次都失败 → 用兜底视频 done
>
> Agent **不需要**直接调 `verify`，**不需要**自己处理 retry 逻辑。

#### Bash 极简版

```bash
# Phase A: 提交所有 clip，限制 6 并发。这里不要 poll。
TOTAL_CLIPS=$(python3 -c 'import json; print(len(json.load(open("./out/state.json"))["clips"]))')
printf '%s\n' $(seq 0 $((TOTAL_CLIPS - 1))) | xargs -P6 -I{} \
  cartoonize run --work-dir ./out --clip-id {}

# Phase B: 全量 sweep。每轮遍历所有未完成 clip 的 --clip-id poll。
while true; do
  remaining=0
  for cid in $(seq 0 $((TOTAL_CLIPS - 1))); do
    cartoonize poll --work-dir ./out --clip-id "$cid" || remaining=1
  done
  [ "$remaining" -eq 0 ] && break
  sleep 30
done
```

> **两个命令：** `cartoonize run --clip-id N` 启动；`cartoonize poll --clip-id N` 查询直到 done。

#### ⚠️ 反面案例

```bash
# ❌ 不要自己拼 4 个子命令，用 run 一站式
cartoonize cartoon --clip-id 0
cartoonize vlm     --clip-id 0
cartoonize upload  --clip-id 0
cartoonize submit  --clip-id 0
```

```bash
# ❌ 死等单 clip 的 Seedance —— agent 完全闲置
cartoonize run --clip-id 0
until cartoonize poll --clip-id 0; do sleep 30; done   # ← 卡 5min！
```

```bash
# ❌ 不带 --clip-id 跑全量，所有 63 个 clip 一次性串行处理
cartoonize cartoon
cartoonize vlm
```

```bash
# ❌ 全量串行 cartoon → 等所有完了才能 upload，浪费时间
cartoonize cartoon --work-dir ./out
cartoonize vlm     --work-dir ./out
cartoonize upload  --work-dir ./out
cartoonize submit  --work-dir ./out
```

#### 全量模式仅适用：

- clip 总数 ≤ 3（并发收益太小）
- 调试 / 重跑某个失败阶段

> **state.json 并发安全（0.9.2+）**：`cartoon` / `vlm` / `upload` / `submit` 都使用字段级合并（`merge_clip_fields`），每个命令只写自己负责的字段（如 `upload` 只写 `subshot_cartoon_urls` 和 `clip_asset_urls`，不动 `task_id`、`status` 等）。多 clip 并发 + 跨命令并发都不会互相覆盖。
>
> ⚠ 之前 0.9.1 及更早版本用整 dict 替换会有罕见竞态（cartoon 还在跑时 upload 启动的极端场景）。0.9.2 修复。

**cartoon 输出：**
```json
{
  "status": "ok",
  "clips": [
    {"clip_id": 0, "cartoons": 3, "paths": ["...sub_00_cartoon.jpg", ...]},
    ...
  ]
}
```

`cartoons` 数应等于 `keyframes` 数。如果有帧 Seedream 失败（数量少），可以记录但继续。

**vlm 输出：**
```json
{
  "status": "ok",
  "prompts": {
    "0": "This is a video generation task — generate a brand-new animated video...",
    ...
  }
}
```

**两个都完成后再执行 Step 4。**

---

### Step 4 — TOS 上传 + Assets API 注册（★ 必须）

```bash
cartoonize upload --work-dir ./my_output
```

内部流程：
1. 并行上传所有 resized 视频 + cartoon 关键帧到 TOS（获取预签名 URL）
2. 通过 Assets API 注册为 Video/Image asset，等待 Status=Active
3. 将 `asset://` URL 写回 state.json

输出：
```json
{
  "status": "ok",
  "group_id": "asset-group-xxx",
  "tos_uploaded": 25,
  "assets_active": 25
}
```

**判断**：`tos_uploaded` 应等于 `assets_active`。不相等说明有 asset 注册超时，重新运行 `upload`。

---

### Step 5a — 批量提交 Seedance 任务

```bash
cartoonize submit --work-dir ./my_output
```

一次性提交所有 clip（秒级完成），不等待生成结果。

输出：
```json
{
  "status": "ok",
  "ratio": "9:16",
  "submitted": [
    {"clip_id": 0, "task_id": "cgt-20260513-xxxxx"},
    {"clip_id": 1, "task_id": "cgt-20260513-yyyyy"},
    ...
  ]
}
```

---

### Step 5b — 轮询 Seedance 结果

```bash
cartoonize poll --work-dir ./my_output
```

**无 `--clip-id` 是旧的全量状态查询模式，只查询 Seedance 任务状态，不做 VLM verify，也不触发自动 retry。**
Agent 不应把它作为最终收割入口。最终收割请按 Step 2c 的阶段 B，遍历 pending clip 调
`cartoonize poll --work-dir ./my_output --clip-id N`。

无 `--clip-id` 的返回语义：
- exit 0 = 全部任务已终结（success 或 failed）  
- exit 1 = 仍有任务运行中

输出：
```json
{
  "status": "running",
  "still_running": 3,
  "clips": [
    {"clip_id": 0, "status": "success", "task_id": "cgt-..."},
    {"clip_id": 1, "status": "running", "task_id": "cgt-..."},
    {"clip_id": 2, "status": "failed",  "task_id": "cgt-..."}
  ]
}
```

**Agent 最终收割逻辑（推荐）：**

```
loop:
  pending = state.json 中 status != success 或 output_url 为空的 clip
  if pending is empty:
    break
  for each cid in pending:
    run: cartoonize poll --work-dir ./my_output --clip-id cid
    # exit 0 = 该 clip done；exit 1 = 仍运行或内部已自动 resubmit
  wait 30 seconds
  goto loop
```

Seedance 一般每个 clip 需 2–5 分钟，10 个 clip 约 10–20 分钟。  
**poll 间隔不要小于 20s**，避免无意义的 API 调用。

---

### Step 5c — VLM 风格校验（自动；手动命令仅调试）

```bash
cartoonize verify --work-dir ./my_output
```

Agent 正常流水线不要直接调用 `verify`。从 0.14.6 起，`cartoonize poll --clip-id N`
已经集成 VLM 风格校验和自动重试；`verify` 只保留给人工调试旧项目使用。

自动校验逻辑会让 VLM 看一遍 Seedance 生成的视频，判断是不是动漫/卡通风格：

- **通过** → `style_verified=true`，进入下一步
- **不通过** 且 `verify_attempts < 3` → `poll --clip-id` 内部自动补关键帧并 resubmit。
  **`output_url` 不会被清空**，
  作为兜底视频保留；每一次的 task_id / output_url / 判定结果都会归档到
  `clip.attempts[]` 数组里
- **不通过** 且 `verify_attempts = 3` → 不再重试，`output_url` 和 `task_id`
  都保留为最后一次的结果，status=success 不变，仅 `style_verified=false`。
  mux 时仍会处理（用最后一次的视频作兜底）

**🎯 提交策略 + 关键帧补齐（0.14.6+，poll 自动调度）：**

每次 verify 失败后，`cartoonize poll` 在内部 resubmit 之前会**先按 append-only 策略
补齐关键帧**——已有的 cartoon 帧和 asset URLs 全部保留，只画/上传新增的那几张。

| 重试次数 | 关键帧动作 | Seedance 模式 | 输入 |
|---------|-----------|--------------|------|
| 第 1 次（attempts=0）| 用 `cartoonize keyframes` 阶段抽出的默认帧 | `video+image` | 原视频 + cartoon key frames |
| 第 2 次（attempts=1）| **3s 时间保底**：相邻关键帧间隔 > 3s 就等距补一帧（如间隔 9s → 补 2 帧）。**仅新增帧走 Seedream**，已有 cartoon 不动 | `video+image` | 原视频 + 补齐后的 cartoon key frames |
| **第 3 次（attempts=2）**| **均匀补齐到 10 张**：贪心 farthest-point，把总数补到 10。**只新增不重画** | **`image-only`** | **只传 key frames（10 张），不传原视频** |

设计原则：失败往往是因为关键帧覆盖不到位（PySceneDetect 对 K-Drama 软切失效、单
场景长镜头采样太稀）。每多一次重试就增加一道关键帧密度，给 Seedance 更强的时间
轴锚点。append-only 让重试成本可控（attempt 2 通常加 1-3 张 Seedream，~$0.04-0.11；
attempt 3 加 5-8 张到 10 张总数，~$0.18-0.28）。

submit 输出的 JSON 会带 `"mode": "video+image"` / `"image-only"`，agent 可以看到当前用的哪种模式。
poll 在补齐时会在事件日志写 `poll.retry_keyframe_topup`，含 `strategy`（`with_floor` / `uniform10`）、
`n_keyframes_before` / `n_keyframes_after`。

**调优参数（cli.py 顶部常量，未来若需可挪到 init flags）：**
- `RETRY_FLOOR_GAP_SEC = 3.0` — attempt 2 的时间保底阈值
- `RETRY_UNIFORM_TARGET = 10` — attempt 3 的总帧数目标

每个 clip 在 state.json 里的 `attempts` 字段记录所有历次结果：
```json
"attempts": [
  {"task_id":"cgt-...A","output_url":"https://...A","verdict":"fail","reason":"..."},
  {"task_id":"cgt-...B","output_url":"https://...B","verdict":"fail","reason":"..."},
  {"task_id":"cgt-...C","output_url":"https://...C","verdict":"pass","reason":"..."}
]
```

退出码：
- **0** = 全部通过校验
- **1** = 仍有 clip 需要重试

输出：
```json
{
  "status": "retry_needed",
  "checked": 12, "passed": 10, "failed": 2, "errors": 0,
  "retry_needed": 2,
  "clips": [
    {"clip_id": 3, "verdict": "fail", "reason": "...", "attempts": 1, "will_retry": true},
    {"clip_id": 7, "verdict": "pass", "reason": "...", "attempts": 1}
  ]
}
```

**Agent 不需要手动实现重试循环。**

> ⚠️ 从 0.14.6 起 verify 重试全部封装在 `cartoonize poll --clip-id N` 内部：
> 1) Seedance 状态查询 → 2) 自动 VLM 校验 → 3) 失败时按 attempt 调度关键帧 append
> （3s floor / 10 张 uniform）→ 4) 重画新增 cartoon + 重传 Assets → 5) 自动
> resubmit Seedance（attempt 3 切 image-only）→ 6) 3 次都失败用最后一次作 fallback。
>
> Agent 唯一要做的是 **`cartoonize poll --clip-id N` exit 0 = done，exit 1 = sleep 30s 再来一次**。
> 见 Step 2c–5a 的两阶段调度：先把所有 clip run 提交完，再对 pending clips 做 poll sweep。
> （0.14.6+ 在触发 append 时单次 poll 可能停顿 30-180s 做 Seedream / Assets 上传，属于正常）。

---

### Step 6 — 下载 + 合并原始音轨

```bash
cartoonize mux --work-dir ./my_output                # 全量：处理所有 status=success 的 clip
cartoonize mux --work-dir ./my_output --clip-id 3    # 0.14.6+：只 mux 指定 clip
```

对每个 success 的 clip：
1. 从 Seedance output_url 下载静音视频
2. 用 ffmpeg 将卡通视频按原片时长**拉伸/压缩**（setpts + fps 规整）
3. 直接贴回原音轨（`-c:a copy`，**bit-identical**，无重编码、无变调）

> **0.14.8+ 行为变化**：之前是用 atempo 拉伸音频去匹配 Seedance 输出时长，会带来
> 人声变调和长片累积漂移；现在改为反过来——拉伸视频（Seedance 通常向上取整到整数
> 秒，长出 5-15%）去匹配原音频，音频保持 bit-for-bit 原样。视频微速变化对动作
> 几乎无感，但音质和音画同步是无损的。

**`--clip-id` 使用场景**（0.14.6+）：手动改单个 clip 的关键帧 / 重画 cartoon /
重新提交 Seedance 后，只想 mux 这个 clip，不动其它已 mux 好的 clip。state 写入
也改成了字段级合并（`merge_clip_fields`），不会覆盖其它 clip 的字段。

输出：
```json
{
  "status": "ok",
  "clips": [
    {"clip_id": 0, "status": "ok", "output": "/path/my_output/final/clip_00.mp4"},
    {"clip_id": 2, "status": "ok", "output": "/path/my_output/final/clip_02.mp4"}
  ]
}
```

---

### Step 7 — 拼接最终视频

```bash
cartoonize merge --work-dir ./my_output
```

输出：
```json
{
  "status": "ok",
  "final_video": "/path/my_output/final_cartoonized.mp4",
  "merged_clips": 11,
  "total_clips": 12
}
```

完成。`final_cartoonized.mp4` 即为带音频的完整卡通化视频。

---

## 工作目录结构

```
<work-dir>/
├── state.json              ← 所有步骤的检查点（CLI 读写，agent 可读）
├── clips/                  ← 原始场景切分片段
├── resized/                ← 像素缩放后片段（≤ 927408 px）
├── keyframes/
│   └── clip_XX/            ← 子镜头首帧 + 最后一帧（真实照片）
├── cartoons/
│   └── clip_XX/            ← Seedream I2I 卡通化关键帧
├── cartoonized/            ← Seedance 原始输出（无声）
├── final/                  ← 合并音轨后各片段
└── final_cartoonized.mp4   ← ★ 最终完整视频
```

随时查看进度：

```bash
cartoonize status --work-dir ./my_output
```

---

## 可调参数

在 `cartoonize init` 时指定：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--scene-threshold` | 25.0 | Phase 1: 越低切分越多 |
| `--subshot-threshold` | 27.0 | Phase 2a: 越低子镜头越多 |
| `--style` | `anime` | 风格预设 |
| `--ratio` | 自动检测 | 16:9 / 9:16 / 1:1 / 4:3 / 3:4 / 21:9 |
| `--resolution` | `720p` | Seedance 输出分辨率 |
| `--seedance-model` | `standard` | `standard` / `fast` / 自定义 endpoint ID |

---

## Troubleshooting

| 现象 | 阶段 | 处理方法 |
|------|------|---------|
| 子镜头未检测到 | keyframes | 降低 `--subshot-threshold`（试 20.0），重新 init + split + keyframes。**注意**：对 K-Drama 软切场景调阈值帮助有限，让 poll 的 0.14.6 自动 append 机制兜底更稳妥 |
| 关键帧太多/误检 | keyframes | 升高 `--subshot-threshold`（试 30.0） |
| verify 反复失败因关键帧覆盖差 | poll | **0.14.6+** poll 在 attempt 2/3 自动 append；如果还想手动加，编辑 state.json 的 `subshot_frame_paths` 并清空 `subshot_cartoon_urls`，然后 `cartoon --clip-id N` + `upload --clip-id N` + `submit --clip-id N` |
| Seedream 风格不准 | cartoon | 用 `--style custom --ref-images` 提供更强参考图 |
| Seedream 返回 404 | cartoon | 检查 model 是否用 date-stamped 版本 `seedream-5-0-260128` |
| Seedream `InputImageSensitiveContentDetected` | cartoon | 个别关键帧因人像/敏感元素被拦截，函数会跳过失败帧并打印 `✗ Seedream failed`，state 只记录成功的；换帧重抽（手动调时间戳）或接受短缺 |
| HTTP 400 `InputVideoSensitiveContentDetected` | submit | 视频未走 Assets API，重跑 `upload` |
| HTTP 400 `InputImageSensitiveContentDetected` | submit | 卡通帧未走 Assets API，重跑 `upload` |
| assets_active < tos_uploaded | upload | 有 asset 超时，重跑 `upload`（幂等） |
| Seedance 输出无声 | mux | 正常，`mux` 会贴音轨 |
| 单个 clip 重做后 mux 想只刷它 | mux | **0.14.6+** 用 `cartoonize mux --clip-id N`，不影响其它 clip 的 state |
| poll 一直 exit 1 | poll | 检查 `cartoonize status` 看是否有 failed，failed 的 clip 不影响 poll 完成 |
| `cartoonize billing` Seedance 显示 $0 | billing | **0.14.5 之前**全量 `cartoonize poll`（不带 `--clip-id`）不记 Seedance 用量；**0.14.6** 已修复。老项目无法回填，新提交的任务都会计入 |
| 最终视频片段数少于预期 | merge | 部分 clip failed，检查 status 看原因 |
