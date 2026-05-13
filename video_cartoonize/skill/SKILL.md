---
name: video-cartoonize
description: >
  End-to-end real-video → anime/manga-style video pipeline driven by the
  `cartoonize` CLI. Splits a live-action video into clips, extracts key frames
  (sub-shot first frames + last frame) per clip, converts them to cartoon style
  via Seedream 5.0 I2I, generates per-clip Seedance prompts via Seed 2.0 Lite
  video analysis, uploads everything through the ModelArk Assets API (required
  to bypass privacy filter), submits each clip to Seedance 2.0 with key frame
  cartoon refs + multi-beat prompt, muxes original audio back, and merges all
  clips into one final video.

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
cartoonize cartoon  ──┐ Phase 2b: Seedream I2I 卡通化
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
    │
    ▼
cartoonize mux         → Phase 6: 下载 + 合并原始音轨
    │
    ▼
cartoonize merge       → Phase 7: 拼接最终视频
```

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

---

## Runbook — 逐步执行

### Step 0 — 初始化项目

```bash
cartoonize init \
  --input /path/to/video.mp4 \
  --work-dir ./my_output \
  --style anime \
  --ratio 9:16
```

可用风格：`manhwa` / `anime` / `manhua` / `pixar` / `comic` / `noir` / `custom`  
自定义风格需加 `--ref-images a.jpg b.jpg`

输出：
```json
{
  "status": "ok",
  "work_dir": "/path/to/my_output",
  "input_video": "/path/to/video.mp4",
  "style": "anime"
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

### Step 2b + Step 3 — Seedream 卡通化 & VLM 场景分析

`cartoon`、`vlm`、`upload`、`submit` 都支持 `--clip-id N`，可以**按 clip 级别流水线**执行，无需等所有 clip 完成再进入下一步。

**推荐：per-clip 流水线（最快）**

```bash
# split + keyframes 全量完成后，每个 clip 独立流水线
# agent 可并发启动多个 clip，每个 clip 内部 cartoon 和 vlm 并行

# clip_00
cartoonize cartoon --work-dir ./my_output --clip-id 0  # 后台
cartoonize vlm     --work-dir ./my_output --clip-id 0  # 后台（与 cartoon 并行）
# 两者完成后：
cartoonize upload  --work-dir ./my_output --clip-id 0
cartoonize submit  --work-dir ./my_output --clip-id 0

# clip_01（可与 clip_00 同时进行）
cartoonize cartoon --work-dir ./my_output --clip-id 1
cartoonize vlm     --work-dir ./my_output --clip-id 1
cartoonize upload  --work-dir ./my_output --clip-id 1
cartoonize submit  --work-dir ./my_output --clip-id 1

# ... 其余 clip 同理
```

**也可以全量模式（不加 --clip-id）：**

```bash
cartoonize cartoon --work-dir ./my_output   # 处理所有 clip
cartoonize vlm     --work-dir ./my_output
cartoonize upload  --work-dir ./my_output
cartoonize submit  --work-dir ./my_output
```

> **state.json 并发安全说明**：`upload` 和 `submit` 对 state.json 做增量写入，多个 clip 并发执行不会互相覆盖。`cartoon` 和 `vlm` 也只写自己 clip 的字段。

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

**一次性查询**，不阻塞。  
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

**Agent 轮询逻辑：**

```
loop:
  run: cartoonize poll --work-dir ./my_output
  if exit_code == 0:
    break               ← 全部完成，继续下一步
  wait 30 seconds
  goto loop
```

Seedance 一般每个 clip 需 2–5 分钟，10 个 clip 约 10–20 分钟。  
**poll 间隔不要小于 20s**，避免无意义的 API 调用。

---

### Step 6 — 下载 + 合并原始音轨

```bash
cartoonize mux --work-dir ./my_output
```

对每个 success 的 clip：
1. 从 Seedance output_url 下载静音视频
2. 用 ffmpeg 将原始 resized clip 的音轨贴回

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

---

## Troubleshooting

| 现象 | 阶段 | 处理方法 |
|------|------|---------|
| 子镜头未检测到 | keyframes | 降低 `--subshot-threshold`（试 20.0），重新 init + split + keyframes |
| 关键帧太多/误检 | keyframes | 升高 `--subshot-threshold`（试 30.0） |
| Seedream 风格不准 | cartoon | 用 `--style custom --ref-images` 提供更强参考图 |
| Seedream 返回 404 | cartoon | 检查 model 是否用 date-stamped 版本 `seedream-5-0-260128` |
| HTTP 400 `InputVideoSensitiveContentDetected` | submit | 视频未走 Assets API，重跑 `upload` |
| HTTP 400 `InputImageSensitiveContentDetected` | submit | 卡通帧未走 Assets API，重跑 `upload` |
| assets_active < tos_uploaded | upload | 有 asset 超时，重跑 `upload`（幂等） |
| Seedance 输出无声 | mux | 正常，`mux` 会贴音轨 |
| poll 一直 exit 1 | poll | 检查 `cartoonize status` 看是否有 failed，failed 的 clip 不影响 poll 完成 |
| 最终视频片段数少于预期 | merge | 部分 clip failed，检查 status 看原因 |
