#!/usr/bin/env python3
"""
MBTI 人格测试 — 后端服务器
- Likert 5点量表 + 5维度（EI/SN/TF/JP/AT）
- 根据传统结果动态选择开放题
- 调用 DeepSeek 分析开放题
- 支持 config.json 持久化 API key

Usage:
    python server.py [--port 8899]
"""
import argparse
import json
import os
import random
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

HERE = Path(__file__).parent
QUESTIONS_FILE = HERE / "questions.json"
CONFIG_FILE = HERE / "config.json"
# Default AI settings (keeps backward compatibility with DeepSeek)
AI_BACKEND = "deepseek"
AI_URL = "https://api.deepseek.com/v1/chat/completions"
AI_MODEL = "deepseek-chat"
AI_API_KEY = ""
AI_AUTH_HEADER = "Authorization"  # header name to send the API key (default: Authorization)
AI_BACKENDS = {}

questions_data = {}


def load_config():
    global AI_BACKEND, AI_API_KEY, AI_URL, AI_MODEL, AI_AUTH_HEADER, AI_BACKENDS
    # 1. Environment variables (prefer explicit AI_ vars)
    AI_BACKEND = os.environ.get("AI_BACKEND", AI_BACKEND)
    AI_API_KEY = os.environ.get("AI_API_KEY", os.environ.get("DEEPSEEK_API_KEY", ""))
    AI_URL = os.environ.get("AI_URL", AI_URL)
    AI_MODEL = os.environ.get("AI_MODEL", AI_MODEL)
    AI_AUTH_HEADER = os.environ.get("AI_AUTH_HEADER", AI_AUTH_HEADER)
    if AI_API_KEY:
        return
    # 2. config.json
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            AI_BACKENDS = cfg.get("ai_backends", {}) or {}
            AI_BACKEND = cfg.get("ai_backend", AI_BACKEND)
            if AI_BACKENDS and AI_BACKEND in AI_BACKENDS:
                selected = AI_BACKENDS[AI_BACKEND]
                AI_API_KEY = (selected.get("ai_api_key") or selected.get("deepseek_api_key", "")).strip()
                AI_URL = selected.get("ai_url", AI_URL)
                AI_MODEL = selected.get("ai_model", AI_MODEL)
                AI_AUTH_HEADER = selected.get("ai_auth_header", AI_AUTH_HEADER)
            else:
                AI_API_KEY = (cfg.get("ai_api_key") or cfg.get("deepseek_api_key", "")).strip()
                AI_URL = cfg.get("ai_url", AI_URL)
                AI_MODEL = cfg.get("ai_model", AI_MODEL)
                AI_AUTH_HEADER = cfg.get("ai_auth_header", AI_AUTH_HEADER)
        except (json.JSONDecodeError, IOError):
            pass


def load_questions():
    global questions_data
    with open(QUESTIONS_FILE, encoding="utf-8") as f:
        questions_data = json.load(f)


# ====== SCORING ======
DIM_ORDER = ["EI", "SN", "TF", "JP", "AT"]
FIRST_POLES = {"EI": "E", "SN": "S", "TF": "T", "JP": "J", "AT": "A"}


