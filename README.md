# Script Translate

短剧剧本人物对话翻译工具。支持上传 `.docx` / `.doc` 或粘贴纯文本，自动识别对话行并用多模型翻译，在页面与导出文档中以 `原文(译文)` 呈现。

## 目录结构

- `backend/`: FastAPI、SQLite、文档解析、翻译编排、导出 docx
- `frontend/`: React + Vite 页面
- `deploy/`: Nginx 与 systemd 模板

## 本地启动

### 后端

```bash
cd backend
python3 -m venv ../.venv
. ../.venv/bin/activate
pip install -e .[dev]
cp .env.example .env
# fill in DOUBAO_API_KEY and DOUBAO_MODELS before startup
uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8901
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

开发模式下，Vite 会把 `/api` 代理到 `http://127.0.0.1:8901`。

## 测试与构建

```bash
. .venv/bin/activate
cd backend && pytest -q
cd ../frontend && npm run build
```

## 当前实现范围

- 文本 / docx 上传与入库
- `.doc` 转换入口（依赖服务器安装 LibreOffice）
- 基于规则的剧本行识别
- 多 Provider 注册表，默认使用豆包
- 翻译版本管理、历史查看、docx 下载
- Nginx / systemd 部署模板

## Provider 配置

- 当前默认 Provider 是 `doubao`
- 如果 `DEFAULT_PROVIDER=doubao`，启动前必须配置 `DOUBAO_API_KEY`
- `DOUBAO_MODELS` 使用逗号分隔，按顺序声明当前 key 可切换的豆包模型
- `DOUBAO_MODELS` 的第一个模型是后端默认模型
- `/api/models` 只会返回已配置可用的 Provider
- 前端会优先记住上次选择的豆包模型；如果该模型已失效，则回退到 `DOUBAO_MODELS` 第一个

## 翻译联调测试

- `backend/tests/test_api.py` 中的翻译闭环测试会调用真实豆包接口
- 运行该测试前需要在环境中设置 `DOUBAO_API_KEY`，并建议同时设置 `DOUBAO_MODELS`
