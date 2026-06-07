# 剧本对话翻译工具 — 开发计划

> 版本 v1.0  ·  2026-06-07
>
> 本文档为开发依据。不含代码实现。

---

## 1. 项目概述

### 1.1 用户与痛点
- **用户**：短剧编剧团队。日常拿到的「反写剧本」夹带外文（泰/英/阿等）人物对话，编剧不通外语，难以直接二次创作。
- **痛点**：
  - 通用翻译软件输出过于书面，不贴合短剧口语；
  - 切来切去丢失原文上下文，编辑时找不到原句对应位置；
  - 没法横向比较多个 LLM 的翻译效果，选不出最适合短剧语境的模型。

### 1.2 核心能力
1. 上传 / 拖拽 `.docx` `.doc`，或直接粘贴纯文本剧本。
2. AI 自动识别剧本中的人物对话行（区分场景描述行）。
3. 选择目标语言（中、英、泰、阿），选择 LLM 模型，逐行翻译。
4. 在网页上以 **`原文(译文)`** 行内格式呈现，保留原文便于对照。
5. 对同一份剧本，可分别用不同 LLM 翻译并保留所有版本，供人工对比。
6. 一键下载翻译后的全新 `.docx`。

### 1.3 形态示例
输入：

```
艾米丽（局促，低声）：อีธาน พอแค่นี้ดีกว่าไหม ที่นี่คนเยอะเกินไป
```

输出（页面与下载文档）：

```
艾米丽（局促，低声）：อีธาน พอแค่นี้ดีกว่าไหม ที่นี่คนเยอะเกินไป(伊森，要不我们先这样吧，这里人实在太多了)
```

### 1.4 部署目标
- 服务器：`45.78.235.74`
- 公网入口：`https://45.78.235.74:8900`
- 后端内部端口：`127.0.0.1:8901`（不直接对公网暴露）

---

## 2. 技术选型

| 层 | 选型 | 理由 |
| --- | --- | --- |
| 后端 | Python 3.11 + FastAPI + Uvicorn | async 原生、Pydantic 类型校验、各家 LLM Python SDK 生态最齐 |
| 前端 | React 18 + Vite + TypeScript + Tailwind + shadcn/ui | 工程化成熟、组件可控、与「剧本编辑器」型界面契合 |
| 数据库 | SQLite 3 + SQLAlchemy 2.0 (async) + aiosqlite | 零运维、单机部署足够、可平滑迁移 Postgres |
| 文档解析 | python-docx（`.docx`）+ libreoffice headless 转换（`.doc` → `.docx`） | 唯一稳定的 .doc 处理路径 |
| 文档生成 | python-docx | 与解析同栈，输出统一排版的 docx |
| LLM 适配 | 自研 `BaseLLMProvider` + 各家 SDK | 官方 SDK：openai、dashscope（通义）、zhipuai；DeepSeek/豆包走 OpenAI 兼容 |
| 反向代理 | Nginx | 终止 TLS、托管前端静态、把 `/api` 代理到后端 |
| 进程管理 | systemd | 单机部署最简方案 |

---

## 3. 系统架构

```
┌──────────────┐  HTTPS:8900  ┌──────────────┐  127.0.0.1:8901  ┌──────────────┐
│  Browser UI  │ ───────────▶ │    Nginx     │ ───────────────▶ │  FastAPI     │
│ React+shadcn │              │ TLS+静态+反代 │                  │  Python 3.11 │
└──────────────┘              └──────────────┘                  └──────┬───────┘
                                                                       │
                            ┌────────────────┬─────────────────┬───────┴─────┐
                            ▼                ▼                 ▼             ▼
                       SQLite DB      文件系统(uploads/    LLM Providers   docx 生成
                      (剧本/版本/      generated/)        (5 家适配)      python-docx
                       行/译行/文档)                       
```

数据流：

1. 用户上传文档 / 粘贴文本 → `POST /api/scripts`
2. 后端解析 → 入库 `scripts` + `script_lines`
3. 用户在前端选「目标语言 + 模型」→ `POST /api/scripts/:id/translate`
4. 后端创建 `translation_versions` 记录（status=running），`BackgroundTasks` 异步翻译
5. 翻译完成写入 `translation_lines`，状态置 `done`
6. 前端轮询 `GET /api/translations/:version_id` 直至完成，渲染预览
7. 下载 → `GET /api/translations/:version_id/download`

---

