#!/usr/bin/env python3
"""Project Mirror — Vercel Serverless (Flask)
Handles /api/questions, /api/score, /api/analyze
"""
import json, os, random, re, sys, time, traceback
from pathlib import Path
from http.client import HTTPSConnection
from flask import Flask, request, jsonify

app = Flask(__name__)

# ── Load data ──
HERE = Path(__file__).parent.parent
with open(HERE / "questions.json", encoding="utf-8") as f:
    questions_data = json.load(f)

# ── Config from env ──
AI_API_KEY = os.environ.get("AI_API_KEY", os.environ.get("DEEPSEEK_API_KEY", "")).strip()
AI_URL = os.environ.get("AI_URL", "https://api.deepseek.com/v1/chat/completions")
AI_MODEL = os.environ.get("AI_MODEL", "deepseek-chat")
AI_AUTH_HEADER = os.environ.get("AI_AUTH_HEADER", "Authorization")

# ── Constants ──
DIM_ORDER = ["EI", "SN", "TF", "JP", "AT"]
FIRST_POLES = {"EI": "E", "SN": "S", "TF": "T", "JP": "J", "AT": "A"}

_NONSENSE_RE = re.compile(
    r'^(.)\1{2,}$|^[a-zA-Z]{1,3}$|^(.){1,2}$|'
    r'^(嗯|哦|啊|哈|是|对|好|行|不|无|有|没|了|的){1,4}$|'
    r'^(asdf|qwer|test|测试|111|222|aaa|bbb)$', re.IGNORECASE)


# ═══════════════════════════════════════════
#  Scoring
# ═══════════════════════════════════════════

def score_traditional(answers):
    net_scores = {}
    for dim in DIM_ORDER:
        dim_qs = [q for q in questions_data["traditional"] if q["dimension"] == dim]
        net = 0
        first = FIRST_POLES[dim]
        second = {"EI":"I","SN":"N","TF":"F","JP":"P","AT":"T"}[dim]
        for q in dim_qs:
            match = [a for a in answers if a["id"] == q["id"]]
            if not match: continue
            val = match[0]["value"]
            net += val if q["direction"] == first else -val
        possible_max = len(dim_qs) * 2
        dominant = first if net >= 0 else second
        other = second if net >= 0 else first
        intensity = min(abs(net) / possible_max * 100, 100) if possible_max else 50
        dom_pct = round(50 + abs(net) / possible_max * 50) if possible_max else 50
        other_pct = 100 - dom_pct
        net_scores[dim] = {
            "net": net, "dominant": dominant, "other": other,
            "intensity": round(intensity),
            "strength": "neutral" if intensity < 20 else ("slight" if intensity < 60 else "clear"),
            "dom_pct": dom_pct, "other_pct": other_pct,
        }
    type_str = "".join(net_scores[d]["dominant"] for d in DIM_ORDER[:4])
    identity = net_scores["AT"]["dominant"]
    return {"type": type_str, "identity": identity, "details": net_scores}


# ═══════════════════════════════════════════
#  Open-ended selection
# ═══════════════════════════════════════════

def select_open_ended(details):
    pool = list(questions_data.get("open_ended_pool", []))
    if not pool: return []
    random.shuffle(pool)
    selected, used_ids = [], set()
    def pick_one(tag, focus_dim=None):
        for q in pool:
            if tag in q.get("tags", []) and q["id"] not in used_ids:
                item = dict(q)
                if focus_dim: item["focus_dimension"] = focus_dim
                selected.append(item); used_ids.add(q["id"])
                return True
        return False
    uncertainty, clear_dims = [], []
    for dim in DIM_ORDER:
        d = details.get(dim, {})
        dom_pct = int(d.get("dom_pct", 50))
        strength = d.get("strength", "neutral")
        dominant = d.get("dominant", "")
        if strength != "clear" or dom_pct < 68:
            uncertainty.append((abs(dom_pct - 50), dim))
        elif dominant:
            clear_dims.append(f"shadow_{dominant}")
    uncertainty.sort(key=lambda x: x[0])
    for _, dim in uncertainty:
        if len(selected) >= 5: break
        pick_one(f"probe_{dim}", dim)
    random.shuffle(clear_dims)
    for tag in clear_dims:
        if len(selected) >= 5: break
        pick_one(tag)
    if len(selected) < 5:
        for q in pool:
            if "mixed" in q.get("tags", []) and q["id"] not in used_ids:
                selected.append(dict(q)); used_ids.add(q["id"])
                if len(selected) >= 5: break
    if len(selected) < 5:
        for q in pool:
            if q["id"] not in used_ids:
                selected.append(dict(q)); used_ids.add(q["id"])
                if len(selected) >= 5: break
    return [
        {"display_id": f"oe_{i+1}", "id": q["id"], "text": q["text"],
         "hint": q.get("hint", ""), "focus_dimension": q.get("focus_dimension", "")}
        for i, q in enumerate(selected[:5])
    ]


# ═══════════════════════════════════════════
#  AI call
# ═══════════════════════════════════════════

