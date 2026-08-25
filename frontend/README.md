# QueryPilot Chat UI（阶段五）

Vite + React + TypeScript。

| 步骤 | 状态 |
|------|------|
| UI-1 mock 布局 | ✅ |
| UI-2 `/api/ask` + `/api/export` | ✅ |
| UI-3 收口说明 | ✅ |

问数页逐步操作见 [`logs/05-阶段五-原型系统交付与验证.md`](../logs/05-阶段五-原型系统交付与验证.md) **附录 B**；对话模式见下文。

## 启动顺序（必须）

1. **先**起 API：`querypilot serve --host 127.0.0.1 --port 8000`  
2. **再**起 UI（本目录）：`npm install` → `npm run dev`  
3. 浏览器打开 `http://127.0.0.1:5173`

未先 `serve` 时点「发送」会提示无法连接。

```powershell
# 终端 1
querypilot serve --host 127.0.0.1 --port 8000

# 终端 2
cd frontend
npm install
npm run dev
```

## 页面操作摘要

顶栏 **问数 / 对话** 切换。两种模式都走 Vite 代理 `POST /api/ask`。

**问数（默认，实验室布局）**

1. 「发送」→ 先结果表、再 SQL；过长可展开  
2. 「过程与耗时」折叠查看剪枝与分阶段耗时  
3. 「导出 CSV」→ `POST /api/export`  

**对话**

1. 底部输入，Enter 发送（Shift+Enter 换行）；走强 Agent（`mode=agent` + `session_id`）  
2. 助手侧：思考过程默认折叠，正文为自然语言 / SQL / 结果表（有表时正文不再重复表内数字）  
3. 耗时默认藏在「详情」；顶栏「新对话」在模式开关左侧，清空线程  

`vite.config.ts` 代理：`/api`、`/health` → `http://127.0.0.1:8000`。

## 构建

```powershell
npm run build
# 产物 frontend/dist/；生产环境需自行将 /api 反代到 FastAPI
```
