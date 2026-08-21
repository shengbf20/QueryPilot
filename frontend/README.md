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

未先 `serve` 时点「发送」会提示无法连接；可用「mock 成功 / mock 拦截」离线看布局。

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

1. 「发送」→ 展示耗时、剪枝、SQL、结果表  
2. 同题再发一次 → 观察 `cache_hit` 与更短 `total_ms`  
3. 「导出 CSV」→ `POST /api/export`  
4. mock 按钮不请求后端  

**对话**

1. 底部输入，Enter 发送（Shift+Enter 换行）；走强 Agent（`mode=agent` + `session_id`）  
2. 助手侧：思考过程默认折叠，正文为自然语言 / SQL / 结果表（有表时正文不再重复表内数字）  
3. 耗时、缓存、剪枝默认隐藏，点消息下「详情」展开；「新对话」清空线程（换题会重新剪枝，勿沿用旧会话的表白名单）  
4. 无 mock 按钮  

`vite.config.ts` 代理：`/api`、`/health` → `http://127.0.0.1:8000`。

## 构建

```powershell
npm run build
# 产物 frontend/dist/；生产环境需自行将 /api 反代到 FastAPI
```