def call_ai(system_prompt, user_prompt, retries=2, temperature=0.3, max_tokens=4096):
    if not AI_API_KEY:
        raise ValueError("AI API Key 未设置。请在 Vercel 环境变量中配置 AI_API_KEY。")
    import urllib.request
    messages = []
    if system_prompt and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    payload = json.dumps({
        "model": AI_MODEL, "messages": messages,
        "temperature": temperature, "max_tokens": max_tokens,
    }).encode("utf-8")
    req = urllib.request.Request(AI_URL, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header(AI_AUTH_HEADER, f"Bearer {AI_API_KEY}")
    last_error = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, dict):
                if data.get("choices"):
                    return data["choices"][0]["message"]["content"]
                if data.get("result"):
                    return data["result"]
            return json.dumps(data, ensure_ascii=False)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"AI API 错误: {e.read().decode('utf-8', errors='replace')}")
        except urllib.error.URLError as e:
            last_error = e
            if attempt < retries: time.sleep(1)
    raise RuntimeError(f"网络错误: {last_error}")


def is_nonsense(text):
    if not text or len(text.strip()) < 3: return True
    t = text.strip()
    if _NONSENSE_RE.search(t): return True
    if len(t) > 3 and max(t.count(c) for c in set(t)) / len(t) > 0.6: return True
    if all(not c.isalnum() for c in t): return True
    return False


# ═══════════════════════════════════════════
#  AI analysis
# ═══════════════════════════════════════════

def _fallback_analysis(traditional_type, identity, details, open_answers):
    full_type = f"{traditional_type}-{identity}"
    profile = questions_data.get("type_profiles", {}).get(traditional_type, {})
    dim_names = {"EI":"精力来源","SN":"认知方式","TF":"决策方式","JP":"生活态度","AT":"身份认同"}
    dim_analysis = {}
    for dim in DIM_ORDER:
        d = details.get(dim, {})
        dom = d.get("dominant","?")
        pct = d.get("dom_pct",50)
        label = "明显偏向" if pct>70 else ("轻微偏向" if pct>55 else "接近居中")
        dim_analysis[dim] = {
            "倾向": f"{dom} ({pct}%)", "confidence": min(pct+10,95),
            "evidence": f"传统量表数据显示你在该维度偏向 {dom}（{pct}%），属于「{label}」。",
            "分析": f"基于量表统计，你在{dim_names.get(dim,dim)}维度上表现出{dom}倾向。" +
                    ("这一倾向较为明显。" if pct>60 else "但并非极端，在不同情境下可能有所变化。")
        }
    return {
        "insight": f"基于传统量表数据，你的类型为 {full_type}。由于 AI 深度分析服务暂不可用，以下分析基于统计数据生成。",
        "ai_confidence": 60, "answer_quality_score": 50,
        "summary": "传统量表结果已生成，但 AI 深度分析未完成。",
        "dimension_analysis": dim_analysis,
        "differences": ["AI 深度分析暂不可用，无法对比差异。"],
        "strengths": (profile.get("strengths") or [])[:4] or ["暂无数据"],
        "growth_areas": (profile.get("weaknesses") or [])[:3] or ["暂无数据"],
        "career_hints": (profile.get("careers") or [])[:6] or [],
    }


