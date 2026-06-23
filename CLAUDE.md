# CLAUDE.md — mbti-public (Vercel 部署版)

## 概述

Project Mirror（MBTI 人格测试）的 Vercel 部署版本。与 `D:\Code\1123\mbti\` 同步，但为 Vercel Serverless 架构做了适配。

## 项目结构（Vercel）

```
mbti-public/
├── api/
│   ├── index.py           # Flask 应用（服务端函数入口）
│   └── templates/
│       └── index.html     # ⚠️ 前端文件在这里，不在 public/！
├── public/
│   └── index.html         # ❌ Vercel 不把此目录加入函数环境
├── questions.json         # 题目数据
├── vercel.json            # 路由规则
├── requirements.txt       # flask>=3.0
└── CLAUDE.md
```

## Vercel 部署注意事项

### ⚠️ 关键：public/ 目录陷阱

**`public/` 目录不会被包含进 Vercel Serverless 函数文件系统！**

Vercel 将 `public/` 视为纯静态资源目录，由 CDN 独立托管，不放入 `/var/task/` 环境。所以 `api/index.py` 读不到 `public/` 里的文件。

**解决方法**：前端文件放在 `api/templates/index.html`，由 Flask 根路由直接读取并返回：

```python
TEMPLATES = Path(__file__).parent / "templates"

@app.route("/")
def handle_root():
    index_html = TEMPLATES / "index.html"
    if index_html.exists():
        return index_html.read_text(encoding="utf-8"), 200, {"Content-Type": "text/html; charset=utf-8"}
    return "FE not found", 404
```

### 数据文件加载

`questions.json` 放在项目根目录，Vercel 会把它放进 `/var/task/questions.json`，可以正常读取。

```python
HERE = Path(__file__).parent.parent  # → /var/task/
DATA_PATH = HERE / "questions.json"
```

### 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `AI_API_KEY` | 是 | DeepSeek API Key |

在 Vercel 面板 → Project Settings → Environment Variables 中设置。

### Vercel Dashboard 设置

- **Framework Preset**: Flask（必须选 Flask，不能选 Other）
- **Root Directory**: `./`
- **Build Command**: 无
- **Install Command**: `pip install -r requirements.txt`（自动生成，保持不动）

### vercel.json

```json
{
  "rewrites": [
    { "source": "/api/(.*)", "destination": "/api/index" }
  ]
}
```

- `/api/*` 路由到 Flask 服务端函数
- `/`（根路径）由 Flask 根路由 `handle_root()` 处理，返回前端页面
- 前端 JS 调用 `/api/questions`、`/api/score`、`/api/analyze` 等相对路径

### 部署流程

```powershell
# 提交并推送到 GitHub
git add -A
git commit -m "描述改动"
git -c http.https://github.com.proxy=http://127.0.0.1:7897 push origin master

# Vercel 自动部署，等待 1-2 分钟
```

Vercel 有 Hobby 计划 **10 秒超时限制**，AI 分析（DeepSeek 调用）可能超时，会触发 fallback 分析。

## 本地开发

```powershell
# 本地测试 Flask 应用
python api/index.py

# 或通过 1123 的 stdlib 服务器
python ../1123/mbti/server.py --host 127.0.0.1 --port 8899
```

## 与 1123 同步

此仓库是 `D:\Code\1123\mbti\` 的独立部署副本。更新时手动复制关键文件：

```powershell
# 同步前端
Copy-Item D:\Code\1123\mbti\index.html D:\Code\mbti-public\api\templates\index.html

# 同步数据
Copy-Item D:\Code\1123\mbti\questions.json D:\Code\mbti-public\questions.json

# 同步后端逻辑（注意 Vercel 版是 Flask 封装）
# 手动比较 api/index.py 与 server.py 的逻辑差异
```

## 已安装工具

（此项目不需要额外构建工具，Flask 由 `requirements.txt` 管理）
