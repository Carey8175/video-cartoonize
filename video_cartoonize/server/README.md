# Cartoonize Console — Backend Server

FastAPI service layer for the Console web UI.  
**Business logic lives entirely in the `cartoonize` CLI** — this server only handles HTTP, DB, Redis, and SSE.

## Quick start (local dev)

```bash
# 1. 启动 PostgreSQL + Redis（Docker）
docker compose up -d

# 2. 安装 server 依赖
pip install -e ".[server]"

# 3. 启动服务（SQLite 默认，无需 Docker）
cartoonize serve --port 7317

# 或连接 Docker 数据库：
DATABASE_URL=postgresql+asyncpg://cartoonize:cartoonize@localhost/cartoonize \
REDIS_URL=redis://localhost:6379/0 \
cartoonize serve --port 7317 --reload
```

API docs: http://localhost:7317/api/docs

## 扩展性设计

### 新增 CLI 步骤 → 只需 1 步

编辑 `pipeline/registry.py`，在 `STEP_REGISTRY` 里加一条：

```python
"my_new_step": StepDef(
    cli_args=lambda req: ["--my-flag", req.get("my_param", "default")],
    timeout=300,
    description="My new step description",
),
```

完成。路由、Job 执行、SSE 推送、DB 记录全部自动适配。

### CLI state.json schema 升级 → 只需改 1 个文件

`services/state_adapter.py` 是 state.json → API schema 的唯一转换点。  
CLI 升级 state schema 后，只改这一个文件，其余层无需动。

## 架构

```
CLI subprocess (cartoonize <step>)
      ↑ 子进程调用（唯一耦合点）
cli_runner.py
      ↑
job_service.py  ←→  DB (pipeline_jobs)
      ↑               Redis (lock + progress)
pipeline/registry.py  ←  StepDef (cli_args, timeout)
      
state_adapter.py  ←  state.json（业务数据 source of truth）
      ↓
Pydantic schemas → FastAPI routers → HTTP response
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HOST` | `127.0.0.1` | 绑定地址 |
| `PORT` | `7317` | 端口 |
| `WORK_ROOT` | `~/cartoonize` | project 根目录 |
| `DATABASE_URL` | `sqlite+aiosqlite://…` | SQLite（开发）/ PostgreSQL（生产） |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis 地址 |
| `REDIS_ENABLED` | `true` | `false` 时降级为无 SSE 广播模式 |
| `CORS_ORIGINS` | `["http://localhost:5173"]` | 允许的前端 origin |