def _analyze_with_deepseek(traditional_type, identity, details, open_answers):
    dim_names = {"EI":"精力来源","SN":"认知方式","TF":"决策方式","JP":"生活态度","AT":"身份认同"}
    dim_desc = []
    for dim in DIM_ORDER:
        d = details.get(dim,{})
        dim_desc.append(f"- {dim_names.get(dim,dim)} ({dim}): {d.get('dominant','?')} {d.get('dom_pct',50)}% ({d.get('strength','')})")
    full_type = f"{traditional_type}-{identity}"
    answers_text = "\n".join(
        f"Q{oa.get('display_id',i+1)}: {oa.get('text','')}\n回答: {oa.get('answer','')}"
        for i, oa in enumerate(open_answers) if oa.get("answer","").strip()
    )
    call1_prompt = f"""你是MBTI人格分析专家。分析一位{full_type}型人格的开放题回答，输出JSON。

传统量表结果：{full_type}
维度得分：
{chr(10).join(dim_desc)}

回答内容：
{answers_text if answers_text else "（未填写）"}

要求：
- 通篇用「你」称呼对方，不要用「用户」
- 引用原话时直接加引号，不要标注Q1/Q2等编号
- 核心任务是验证为什么对方确实是{full_type}型
- 从认知功能角度分析（用F/T/N/S等方向字母，不要Fe/Ni这类缩写）
- 使用中文标点符号

请输出JSON，不要markdown代码块：
{{
  "analysis_summary": "400~600字深度分析",
  "dimension_analysis": {{
    "EI": {{"倾向":"E/I","confidence":0-100,"evidence":"引用原话","分析":"100~180字认知功能分析"}},
    "SN": {{"倾向":"S/N","confidence":0-100,"evidence":"引用原话","分析":"100~180字认知功能分析"}},
    "TF": {{"倾向":"T/F","confidence":0-100,"evidence":"引用原话","分析":"100~180字认知功能分析"}},
    "JP": {{"倾向":"J/P","confidence":0-100,"evidence":"引用原话","分析":"100~180字认知功能分析"}},
    "AT": {{"倾向":"A/T","confidence":0-100,"evidence":"引用原话","分析":"100~180字认知功能分析"}}
  }},
  "agreement": "high/medium/low",
  "differences": [],
  "strengths": [],
  "growth_areas": [],
  "career_hints": []
}}"""
    raw1 = call_ai("", call1_prompt, temperature=0.5, max_tokens=4096).strip()
    if raw1.startswith("```"):
        raw1 = raw1.split("\n",1)[-1].rsplit("```",1)[0]
    parsed = {}
    try:
        parsed = json.loads(raw1)
    except json.JSONDecodeError:
        brace_start = raw1.find("{")
        brace_end = raw1.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            try:
                parsed = json.loads(raw1[brace_start:brace_end+1])
            except json.JSONDecodeError:
                parsed = {"raw_output": raw1}
    # Build response from parsed data
    da = parsed.get("dimension_analysis", {})
    for d in DIM_ORDER:
        if d not in da:
            nd = details.get(d,{})
            da[d] = {"倾向": nd.get("dominant",""), "confidence": 50, "evidence": "", "分析": ""}
    differences = parsed.get("differences", []) or []
    return {
        "insight": parsed.get("analysis_summary", "分析完成。"),
        "ai_confidence": 85,
        "answer_quality_score": min(len(open_answers) * 18 + 10, 90),
        "summary": parsed.get("analysis_summary", "")[:200],
        "dimension_analysis": da,
        "differences": differences,
        "strengths": parsed.get("strengths", [])[:4],
        "growth_areas": parsed.get("growth_areas", [])[:3],
        "career_hints": parsed.get("career_hints", [])[:6],
    }


def analyze_with_ai(traditional_type, identity, details, open_answers):
    filtered = [oa for oa in open_answers if not is_nonsense(oa.get("answer",""))]
    meaningful = len(filtered)
    if meaningful == 0:
        return _fallback_analysis(traditional_type, identity, details, open_answers)
    try:
        return _analyze_with_deepseek(traditional_type, identity, details, filtered)
    except Exception as e:
        traceback.print_exc()
        return _fallback_analysis(traditional_type, identity, details, open_answers)


# ═══════════════════════════════════════════
#  Routes
# ═══════════════════════════════════════════

@app.route("/")
def handle_root():
    """Serve the frontend index.html for the root path."""
    # Try multiple possible paths (Vercel serverless env varies)
    candidates = [
        HERE / "public" / "index.html",
        Path(__file__).parent / "public" / "index.html",
        Path.cwd() / "public" / "index.html",
        HERE / "index.html",
    ]
    for p in candidates:
        try:
            if p.exists() and p.is_file():
                return app.response_class(
                    response=p.read_text(encoding="utf-8"),
                    status=200, mimetype="text/html",
                )
        except OSError:
            pass
    debug = (
        f"<h1>Frontend not found</h1>"
        f"<p><b>__file__:</b> {__file__}</p>"
        f"<p><b>CWD:</b> {Path.cwd()}</p>"
        f"<p><b>HERE:</b> {HERE}</p>"
        f"<p><b>Searched:</b></p><ul>"
    )
    for p in candidates:
        debug += f"<li>{p} — {'✓ EXISTS' if p.exists() else '✗ NOT FOUND'}</li>"
    debug += "</ul>"
    try:
        debug += "<p><b>CWD contents:</b></p><ul>"
        for f in sorted(Path.cwd().iterdir()):
            debug += f"<li>{f.name}{'/' if f.is_dir() else ''}</li>"
        debug += "</ul>"
    except OSError:
        pass
    debug += f"<p><b>HERE contents:</b></p><ul>"
    try:
        for f in sorted(HERE.iterdir()):
            debug += f"<li>{f.name}{'/' if f.is_dir() else ''}</li>"
        debug += "</ul>"
    except OSError:
        debug += f"<li>Cannot list {HERE}</li></ul>"
    return debug, 404


@app.route("/api/questions")
def handle_questions():
    return jsonify(questions_data)


@app.route("/api/score", methods=["POST"])
def handle_score():
    data = request.get_json(force=True)
    answers = data.get("answers", [])
    result = score_traditional(answers)
    result["selected_questions"] = select_open_ended(result["details"])
    return app.response_class(
        response=json.dumps(result, ensure_ascii=False),
        status=200, mimetype="application/json",
    )


@app.route("/api/analyze", methods=["POST"])
def handle_analyze():
    data = request.get_json(force=True)
    result = analyze_with_ai(
        data.get("type", ""),
        data.get("identity", ""),
        data.get("details", {}),
        data.get("open_answers", []),
    )
    return app.response_class(
        response=json.dumps(result, ensure_ascii=False),
        status=200, mimetype="application/json",
    )


# Vercel WSGI entry point
app = app