## 4. 数据库设计（SQLite DDL）

```sql
-- 剧本（一次上传/粘贴 → 一条）
CREATE TABLE scripts (
  id            TEXT PRIMARY KEY,           -- uuid
  title         TEXT NOT NULL,
  source_lang   TEXT,                       -- auto / zh / en / th / ar（识别后回填）
  source_type   TEXT NOT NULL,              -- upload_docx / upload_doc / paste
  raw_text      TEXT NOT NULL,              -- 标准化后的全文
  raw_file_path TEXT,                       -- 原文件相对路径（粘贴时空）
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 识别出的行（包含对话行 + 场景描述行）
CREATE TABLE script_lines (
  id             TEXT PRIMARY KEY,
  script_id      TEXT NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
  line_no        INTEGER NOT NULL,          -- 行序号
  raw_line       TEXT NOT NULL,             -- 整行原文
  speaker        TEXT,                      -- "艾米丽"，描述行为 NULL
  parenthetical  TEXT,                      -- "局促，低声"，无则 NULL
  dialogue       TEXT,                      -- 仅对话部分（待译）
  is_dialogue    BOOLEAN NOT NULL           -- false 表示场景描述行
);
CREATE INDEX idx_lines_script ON script_lines(script_id, line_no);

-- 翻译版本：一个剧本 × 一个目标语言 × 一个模型 → 一条版本
CREATE TABLE translation_versions (
  id              TEXT PRIMARY KEY,
  script_id       TEXT NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
  target_lang     TEXT NOT NULL,            -- zh / en / th / ar
  model_provider  TEXT NOT NULL,            -- openai / deepseek / doubao / tongyi / zhipu
  model_name      TEXT NOT NULL,
  status          TEXT NOT NULL,            -- pending / running / done / failed
  prompt_version  TEXT NOT NULL,            -- 提示词模板版本号
  total_tokens    INTEGER,
  cost            NUMERIC,                  -- 估算（人民币元）
  duration_ms     INTEGER,
  error_message   TEXT,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_versions_script ON translation_versions(script_id, created_at);

-- 行级译文（与版本 + 行 多对一）
CREATE TABLE translation_lines (
  id                 TEXT PRIMARY KEY,
  version_id         TEXT NOT NULL REFERENCES translation_versions(id) ON DELETE CASCADE,
  line_id            TEXT NOT NULL REFERENCES script_lines(id) ON DELETE CASCADE,
  translated_dialogue TEXT,                  -- 仅对话部分译文
  rendered_line       TEXT NOT NULL          -- "原文(译文)" 完整渲染行
);
CREATE INDEX idx_translines_version ON translation_lines(version_id);

-- 已生成的下载文档
CREATE TABLE generated_docs (
  id          TEXT PRIMARY KEY,
  version_id  TEXT NOT NULL REFERENCES translation_versions(id) ON DELETE CASCADE,
  file_path   TEXT NOT NULL,                -- storage/generated/<version_id>/xxx.docx
  filename    TEXT NOT NULL,
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 5. 后端模块结构

```
backend/
  app/
    main.py                 # FastAPI 入口、CORS、路由注册、生命周期
    config.py               # pydantic-settings；从 .env 加载
    db.py                   # SQLAlchemy async engine + session 依赖
    models/                 # ORM 模型（5 张表）
    schemas/                # Pydantic 请求/响应模型
    routers/
      scripts.py            # 上传/粘贴、读取剧本
      translations.py       # 触发翻译、读版本、列版本
      downloads.py          # 生成 + 下载 docx
      models.py             # 列出可用 LLM 模型
      health.py             # 健康检查
    services/
      script_parser.py      # docx/doc/纯文本 → 标准化文本
      dialogue_extractor.py # 行识别（正则 + LLM 兜底）
      lang_detect.py        # 简单字符段判定为主，langdetect 兜底
      translator.py         # 编排：分批 → LLM → 合并 → 渲染 → 写库
      doc_generator.py      # python-docx 生成下载文件
      cost_estimator.py     # token → 人民币
    llm/
      base.py               # BaseLLMProvider（abstract）
      registry.py           # 工厂 + 模型清单
      openai_provider.py
      deepseek_provider.py  # OpenAI 兼容
      doubao_provider.py    # OpenAI 兼容（火山方舟）
      tongyi_provider.py    # dashscope
      zhipu_provider.py     # zhipuai
    prompts/
      style_guidelines.md   # 短剧口语化 + 命名一致性 + 不译内容
      translate_xx_to_zh.md # 任意 → 中文
      translate_zh_to_xx.md # 中文 → 任意
  storage/
    uploads/<script_id>/<original-filename>
    generated/<version_id>/<title>-<lang>-<provider>.docx
  data/
    app.db                  # SQLite
  .env.example              # 各家 API Key 占位
  pyproject.toml
  README.md
