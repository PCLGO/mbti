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
def call_ai(system_prompt, user_prompt, retries=2):
    """Generic AI caller. Configure `ai_url`, `ai_model`, and `ai_api_key` in `config.json` or via env vars.
    Keeps default pointing to DeepSeek for backward compatibility."""
    if not AI_API_KEY:
        raise ValueError("AI API Key 未设置。请在 config.json 中配置 ai_api_key 或设置环境变量 AI_API_KEY。")

    payload = json.dumps({
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.3,
        "max_tokens": 4096,
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
                content = data["choices"][0]["message"]["content"]
                # Handle both string and structured content blocks (Claude, Kimi format)
                if isinstance(content, str):
                    return content
                elif isinstance(content, list):
                    # Extract text from content blocks
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                    if text_parts:
                        return "".join(text_parts)
                    else:
                        raise RuntimeError("Content block is not a text block: 无法从返回数据中提取文本内容")
                else:
                    raise RuntimeError(f"Unexpected content format: {type(content)}")
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


def call_deepseek(system_prompt, user_prompt, retries=2):
    # kept for backward compatibility; delegate to generic caller
    return call_ai(system_prompt, user_prompt, retries=retries)


def analyze_with_ai(traditional_type, identity, details, open_answers):
    try:
        return _analyze_with_deepseek(traditional_type, identity, details, open_answers)
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
    full_type = f"{traditional_type}{identity}"
    profile = questions_data.get("type_profiles", {}).get(traditional_type, {})
    dim_names = {"EI": "精力来源", "SN": "认知方式", "TF": "决策方式", "JP": "生活态度", "AT": "身份认同"}

    dim_analysis = {}
    for dim in DIM_ORDER:
        d = details.get(dim, {})
        dom = d.get("dominant", "?")
        pct = d.get("dom_pct", 50)
        meta = dim_names.get(dim, dim)
        label = "明显偏向" if pct > 70 else ("轻微偏向" if pct > 55 else "接近居中")
        dim_analysis[dim] = {
            "倾向": f"{dom} ({pct}%)",
            "confidence": min(pct + 10, 95),
            "evidence": f"传统量表数据显示你在该维度偏向 {dom}（{pct}%），属于「{label}」。",
            "分析": f"基于量表统计，你在 {meta}（{dim}）维度上表现出 {dom} 倾向。" + ("这一倾向较为明显。" if pct > 60 else "但并非极端，在不同情境下可能有所变化。")
        }

    return {
        "insight": f"基于传统量表数据，你的类型为 {full_type}。由于 AI 深度分析服务暂不可用，以下分析基于统计数据和类型特征生成，仅供参考。完成开放题后再次提交可获得更精准的个性化解读。",
        "agreement": "medium",
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
        "summary": f"你的传统测试结果为 {full_type}。各维度数据显示了你的基本倾向分布。由于当前 AI 分析服务暂不可用，详细的交叉验证和个性化洞察将在服务恢复后提供。"
    }


def _analyze_with_deepseek(traditional_type, identity, details, open_answers):
    """open_answers is a list of {display_id, text, answer}"""
    dim_names = {"EI": "精力来源", "SN": "认知方式", "TF": "决策方式", "JP": "生活态度", "AT": "身份认同"}
    dim_desc = []
    for dim in DIM_ORDER:
        d = details.get(dim, {})
        dom = d.get("dominant", "?")
        pct = d.get("dom_pct", 50)
        strength = d.get("strength", "")
        dim_desc.append(f"- {dim_names.get(dim, dim)} ({dim}): {dom} {pct}% ({strength})")

    full_type = f"{traditional_type}{identity}"
    answers_text = "\n".join(
        f"Q{oa.get('display_id', i+1)}: {oa.get('text', '')}\n回答: {oa.get('answer', '')}"
        for i, oa in enumerate(open_answers)
        if oa.get("answer", "").strip()
    )

    system_prompt = """你是MBTI人格分析专家，擅长从语言表达的细节和模式中深度分析人格特质。

你会收到用户的传统MBTI测试结果和开放式问题的回答。

核心原则：
1. **分析深度与回答质量对等**：用户回答越详细（具体场景、情绪描述、决策过程、事例细节），你的分析必须越深入。引用用户回答中的具体关键词、短语、对比和矛盾点作为证据。如果用户只写一句话，则相应简短；如果用户写了长篇具体经历，则从多个角度切入做透彻分析。

2. **严格独立验证**：基于开放题文本逐维分析 EI/SN/TF/JP/AT。不要盲目认同传统结果——如果回答展现出不同的倾向，如实指出并说明理由。引用原文作为倾向证据。

3. **情感关照**：注意用户语言中的情绪色彩（焦虑、自信、矛盾、兴奋等），在 insight 和 summary 中体现情感共情。对自我暴露较多的回答，分析应更温和且有深度。

4. **多角度切入**：从以下角度分析回答——(a) 具体行为选择 vs 抽象理念，(b) 情绪表达方式和强度，(c) 决策依据（原则/情感/实用），(d) 对冲突和压力的反应模式，(e) 自我觉察程度。结合这些角度形成综合判断。

5. **诚实面对不确定性**：证据不足时降低 confidence，列出 insufficient_evidence_dims。不从一句话过度推断。

始终以纯JSON格式回复，不要包含markdown代码块或其他文字。"""

    user_prompt = f"""## 传统MBTI测试结果
初步类型: {full_type}

各维度详情:
{chr(10).join(dim_desc)}

## 用户开放式回答
{answers_text if answers_text else "（用户未填写开放题）"}

## 要求
请严格分析上述信息，返回纯JSON（不要markdown代码块标记）。如果用户未填写回答，请降低confidence。

**重要——分析深度必须与用户回答质量成正比**：用户回答越详细、越具体（包含真实经历、场景描述、情绪感受、决策过程），你的 insight、summary、dimension_analysis 中的"分析"字段必须越充分，直接引用用户原话作为证据。简短回答则相应简短，不强行拉长。

{{
  "ai_type": "基于开放题分析得出的5字母MBTI类型（含A/T，如ENFJ-A）",
  "ai_confidence": "0-100的整数，反映你对回答证据充分性的信心",
  "answer_quality_score": "0-100的整数，反映回答细节、具体例子和自我反思的充分程度",
  "insufficient_evidence_dims": ["证据不足的维度，如EI或JP"],
  "follow_up_questions": ["如果需要提高准确性，建议继续追问的问题，最多3个"],
  "agreement": "high/medium/low 表示传统结果与AI分析的整体一致程度",
  "agreement_details": {{
    "matching_dims": ["一致维度列表，如EI", "SN"],
    "differing_dims": ["差异维度列表，如TF"],
    "explanation": "对一致与差异的简要解释"
  }},
  "dimension_analysis": {{
    "EI": {{"倾向": "E或I", "confidence": 0-100, "evidence": "从用户的回答中引用具体内容作为证据", "分析": "一两句话的综合判断"}},
    "SN": {{"倾向": "S或N", "confidence": 0-100, "evidence": "引用回答中的具体内容", "分析": "一两句话的综合判断"}},
    "TF": {{"倾向": "T或F", "confidence": 0-100, "evidence": "引用回答中的具体内容", "分析": "一两句话的综合判断"}},
    "JP": {{"倾向": "J或P", "confidence": 0-100, "evidence": "引用回答中的具体内容", "分析": "一两句话的综合判断"}},
    "AT": {{"倾向": "A或T", "confidence": 0-100, "evidence": "引用回答中的具体内容", "分析": "一两句话的综合判断"}}
  }},
  "differences": ["传统与AI分析之间的主要差异，具体说明差异在哪里"],
  "insight": "对你性格的深刻洞察（2-3句话，中文）",
  "summary": "综合性格总结（3-5句话，中文）",
  "strengths": ["优势1（附简要解释）", "优势2", "优势3"],
  "growth_areas": ["成长建议1（附原因）", "成长建议2"],
  "career_hints": ["可能适合的方向1", "方向2"]
}}"""

    raw = call_deepseek(system_prompt, user_prompt)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0]

    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError as e:
        debug_log = f"[AI Parse Error] {e}\n---RAW START---\n{raw}\n---RAW END---"
        print(debug_log, file=sys.stderr)
        import re
        brace_start = raw.find("{")
        brace_end = raw.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            candidate = raw[brace_start:brace_end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
        raise RuntimeError(f"AI 返回格式异常，请重试。{e}")


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
        print('          "ai_api_key": "sk-你的-deepseek-key",')
        print('          "ai_auth_header": "Authorization"')
        print('        },')
        print('        "glm51": {')
        print('          "ai_url": "https://your-glm-provider/api/v1/chat/completions",')
        print('          "ai_model": "glm-5.1",')
        print('          "ai_api_key": "sk-你的-glm-key",')
        print('          "ai_auth_header": "Authorization"')
        print('        }')
        print('      }')
        print('    }')
        print("    或设置环境变量: set AI_API_KEY=sk-xxx")
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