def score_traditional(answers):
    """answers: [{"id": int, "value": -2|-1|0|1|2}]"""
    net_scores = {}
    for dim in DIM_ORDER:
        dim_qs = [q for q in questions_data["traditional"] if q["dimension"] == dim]
        net = 0
        first = FIRST_POLES[dim]
        second = dim.replace("E", "I").replace("S", "N").replace("T", "F").replace("J", "P").replace("A", "T")
        # Actually compute second pole more carefully
        if dim == "EI": second = "I"
        elif dim == "SN": second = "N"
        elif dim == "TF": second = "F"
        elif dim == "JP": second = "P"
        elif dim == "AT": second = "T"

        for q in dim_qs:
            match = [a for a in answers if a["id"] == q["id"]]
            if not match:
                continue
            val = match[0]["value"]
            if q["direction"] == first:
                net += val
            else:
                net -= val

        possible_max = len(dim_qs) * 2
        dominant = first if net >= 0 else second
        other = second if net >= 0 else first
        intensity = min(abs(net) / possible_max * 100, 100) if possible_max else 50
        if intensity < 20:
            strength = "neutral"
        elif intensity < 60:
            strength = "slight"
        else:
            strength = "clear"
        dom_pct = round(50 + abs(net) / possible_max * 50) if possible_max else 50
        other_pct = 100 - dom_pct

        net_scores[dim] = {
            "net": net, "dominant": dominant, "other": other,
            "intensity": round(intensity), "strength": strength,
            "dom_pct": dom_pct, "other_pct": other_pct,
        }

    type_str = "".join(net_scores[d]["dominant"] for d in DIM_ORDER[:4])
    identity = net_scores["AT"]["dominant"]
    return {"type": type_str, "identity": identity, "details": net_scores}


# ====== OPEN-ENDED SELECTION ======
def select_open_ended(details):
    pool = list(questions_data.get("open_ended_pool", []))
    if not pool:
        return []

    random.shuffle(pool)
    selected = []
    used_ids = set()

    def pick_one(tag, focus_dim=None):
        for q in pool:
            if tag in q.get("tags", []) and q["id"] not in used_ids:
                item = dict(q)
                if focus_dim:
                    item["focus_dimension"] = focus_dim
                selected.append(item)
                used_ids.add(q["id"])
                return True
        return False

    # Open-ended questions improve accuracy most when they probe weak or borderline dimensions.
    uncertainty = []
    clear_dims = []
    for dim in DIM_ORDER:
        d = details.get(dim, {})
        dom_pct = int(d.get("dom_pct", 50))
        strength = d.get("strength", "neutral")
        dominant = d.get("dominant", "")
        closeness = abs(dom_pct - 50)
        if strength != "clear" or dom_pct < 68:
            uncertainty.append((closeness, dim))
        elif dominant:
            clear_dims.append(f"shadow_{dominant}")

    uncertainty.sort(key=lambda x: x[0])
    for _, dim in uncertainty:
        if len(selected) >= 5:
            break
        pick_one(f"probe_{dim}", dim)

    # For clear dimensions, use shadow questions to test whether the label survives a harder context.
    random.shuffle(clear_dims)
    for tag in clear_dims:
        if len(selected) >= 5:
            break
        pick_one(tag)

    if len(selected) < 5:
        for q in pool:
            if "mixed" in q.get("tags", []) and q["id"] not in used_ids:
                selected.append(dict(q))
                used_ids.add(q["id"])
                if len(selected) >= 5:
                    break

    if len(selected) < 5:
        for q in pool:
            if q["id"] not in used_ids:
                selected.append(dict(q))
                used_ids.add(q["id"])
                if len(selected) >= 5:
                    break

    result = []
    for i, q in enumerate(selected[:5]):
        result.append({
            "display_id": f"oe_{i+1}",
            "id": q["id"],
            "text": q["text"],
            "hint": q.get("hint", ""),
            "focus_dimension": q.get("focus_dimension", ""),
        })
    return result


