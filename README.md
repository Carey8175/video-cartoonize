# video-cartoonize

`video-cartoonize` is a single-step CLI for an agent-driven real-video to cartoon/anime workflow.

The CLI does not run the whole workflow by itself. Each command executes exactly one step, writes `state.json`, and returns JSON output for an agent to inspect before choosing the next command.

## Install

Public repo install:

```bash
bash -c 'bash <(curl -fsSL https://raw.githubusercontent.com/Carey8175/video-cartoonize/main/install.sh)'
```

If the repo is private or GitHub rate limits raw downloads, pass `GITHUB_TOKEN`:

```bash
bash -c 'bash <(curl -fsSL -H "Authorization: token $GITHUB_TOKEN" https://raw.githubusercontent.com/Carey8175/video-cartoonize/main/install.sh)'
```

The installer creates an isolated venv under `~/.local/share/video-cartoonize/` and writes the global command to `~/.local/bin/cartoonize`. It does not require `pipx`.

Optional install overrides:

```bash
VIDEO_CARTOONIZE_HOME="$HOME/.video-cartoonize" \
VIDEO_CARTOONIZE_BIN_DIR="$HOME/bin" \
VIDEO_CARTOONIZE_REF="main" \
bash -c 'bash <(curl -fsSL https://raw.githubusercontent.com/Carey8175/video-cartoonize/main/install.sh)'
```

After install, the command is global:

```bash
cartoonize --help
```

## Credentials

You can use environment variables:

```bash
export ARK_API_KEY="..."
export ARK_AK="..."
export ARK_SK="..."
export ARK_REGION="ap-southeast-1"

export TOS_ACCESS_KEY="..."
export TOS_SECRET_KEY="..."
export TOS_ENDPOINT="tos-ap-southeast-1.bytepluses.com"
export TOS_REGION="ap-southeast-1"
export TOS_BUCKET="..."
```

Or write config files under:

```text
~/.config/video-cartoonize/
├── ark_api_key.txt
├── ark_ak_sk.json
└── tos_credentials.json
```

Run:

```bash
cartoonize doctor
```

## Agent-Controlled Steps

Run one command at a time:

```bash
cartoonize init --input video.mp4 --work-dir ./out --style anime
cartoonize split --work-dir ./out
cartoonize keyframes --work-dir ./out
cartoonize cartoon --work-dir ./out
cartoonize vlm --work-dir ./out
cartoonize upload --work-dir ./out
cartoonize submit --work-dir ./out
cartoonize poll --work-dir ./out
cartoonize mux --work-dir ./out
cartoonize merge --work-dir ./out
```

`cartoonize poll` exits with code `1` while tasks are still running and code `0` when every task has reached a terminal state.

Inspect state any time:

```bash
cartoonize status --work-dir ./out
```

## Update / Remove

```bash
# update: rerun the install command
bash -c 'bash <(curl -fsSL https://raw.githubusercontent.com/Carey8175/video-cartoonize/main/install.sh)'

# remove
rm -rf ~/.local/share/video-cartoonize ~/.local/bin/cartoonize
```