```

---

## 6. 对话识别策略

### 6.1 输入标准化
- `.docx`：python-docx 按段落读出文本，剔除空段
- `.doc`：先 `libreoffice --headless --convert-to docx` 转换，再走 `.docx` 流程
- 纯文本：按行切分，剔除多余空行

### 6.2 行识别规则（基于 `script-example.md`）
1. **场景标题行**：以 `[x]-y 场景：` 开头 → 不译，原样保留
2. **场景描述行**：以 `△` 开头 → 不译，原样保留
3. **集数标题**：以 `【第x集】` 形式 → 不译
4. **对话行**：匹配以下任一模式
   - `<人名>（<情绪/动作>）：<对话>`
   - `<人名>：<对话>`
   - 兼容半角 `()`、`:` 与全角 `（）`、`：`
5. **空行**：保留

正则草案（仅供参考，实现时按 `script-example.md` 跑准确率 ≥ 95%）：

```python
DIALOGUE_RE = re.compile(
    r'^(?P<speaker>[^\s（(：:]+?)'
    r'(?:[（(](?P<paren>[^）)]*)[）)])?'
    r'[：:](?P<dialogue>.+)$'
)
SCENE_PREFIX = ('△', '[', '【')
```

### 6.3 LLM 兜底
- 触发条件：正则未命中但行内含 `：` 或 `:`（疑似对话）
- 行为：调用一次 LLM 做结构化抽取，返回 `{is_dialogue, speaker, parenthetical, dialogue}`
- 单次调用最多覆盖一段 ≤ 50 行，控制成本

---

## 7. 翻译策略与 Prompt 设计

### 7.1 批量与稳定输出
- 每批 20–40 行对话一并送入 LLM
- 用「占位 ID」格式约束输出，规避 markdown / 引号干扰：

  ```
  L001 = อีธาน พอแค่นี้ดีกว่าไหม ที่นี่คนเยอะเกินไป
  L002 = กลับไปในรถ
  ...
  ```

  模型只需返回：

  ```
  L001 = 伊森，要不我们先这样吧，这里人实在太多了
  L002 = 我们回车里去
  ```

- 解析按 `^L\d+ = ` 切分；若缺行则该行回退单条重试。

### 7.2 系统提示（核心要点）

```
你是短剧本地化译者。规则：
1. 译文必须是【目标语言的口语】，避免书面、学术、文绉绉表达。
2. 短剧节奏快、台词简短，请保留口头化、情绪化用词。
3. 保留人物名一致性，遵循对照表（如果给定）：
   - Ethan / อีธาน → 伊森
   - Emily / เอมิลี่ → 艾米丽
   - Stella / สเตลล่า → 斯特拉
   - Lucy / ลูซี่ → 露西
