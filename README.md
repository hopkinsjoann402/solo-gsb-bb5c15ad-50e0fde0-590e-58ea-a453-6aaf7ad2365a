# 合奏节拍网格 API（Ensemble Beat Grid API）

基于 **Python + FastAPI + SQLite** 的合奏节拍网格服务。

提交一小节的**目标时长**和**至少两个声部**；每个声部由依次排列的**发声（note）/休止（rest）事件**组成，事件时长以**正有理数字符串**表示（如 `"1"`、`"1/4"`、`"3/8"`）。服务使用**精确分数**（`fractions.Fraction`，无浮点误差）累加各声部时长：

- 任一声部总时长 ≠ 目标时长 → 返回 `422`，逐声部列出精确差额（`总时长 − 目标时长`），**不保存**；
- 全部相等 → 对所有事件起止点取**并集**，按相邻点切分**半开区间 `[start, end)`** 网格，每段列出各声部正在发声的事件 ID（休止为 `null`）。事件与网格同为半开区间，相邻事件在共享边界上**既不丢音也不重复**。校验通过的小节保存到 SQLite，可按 ID 查询网格。

## 启动（一条命令）

```bash
docker compose up --build
```

该命令自动完成：依赖安装（镜像构建）→ SQLite 数据库初始化（应用启动时建表）→ 服务启动。

- API 地址：**http://localhost:8000**
- 交互式文档（Swagger UI）：**http://localhost:8000/docs**
- 健康检查：`GET http://localhost:8000/health`

停止：`docker compose down`（加 `-v` 可同时删除数据卷）。

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `DATABASE_PATH` | 容器内 `/data/measures.db`；本地运行 `./data/measures.db` | SQLite 数据库文件路径 |

端口映射在 `docker-compose.yml` 中（默认 `8000:8000`）；数据通过命名卷 `beat-grid-data` 持久化。

## API

### `POST /measures` — 提交小节

请求体：

```json
{
  "target_duration": "1",
  "voices": [
    {
      "name": "soprano",
      "events": [
        {"kind": "note", "duration": "1/2"},
        {"kind": "rest", "duration": "1/2"}
      ]
    },
    {
      "name": "alto",
      "events": [
        {"kind": "note", "duration": "1/4"},
        {"kind": "note", "duration": "1/4"},
        {"kind": "note", "duration": "1/4"},
        {"kind": "note", "duration": "1/4"}
      ]
    }
  ]
}
```

约束：`target_duration` 与每个 `duration` 必须为正有理数字符串（`"n"` 或 `"n/d"`，大于 0、分母非 0）；`voices` 至少 2 个且 `name` 唯一；每个声部至少 1 个事件；`kind` 为 `note` 或 `rest`。

成功响应 `201 Created`（事件 ID 规则为 `声部名#序号`，段内休止记为 `null`）：

```json
{
  "id": 1,
  "target_duration": "1",
  "voices": [
    {
      "name": "soprano",
      "events": [
        {"id": "soprano#1", "kind": "note", "duration": "1/2", "start": "0", "end": "1/2"},
        {"id": "soprano#2", "kind": "rest", "duration": "1/2", "start": "1/2", "end": "1"}
      ]
    }
  ],
  "segments": [
    {"start": "0",   "end": "1/4", "voices": {"soprano": "soprano#1", "alto": "alto#1"}},
    {"start": "1/4", "end": "1/2", "voices": {"soprano": "soprano#1", "alto": "alto#2"}},
    {"start": "1/2", "end": "3/4", "voices": {"soprano": null,        "alto": "alto#3"}},
    {"start": "3/4", "end": "1",   "voices": {"soprano": null,        "alto": "alto#4"}}
  ]
}
```

声部总时长与目标不符时响应 `422`，**不保存**：

```json
{
  "detail": {
    "message": "voice durations do not match target_duration",
    "mismatches": [
      {"voice": "soprano", "target": "1", "total": "7/8", "difference": "-1/8"}
    ]
  }
}
```

`difference = 该声部总时长 − 目标时长`（负值表示不足）。时长字符串非法（如 `"1.5"`、`"1/0"`）同样返回 `422`。

### `GET /measures/{id}` — 按 ID 查询网格

返回与创建时相同的结构（另含 `created_at`）；不存在返回 `404`。

```bash
curl http://localhost:8000/measures/1
```

### 示例

```bash
curl -X POST http://localhost:8000/measures \
  -H "Content-Type: application/json" \
  -d '{"target_duration": "4/4", "voices": [
        {"name": "soprano", "events": [{"kind": "note", "duration": "1/2"}, {"kind": "rest", "duration": "1/2"}]},
        {"name": "alto",    "events": [{"kind": "note", "duration": "1/4"}, {"kind": "note", "duration": "1/4"},
                                       {"kind": "note", "duration": "1/4"}, {"kind": "note", "duration": "1/4"}]}
      ]}'
```

## 本地开发与测试

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

核心算法（分数累加、边界并集、半开分段）与 SQLite 持久化为纯标准库实现，测试无需第三方依赖：

```bash
python3 -m unittest discover -s tests -v
```

## 项目结构

```
app/
  main.py     # FastAPI 应用与路由（启动时初始化数据库）
  schemas.py  # Pydantic 请求模型（形状校验）
  grid.py     # 核心：有理数解析、精确累加、边界并集、半开网格（纯标准库）
  db.py       # SQLite 初始化与读写（纯标准库）
tests/
  test_core.py
Dockerfile
docker-compose.yml
requirements.txt
```
