# QueryPilot Chat UI（阶段五）

Vite + React + TypeScript。

| 步骤 | 状态 |
|------|------|
| UI-1 mock 布局 | ✅ |
| UI-2 `/api/ask` + `/api/export` | ✅ |
| UI-3 收口说明 | ✅ |

详细操作见仓库 [`logs/05-阶段五-原型系统交付与验证.md`](../logs/05-阶段五-原型系统交付与验证.md) **附录 B**。

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

1. 「发送」→ Vite 代理 `POST /api/ask`  
2. 同题再发一次 → 观察 `cache_hit` 与更短 `total_ms`  
3. 「导出 CSV」→ `POST /api/export`  
4. mock 按钮不请求后端  

`vite.config.ts` 代理：`/api`、`/health` → `http://127.0.0.1:8000`。

## 构建

```powershell
npm run build
# 产物 frontend/dist/；生产环境需自行将 /api 反代到 FastAPI
```