4. 仅翻译给定行的对话内容；不要翻译括号里的情绪/动作描述。
5. 严格按 "Lxxx = 译文" 单行返回，不要加引号、不要解释。
```

### 7.3 上下文注入
- 每批请求前置 200~400 字的「场景上下文」（取本批前后的描述行），帮助模型把握情绪
- 命名对照表来自第一遍快速预扫（高频外文人名 ↔ 中文，可手动覆盖）

### 7.4 失败处理
- LLM 输出不可解析 / 缺行 → 该批回退为单行翻译
- API 限流 / 超时 → 指数退避重试 3 次后标记 `failed`，记录到 `error_message`

---

## 8. API 设计

| Method | Path | Body / Query | Response |
| --- | --- | --- | --- |
| GET | `/api/health` | - | `{status: "ok"}` |
| GET | `/api/models` | - | `[{provider, name, target_langs, default}]` |
| POST | `/api/scripts` | multipart 上传 OR `{title, raw_text}` | `{script_id, title, line_count, source_lang}` |
| GET | `/api/scripts` | `?limit&offset` | 剧本分页列表 |
| GET | `/api/scripts/:id` | - | `{...meta, lines: [...]}` |
| POST | `/api/scripts/:id/translate` | `{target_lang, provider, model}` | `{version_id, status: "running"}` |
| GET | `/api/translations/:version_id` | - | `{...meta, rendered_lines: [...]}` |
| GET | `/api/scripts/:id/versions` | - | 同剧本所有版本（用于历史对比） |
| GET | `/api/translations/:version_id/download` | - | 流式 `.docx` |

异步：翻译用 FastAPI `BackgroundTasks`（MVP 足够）；前端轮询 `/api/translations/:version_id`，2s 一次直至 `status` 变更。

---

## 9. 前端模块

```
frontend/
  src/
    pages/
      UploadPage.tsx         # 主页：拖拽/粘贴 + 标题 + 目标语言 + 模型 + 翻译按钮
      ScriptViewer.tsx       # 单剧本预览：原文(译文) 行内显示 + 版本切换
      HistoryPage.tsx        # 全部剧本 + 各版本矩阵（用 Tabs 横向对比）
    components/
      Dropzone.tsx           # 拖拽上传，调用 react-dropzone
      ModelSelector.tsx      # 厂商 → 模型 二级选择
      TranslationStatus.tsx  # 轮询 + 进度条 + 失败重试
      ScriptLineRow.tsx      # 单行渲染：场景行 / 对话行（含原文+译文样式）
      DownloadButton.tsx
    api/
      client.ts              # axios 实例（baseURL = /api）
      types.ts               # 与后端 schema 对齐
    App.tsx
    main.tsx
  index.html
  vite.config.ts             # dev 时 proxy /api → http://127.0.0.1:8901
  tailwind.config.ts
  components.json            # shadcn/ui
  package.json
```

UI 关键点：
- `ScriptViewer`：场景描述行用浅灰色；对话行渲染 `<原文><span class="text-zinc-500 italic">(译文)</span>`
- `HistoryPage`：每个剧本下用 `Tabs` 横向罗列已生成的 (语言, 模型) 版本
- 上传时让用户填一个「标题」，方便历史区分
- 全程响应式，桌面优先

---

## 10. 部署方案

### 10.1 服务器要求
- Ubuntu 22.04+
- Python 3.11、Node.js 20、Nginx、libreoffice (`libreoffice-common`)、systemd
- 出网可达各 LLM API 域名

### 10.2 端口与路径
- Nginx 监听 `0.0.0.0:8900`（TLS）
- FastAPI 监听 `127.0.0.1:8901`
- 前端构建产物在 `frontend/dist`

### 10.3 Nginx 站点要点（示意）
```
server {
  listen 8900 ssl;
  ssl_certificate     /etc/ssl/script-translate.crt;
  ssl_certificate_key /etc/ssl/script-translate.key;

  client_max_body_size 20m;        # 允许 docx 上传

  root /opt/script-translate/frontend/dist;
  index index.html;

  location /api/ {
    proxy_pass http://127.0.0.1:8901/api/;
    proxy_set_header Host $host;
    proxy_read_timeout 600s;       # 翻译可能耗时
  }

  location / {
    try_files $uri $uri/ /index.html;
  }
}
```

### 10.4 systemd 单元（示意）
```
[Unit]
Description=Script Translate API
After=network.target

[Service]
WorkingDirectory=/opt/script-translate/backend
EnvironmentFile=/opt/script-translate/backend/.env
ExecStart=/opt/script-translate/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8901
Restart=always

[Install]
WantedBy=multi-user.target
```

### 10.5 配置与密钥
- 各家 API Key 写入 `backend/.env`，**仅服务端读**
- `.env.example` 入库；`.env` 不入库
- 日志脱敏（不打印 prompt 全文，只记 token 数与 hash）

### 10.6 备份
- `data/app.db` + `storage/` 每日打包到 `/var/backups/script-translate/`

---

## 11. 分阶段开发里程碑

| 阶段 | 交付内容 | 验收标准 | 预估 |
| --- | --- | --- | --- |
| M1 骨架 | 前后端工程脚手架；Nginx + systemd 联通；`/api/health` 通 | 浏览器访问 `https://45.78.235.74:8900` 看到首页，调 `/api/health` 返回 ok | 0.5d |
| M2 上传&解析 | 拖拽/粘贴 → 入库；script_lines 正则识别 | 用 `script-example.md` 上传后，对话行识别准确率 ≥ 95% | 1d |
| M3 单模型翻译 | 接入 DeepSeek；批量翻译；ScriptViewer 渲染 | 选「翻译为中文」+ DeepSeek，得到示例需求中给出的 `原文(译文)` 形态 | 1.5d |
| M4 多模型 | 接 OpenAI / 豆包 / 通义 / 智谱；模型选择 UI；多版本入库 | 同一剧本可生成 5 家版本，历史页可对比 | 1d |
| M5 docx 下载 | python-docx 渲染下载 | 下载 docx，Word/WPS 打开排版正常 | 0.5d |
| M6 历史&对比 | HistoryPage + 版本 Tabs | 同剧本下可在 (语言, 模型) 矩阵中切换查看 | 1d |
| M7 LLM 兜底识别 | 正则未命中行走 LLM 抽取 | 故意构造异形行（多冒号/无括号），仍能正确归类 | 0.5d |
| M8 部署上线 | Nginx + TLS + systemd | 公网可访问、刷新不丢路由、长连接不超时 | 0.5d |

