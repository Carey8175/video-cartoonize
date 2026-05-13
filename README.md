# video-cartoonize

`video-cartoonize` is a single-step CLI for an agent-driven real-video to cartoon/anime workflow.

The CLI does not run the whole workflow by itself. Each command executes exactly one step, writes `state.json`, and returns JSON output for an agent to inspect before choosing the next command.

## Install

From a GitHub repo, users can install globally with one command:

```bash
pipx install "git+https://github.com/<owner>/<repo>.git"
```

For private repos over SSH:

```bash
pipx install "git+ssh://git@github.com/<owner>/<repo>.git"
```

If the package lives in a subdirectory of a repo:

```bash
pipx install "git+https://github.com/<owner>/<repo>.git#subdirectory=video_cartoonize"
```

Local development:

```bash
pipx install -e . --force
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
pipx reinstall video-cartoonize
pipx uninstall video-cartoonize
```