# ====== DEEPSEEK ======
def call_ai(system_prompt, user_prompt, retries=2, temperature=0.3, max_tokens=4096):
    """Generic AI caller. Configure `ai_url`, `ai_model`, and `ai_api_key` in `config.json` or via env vars.
    Keeps default pointing to DeepSeek for backward compatibility."""
    if not AI_API_KEY:
        raise ValueError("AI API Key 未设置。请在 config.json 中配置 ai_api_key 或设置环境变量 AI_API_KEY。")

    messages = []
    if system_prompt and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    payload = json.dumps({
        "model": AI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")

    req = Request(AI_URL, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    # allow configurable header name (some domestic APIs expect other header names)
    req.add_header(AI_AUTH_HEADER, f"Bearer {AI_API_KEY}")

    last_error = None
    for attempt in range(retries + 1):
        try:
            with urlopen(req, timeout=120) as resp:
                raw = resp.read()
                try:
                    body = raw.decode("utf-8")
                except UnicodeDecodeError:
                    body = raw.decode("utf-8", errors="replace")
                data = json.loads(body)
            # try common response shapes
            if isinstance(data, dict) and data.get("choices"):
                return data["choices"][0]["message"]["content"]
            # some APIs return {"result": "..."} or similar
            if isinstance(data, dict) and data.get("result"):
                return data.get("result")
            # fallback: return raw body
            return body
        except HTTPError as e:
            err_text = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"AI API 错误: {err_text}")
        except URLError as e:
            last_error = e
            if attempt < retries:
                import time
                time.sleep(1)
            continue
    raise RuntimeError(f"网络错误: {last_error}")


def call_deepseek(system_prompt, user_prompt, retries=2, temperature=0.3, max_tokens=4096):
    # kept for backward compatibility; delegate to generic caller
    return call_ai(system_prompt, user_prompt, retries=retries, temperature=temperature, max_tokens=max_tokens)


import re

# 乱答检测 — 过滤掉无意义的回答以节省 token
_NONSENSE_RE = re.compile(r'^(.)\1{2,}$|^[a-zA-Z]{1,3}$|^(.){1,2}$|^(嗯|哦|啊|哈|是|对|好|行|不|无|有|没|了|的){1,4}$|^(asdf|qwer|test|测试|111|222|aaa|bbb)$', re.IGNORECASE)

def is_nonsense(text):
    if not text or len(text.strip()) < 3:
        return True
    t = text.strip()
    if _NONSENSE_RE.search(t):
        return True
    # 重复字符占比超过 60%
    if len(t) > 3 and max(t.count(c) for c in set(t)) / len(t) > 0.6:
        return True
    # 纯标点符号
    if all(not c.isalnum() for c in t):
        return True
    return False

def analyze_with_ai(traditional_type, identity, details, open_answers):
    # 过滤乱答
    filtered = [oa for oa in open_answers if not is_nonsense(oa.get("answer", ""))]
    meaningful = len(filtered)
    total = len(open_answers)
    if meaningful == 0:
        return _fallback_analysis(traditional_type, identity, details, open_answers)
    if meaningful < total:
        print(f"[nonsense] 过滤了 {total - meaningful}/{total} 条乱答", file=sys.stderr)
    try:
        return _analyze_with_deepseek(traditional_type, identity, details, filtered)
    except (RuntimeError, ValueError) as e:
        import traceback, sys
        traceback.print_exc()
        print(f"[analyze_with_ai] Caught {type(e).__name__}: {e}", file=sys.stderr)
        return _fallback_analysis(traditional_type, identity, details, open_answers)
    except Exception as e:
        import traceback, sys
        traceback.print_exc()
        print(f"[analyze_with_ai] UNEXPECTED {type(e).__name__}: {e}", file=sys.stderr)
        return _fallback_analysis(traditional_type, identity, details, open_answers)


def _fallback_analysis(traditional_type, identity, details, open_answers):
    """Generate a fallback analysis from profile data when DeepSeek is unreachable."""
    full_type = f"{traditional_type}-{identity}"
    profile = questions_data.get("type_profiles", {}).get(traditional_type, {})
    dim_names = {"EI": "精力来源", "SN": "认知方式", "TF": "决策方式", "JP": "生活态度", "AT": "身份认同"}

    dim_analysis = {}
    for dim in DIM_ORDER:
        d = details.get(dim, {})
        dom = d.get("dominant", "?")
        pct = d.get("dom_pct", 50)
        meta = dim_names.get(dim, dim)
        label = "明显偏向" if pct > 70 else ("轻微偏向" if pct > 55 else "接近居中")
        verdict = "confirmed" if pct > 65 else ("tension" if pct > 50 else "insufficient")
        dim_analysis[dim] = {
            "倾向": dom,
            "verdict": verdict,
            "confidence": min(pct + 10, 95),
            "evidence": f"传统量表数据显示你在该维度偏向 {dom}（{pct}%），属于「{label}」。",
            "分析": f"基于量表统计，你在 {meta}（{dim}）维度上表现出 {dom} 倾向。" + ("这一倾向较为明显。" if pct > 60 else "但并非极端，在不同情境下可能有所变化。")
        }

    return {
        "portrait": "",
        "insight_title": "AI 深度解读",
        "insight": f"基于传统量表数据，你的类型为 {full_type}。由于 AI 深度分析服务暂不可用，以下分析基于统计数据和类型特征生成，仅供参考。完成开放题后再次提交可获得更精准的个性化解读。",
        "secret_letter_title": f"给{full_type}的你 的悄悄话",
        "secret_letter": "MBTI 只是一个帮助我们了解自己倾向的工具，它描述的是偏好而非能力，是倾向而非定论。",
        "agreement": "medium",
        "ai_available": False,
        "is_fallback": True,
        "ai_confidence": 60,
        "answer_quality_score": 50,
        "insufficient_evidence_dims": [],
        "differences": ["AI 深度分析暂不可用，无法对比差异。请稍后重试或检查 API 配置。"],
        "dimension_analysis": dim_analysis,
        "strengths": (profile.get("strengths") or [])[:4] or ["暂无数据"],
        "growth_areas": (profile.get("weaknesses") or [])[:3] or ["暂无数据"],
        "career_hints": (profile.get("careers") or [])[:6] or [],
        "follow_up_questions": [
            "尝试描述一个最近让你感到困扰或兴奋的具体场景？",
            "你在团队中通常扮演什么角色？",
            "什么情况下你会觉得最有成就感？"
        ],
    }


def _analyze_with_deepseek(traditional_type, identity, details, open_answers):
    """Split into two calls: first generates long insight text, second generates structured JSON."""
    dim_names = {"EI": "精力来源", "SN": "认知方式", "TF": "决策方式", "JP": "生活态度", "AT": "身份认同"}
    dim_desc = []
    for dim in DIM_ORDER:
        d = details.get(dim, {})
        dom = d.get("dominant", "?")
        pct = d.get("dom_pct", 50)
        strength = d.get("strength", "")
        dim_desc.append(f"- {dim_names.get(dim, dim)} ({dim}): {dom} {pct}% ({strength})")

    full_type = f"{traditional_type}-{identity}"
    answers_text = "\n".join(
        f"Q{oa.get('display_id', i+1)}: {oa.get('text', '')}\n回答: {oa.get('answer', '')}"
        for i, oa in enumerate(open_answers)
        if oa.get("answer", "").strip()
    )

    # ====== CALL 1: Generate analysis summary & structured data ======
    call1_prompt = f"""你是MBTI人格分析专家。分析一位{full_type}型人格的开放题回答，输出JSON。

传统量表结果：{full_type}
维度得分：
{chr(10).join(dim_desc)}

回答内容：
{answers_text if answers_text else "（未填写）"}

要求：
- 通篇用「你」称呼对方，不要用「用户」
- 引用原话时直接加引号（如"我当时的感受是…"），不要标注Q1/Q2等编号
- 核心任务是验证为什么对方确实是{full_type}型——回答中哪些思维模式、情绪反应、行为倾向印证了各维度
- 从认知功能角度分析（用F/T/N/S等方向字母，不要Fe/Ni这类缩写，方便普通用户理解）
- 使用心理学、认知科学术语但自然融入，不堆砌
- 使用中文标点符号

请输出JSON，不要markdown代码块：
{{
  "analysis_summary": "400~600字深度分析。以「你」称呼，引用原话（不加编号），从认知功能角度（用F/T/N/S等方向字母，不用Fe/Ni缩写）解读行为模式，论证各维度倾向的真实性。要有温度和洞察力。",
  "dimension_analysis": {{
    "EI": {{"倾向":"E/I","confidence":0-100,"evidence":"引用原话（不加编号）","分析":"100~180字认知功能分析"}},
    "SN": {{"倾向":"S/N","confidence":0-100,"evidence":"引用原话（不加编号）","分析":"100~180字认知功能分析"}},
    "TF": {{"倾向":"T/F","confidence":0-100,"evidence":"引用原话（不加编号）","分析":"100~180字认知功能分析"}},
    "JP": {{"倾向":"J/P","confidence":0-100,"evidence":"引用原话（不加编号）","分析":"100~180字认知功能分析"}},
    "AT": {{"倾向":"A/T","confidence":0-100,"evidence":"引用原话（不加编号）","分析":"100~180字认知功能分析"}}
  }},
  "agreement": "high/medium/low",
  "agreement_details": {{"matching_dims":[],"differing_dims":[],"explanation":"解释一致与差异"}},
  "differences": [],
  "strengths": [],
  "growth_areas": [],
  "career_hints": [],
  "core_tension": "80字以内，为你的焦虑或困境精准命名",
  "verdicts": {{"EI":"✅","SN":"✅","TF":"⚠️","JP":"✅","AT":"?"}}
}}

关于verdicts：根据开放题内容对每个维度做独立判断，不要照抄量表倾向。✅=支持量表倾向，⚠️=存在张力，?=信息不足。每个维度都要写，不要全部写✅。"""

    print(f"[AI] Call 1: generating analysis data...", file=sys.stderr)
    raw1 = call_deepseek("", call1_prompt, temperature=0.5, max_tokens=4096)
    raw1 = raw1.strip()
    if raw1.startswith("```"):
        raw1 = raw1.split("\n", 1)[-1]
        raw1 = raw1.rsplit("```", 1)[0]

    # Parse JSON
    import re as _re
    parsed = {}
    try:
        parsed = json.loads(raw1)
    except json.JSONDecodeError:
        brace_start = raw1.find("{")
        brace_end = raw1.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            try:
                parsed = json.loads(raw1[brace_start:brace_end + 1])
            except:
                pass

    analysis_summary = parsed.get("analysis_summary", "")
    dim_analysis = parsed.get("dimension_analysis", {})
    # Ensure all 5 dimensions exist
    for dim in DIM_ORDER:
        if dim not in dim_analysis or not isinstance(dim_analysis[dim], dict):
            dim_analysis[dim] = {"倾向": "", "confidence": 60, "evidence": "", "分析": ""}

    # ====== CALL 2: Portrait + Letter ======
    letter_context = f"分析摘要：{analysis_summary[:400]}" if analysis_summary else ""
    call2_prompt = f"""你是一位温暖有洞察力的心理学家兼作家。请为一位{full_type}型的人撰写两份文字。

{letter_context}

对方自己的话：
{answers_text if answers_text else "（未填写）"}

请按以下结构输出，用「你」称呼。不要标题。

一、整体气质画像（150~250字）
画一幅人物速写像：你说话做事像什么？给人什么感觉？像一种什么场景、物件或声音？
先描绘画像，再点出藏在画像里的矛盾。
用短句、断句、意象堆叠——像一段诗意的意识流，让人「看见人」。
用有节奏的标点（句号、逗号、破折号）控制呼吸感，不要全程无标点。

二、悄悄话（300~600字）
用文学性和心理洞察写出最需要被理解的部分。
引用对方原话1-2处（直接用引号，不要标编号）。
语气像一位懂你的朋友——温暖、坦诚、不评判。
直接以内容开头。"""

    print(f"[AI] Call 2: portrait + letter…", file=sys.stderr)
    raw2 = call_deepseek("", call2_prompt, temperature=0.7, max_tokens=2048)
    raw2 = raw2.strip()
    if raw2.startswith("```"):
        raw2 = raw2.split("\n", 1)[-1]
        raw2 = raw2.rsplit("```", 1)[0]

    # Parse portrait and letter from Call 2
    import re
    portrait = ""
    letter = ""

    profile_marker = "整体气质画像"
    letter_marker = "悄悄话"

    profile_pos = raw2.find(profile_marker)
    letter_pos = raw2.find(letter_marker)

    if profile_pos >= 0:
        content_start = profile_pos + len(profile_marker)
        nl = raw2.find("\n", content_start)
        if nl != -1:
            content_start = nl + 1
        if letter_pos >= 0:
            portrait = raw2[content_start:letter_pos].strip()
        else:
            portrait = raw2[content_start:].strip()

    if letter_pos >= 0:
        letter_start = letter_pos + len(letter_marker)
        nl2 = raw2.find("\n", letter_start)
        if nl2 != -1:
            letter_start = nl2 + 1
        letter = raw2[letter_start:].strip()

    # Clean up portrait
    def _strip_md(s):
        return re.sub(r'^#{1,6}\s+', '', s, flags=re.MULTILINE).strip()

    portrait = _strip_md(portrait)
    portrait = re.sub(r'\*{2,}', '', portrait).strip()
    portrait = re.sub(r'^[一二][、.．]?\s*整体气质画像\s*', '', portrait).strip()
    portrait = re.sub(r'\n+#{0,4}\s*二[、.．].*$', '', portrait).strip()

    # Clean up letter
    letter = _strip_md(letter)
    letter = re.sub(r'\*{2,}', '', letter).strip()
    letter = re.sub(r'^[一二][、.．]?\s*悄悄话\s*', '', letter).strip()

    if not letter or len(letter) < 30:
        letter = ""
    if not portrait or len(portrait) < 30:
        portrait = analysis_summary[:200] if analysis_summary else ""

    # Extract core_tension and verdicts
    core_tension = parsed.get("core_tension", "")
    ai_verdicts = parsed.get("verdicts", {})

    # Build dimension_analysis with verdicts
    dim_verdicts = {}
    for dim in DIM_ORDER:
        v = ai_verdicts.get(dim, "?")
        if v == "✅":
            dim_verdicts[dim] = "confirmed"
        elif "⚠" in v:
            dim_verdicts[dim] = "tension"
        else:
            dim_verdicts[dim] = "insufficient"

    dim_analysis_with_verdicts = {}
    for dim in DIM_ORDER:
        ad = dim_analysis.get(dim, {})
        dom = details.get(dim, {}).get("dominant", "")
        verdict = dim_verdicts.get(dim, "insufficient")
        conf = 90 if verdict == "confirmed" else (70 if verdict == "tension" else 55)
        dim_analysis_with_verdicts[dim] = {
            "倾向": dom,
            "verdict": verdict,
            "confidence": conf,
            "evidence": ad.get("evidence", ""),
            "分析": ad.get("分析", ""),
        }

    # Build result
    full_type_full = f"{traditional_type}-{identity}"
    result = {
        "portrait": portrait,
        "insight": analysis_summary,
        "secret_letter_title": f"给{full_type_full}的你 的悄悄话",
        "secret_letter": letter,
        "insight_title": "AI 深度解读",
        "ai_type": parsed.get("ai_type", full_type_full),
        "ai_confidence": parsed.get("ai_confidence", 72),
        "answer_quality_score": parsed.get("answer_quality_score", 60),
        "dimension_analysis": dim_analysis_with_verdicts,
        "insufficient_evidence_dims": [d for d, v in ai_verdicts.items() if v == "?"],
        "follow_up_questions": parsed.get("follow_up_questions", []),
        "agreement": parsed.get("agreement", "high"),
        "agreement_details": parsed.get("agreement_details", {"matching_dims":[],"differing_dims":[],"explanation":""}),
        "differences": parsed.get("differences", []),
        "strengths": parsed.get("strengths", []),
        "growth_areas": parsed.get("growth_areas", []),
        "career_hints": parsed.get("career_hints", []),
        "core_tension": core_tension,
        "ai_available": True,
        "is_fallback": False,
    }

    print(f"[AI] Final: portrait={len(portrait)}c secret={len(letter)}c strengths={len(result['strengths'])} verdicts={dim_verdicts}", file=sys.stderr)
    return result


# ====== HTTP HANDLER ======
class Handler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        try:
            data = Path(path).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self._send_error(404, "File not found")

    def _send_error(self, code, msg):
        self._send_json({"error": msg}, code)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError:
            return json.loads(raw.decode("utf-8", errors="replace"))

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send_file(HERE / "index.html", "text/html; charset=utf-8")
        elif self.path == "/api/questions":
            self._send_json(questions_data)
        else:
            p = HERE / self.path.lstrip("/")
            if p.exists() and p.is_file():
                ext = p.suffix.lower()
                ct = {"html": "text/html; charset=utf-8", "css": "text/css",
                      "js": "application/javascript", "json": "application/json",
                      "png": "image/png", "jpg": "image/jpeg",
                      "svg": "image/svg+xml"}.get(ext.lstrip("."), "application/octet-stream")
                self._send_file(p, ct)
            else:
                self._send_file(HERE / "index.html", "text/html; charset=utf-8")

    def do_POST(self):
        if self.path == "/api/score":
            try:
                body = self._read_body()
                result = score_traditional(body.get("answers", []))
                result["selected_questions"] = select_open_ended(result["details"])
                self._send_json(result)
            except Exception as e:
                self._send_error(400, str(e))
        elif self.path == "/api/analyze":
            try:
                body = self._read_body()
                t_type = body.get("type", "")
                identity = body.get("identity", "")
                details = body.get("details", {})
                open_answers = body.get("open_answers", [])
                result = analyze_with_ai(t_type, identity, details, open_answers)
                self._send_json(result)
            except ValueError as e:
                self._send_error(400, str(e))
            except RuntimeError as e:
                self._send_error(502, str(e))
            except json.JSONDecodeError:
                self._send_error(502, "AI 返回格式异常，请重试")
            except Exception as e:
                self._send_error(500, f"服务器内部错误: {e}")
        else:
            self._send_error(404, "Not found")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {args[0]} {args[1]} {args[2]}")


def main():
    parser = argparse.ArgumentParser(description="MBTI 人格测试服务器")
    parser.add_argument("--port", type=int, default=8899, help="端口 (默认: 8899)")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址 (默认: 127.0.0.1)")
    args = parser.parse_args()

    load_config()
    load_questions()

    if not AI_API_KEY:
        print("[!] AI API Key 未配置")
        print("    请在 config.json 中添加 (示例):")
        print('    {')
        print('      "ai_backend": "glm51",')
        print('      "ai_backends": {')
        print('        "deepseek": {')
        print('          "ai_url": "https://api.deepseek.com/v1/chat/completions",')
        print('          "ai_model": "deepseek-chat",')
        print('          "ai_api_key": "<your-deepseek-api-key>",')
        print('          "ai_auth_header": "Authorization"')
        print('        },')
        print('        "glm51": {')
        print('          "ai_url": "https://your-glm-provider/api/v1/chat/completions",')
        print('          "ai_model": "glm-5.1",')
        print('          "ai_api_key": "<your-glm-api-key>",')
        print('          "ai_auth_header": "Authorization"')
        print('        }')
        print('      }')
        print('    }')
        print("    或设置环境变量: set AI_API_KEY=<your-api-key>")
        print("    传统测试仍可正常使用\n")

    server = HTTPServer((args.host, args.port), Handler)
    print(f"MBTI 测试服务器已启动")
    print(f"  地址: http://{args.host}:{args.port}")
    print(f"  题目: {len(questions_data.get('traditional', []))} 道 Likert 量表")
    print(f"  维度: {' · '.join(DIM_ORDER)}")
    print(f"  类型: {16} × {2} = {32} 种人格类型")
    print(f"  AI:  {'已启用' if AI_API_KEY else '未配置'} (backend={AI_BACKEND})")
    print(f"  Key: {CONFIG_FILE.name} / AI_API_KEY 环境变量")
    print("按 Ctrl+C 停止")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止...")
        server.server_close()


if __name__ == "__main__":
    main()