合计约 6.5 个工作日（不含调试、UI 打磨）。

---

## 12. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| `.doc` 旧格式解析失败 | 用户上传报错 | 失败时返回明确错误，提示用户另存为 `.docx`；可在前端给出「转换失败的常见原因」说明 |
| LLM 输出格式漂移 | 解析失败、丢行 | `Lxxx = 译文` 单行格式 + 严格校验；缺行回退逐条 |
| 泰语/阿语 token 暴涨超上限 | 批量请求被截断 | 动态批大小，按字符长度估算 token；超阈值自动拆批 |
| 原 docx 复杂样式丢失 | 用户下载结果不还原 | MVP 明确不保留样式，README 中说明；后续 M+ 阶段再做局部插入 |
| 各家 API Key 泄漏 | 账号被滥用 | Key 只在服务端 `.env`；日志脱敏；限制 CORS 来源 |
| 翻译时间过长 | 浏览器/Nginx 超时 | 后端用 BackgroundTasks，前端轮询；Nginx `proxy_read_timeout` ≥ 600s |
| 单机 SQLite 并发 | 高并发翻译写入冲突 | MVP 单用户场景充分；写操作走单一 session，必要时排队 |

---

## 13. 验证方法

### 13.1 端到端冒烟（必须）
基于 `script-example.md`：

1. 把 `script-example.md` 文本粘贴进上传页，标题填「火花瞬间燃点」
2. 选「目标语言：中文」+「DeepSeek」→ 翻译
3. 预览页应得到示例需求中给出的形态（如第 7 行）：
   ```
   艾米丽（局促，低声）：อีธาน พอแค่นี้ดีกว่าไหม ที่นี่คนเยอะเกินไป(伊森，要不我们先这样吧，这里人实在太多了)
   ```
4. 切换「豆包 / 通义 / 智谱 / OpenAI」分别翻译，历史页能在版本 Tabs 中横向对比
5. 下载 `.docx`，Word 打开内容、行序、`(译文)` 嵌入位置正确
6. 反向：找一份纯中文剧本，翻为「英文 / 泰语 / 阿语」，同样三步走

### 13.2 单元测试
- `dialogue_extractor`：对 `script-example.md` 全文识别准确率 ≥ 95%（人工标注比对）
- 各 `Provider.translate_batch` 的输入输出契约（真实 Provider 联调或网络层打桩）
- `doc_generator`：给定固定输入，生成的 docx 字节级稳定

### 13.3 部署后手测
- 浏览器打开 `https://45.78.235.74:8900` → 主页正常
- 任意子路由刷新 → 不 404（前端路由 fallback 配置正确）
- 翻译耗时 > 60s → 不被中断（Nginx & systemd 配置生效）

---

## 14. 后续可演进（不在 MVP）

- 用户登录 / 项目空间 / 团队协作
- **术语表 / 人名对照表（Glossary）**：可按剧本维护命名映射，注入提示词
- 译文人工微调 + 反馈回流（用于评测最佳模型）
- 自动评测：BLEU / COMET 或 LLM-as-Judge 给各模型打分
- 保留原 `.docx` 样式的「局部插入」翻译模式（不重排版，仅追加 `(译文)`）
- 流式翻译（SSE / WebSocket）让用户实时看到译文出现

---

## 附录 A：参考资料
- 需求原文：`/root/project/script-translate/需求`
- 真实剧本样例：`/root/project/script-translate/script-example.md`
- 编码守则：`/root/project/script-translate/CLAUDE.md`
