from PIL import Image, ImageDraw, ImageFont
import os

W, H = 1200, 950
img = Image.new("RGB", (W, H), (255, 255, 255))
draw = ImageDraw.Draw(img)

font_path = "C:/Windows/Fonts/msyh.ttc"
try:
    font_title = ImageFont.truetype(font_path, 26)
    font_h1 = ImageFont.truetype(font_path, 20)
    font_h2 = ImageFont.truetype(font_path, 16)
    font_body = ImageFont.truetype(font_path, 13)
    font_small = ImageFont.truetype(font_path, 11)
except:
    font_title = font_h1 = font_h2 = font_body = font_small = ImageFont.load_default()


def round_rect(x, y, w, h, r, fill, outline=None):
    draw.rounded_rectangle([x, y, x + w, y + h], r, fill=fill, outline=outline)


def tw(text, font=font_body, max_w=200):
    if not text:
        return [""]
    lines = []
    for word in text.split(" "):
        if not lines:
            lines.append(word)
        else:
            test = lines[-1] + " " + word
            if draw.textbbox((0, 0), test, font=font)[2] <= max_w:
                lines[-1] = test
            else:
                lines.append(word)
    final = []
    for line in lines:
        if draw.textbbox((0, 0), line, font=font)[2] <= max_w:
            final.append(line)
        else:
            while line:
                i = len(line)
                while i > 0 and draw.textbbox((0, 0), line[:i], font=font)[2] > max_w:
                    i -= 1
                if i == 0:
                    break
                final.append(line[:i])
                line = line[i:].strip()
    return final


# Title
draw.text((40, 25), "MBTI Personality Test — Project Architecture", font=font_title, fill=(30, 30, 30))

# Section 1: File Structure (left)
x0, y0 = 30, 75
round_rect(x0, y0, 560, 340, 12, (240, 248, 255), (180, 210, 230))
draw.text((x0 + 15, y0 + 10), "Project Structure", font=font_h1, fill=(0, 60, 120))

files = [
    ("mbti/server.py", "Python backend", "#1a5276", False),
    ("  score_traditional()", "5-dim scoring", "#2e86c1", True),
    ("  select_open_ended()", "Question picker", "#2e86c1", True),
    ("  analyze_with_ai()", "DeepSeek+fallback", "#2e86c1", True),
    ("mbti/index.html", "Single-page frontend", "#1a5276", False),
    ("  8 screens", "welcome to results", "#2e86c1", True),
    ("  Likert 5-point", "Answer UI", "#2e86c1", True),
    ("  type overlay", "Library detail card", "#2e86c1", True),
    ("mbti/questions.json", "Data bank", "#1a5276", False),
    ("  50 traditional", "Likert questions", "#2e86c1", True),
    ("  20 open-ended", "Pool with tags", "#2e86c1", True),
    ("  32 type profiles", "Strengths/careers", "#2e86c1", True),
    ("mbti/config.*.json", "AI provider config", "#1a5276", False),
    ("mbti/vision_mcp.py", "Qwen vision MCP", "#1a5276", False),
]
for i, (name, desc, color, is_sub) in enumerate(files):
    fy = y0 + 36 + i * 21
    c = tuple(int(color[j:j + 2], 16) for j in (1, 3, 5))
    if is_sub:
        draw.text((x0 + 30, fy), name, font=font_body, fill=c)
        draw.text((x0 + 185, fy), desc, font=font_body, fill=(100, 100, 100))
    else:
        draw.text((x0 + 15, fy), name, font=font_h2, fill=c)
        draw.text((x0 + 225, fy), desc, font=font_body, fill=(100, 100, 100))

# Section 2: Screen Flow (right top)
x1, y1 = 610, 75
round_rect(x1, y1, 560, 195, 12, (245, 240, 255), (200, 180, 230))
draw.text((x1 + 15, y1 + 10), "Frontend Screen Flow", font=font_h1, fill=(80, 30, 120))

screens = [
    ("welcome", "traditional"),
    ("traditional", "open-intro"),
    ("open-intro", "open-ended"),
    ("open-ended", "loading"),
    ("loading/skip", "results"),
]
for i, (s1, s2) in enumerate(screens):
    sy = y1 + 40 + i * 28
    round_rect(x1 + 15, sy, 110, 22, 6, (220, 200, 240))
    draw.text((x1 + 22, sy + 2), s1, font=font_body, fill=(80, 30, 120))
    draw.text((x1 + 132, sy + 2), "▶", font=font_body, fill=(150, 100, 180))
    round_rect(x1 + 150, sy, 110, 22, 6, (230, 215, 245))
    draw.text((x1 + 157, sy + 2), s2, font=font_body, fill=(80, 30, 120))

# Section 3: API Flow (right mid)
x2, y2 = 610, 290
round_rect(x2, y2, 560, 165, 12, (240, 255, 240), (180, 220, 180))
draw.text((x2 + 15, y2 + 10), "API & Data Flow", font=font_h1, fill=(20, 90, 30))

api_steps = [
    ("1. GET /api/questions", "Load questions+profiles"),
    ("2. POST /api/score", "Get type + custom questions"),
    ("3. POST /api/analyze", "AI analysis results"),
    ("4. DeepSeek API", "Cross-validate evidence"),
]
for i, (endpoint, desc) in enumerate(api_steps):
    ay = y2 + 38 + i * 30
    draw.text((x2 + 15, ay), endpoint, font=font_h2, fill=(30, 100, 40))
    draw.text((x2 + 200, ay), desc, font=font_body, fill=(60, 60, 60))

# Section 4: Scoring Detail
x3, y3 = 35, 440
round_rect(x3, y3, 550, 195, 12, (255, 248, 240), (220, 200, 170))
draw.text((x3 + 15, y3 + 10), "5-Dimension Scoring", font=font_h1, fill=(140, 80, 10))

dims = [
    ("EI", "Extraversion / Introversion", "Energy source"),
    ("SN", "Sensing / Intuition", "Cognitive style"),
    ("TF", "Thinking / Feeling", "Decision method"),
    ("JP", "Judging / Perceiving", "Life attitude"),
    ("AT", "Assertive / Turbulent", "Identity"),
]
for i, (dim, full, cn) in enumerate(dims):
    dy = y3 + 38 + i * 30
    round_rect(x3 + 15, dy, 55, 24, 5, (230, 195, 150))
    draw.text((x3 + 22, dy + 3), dim, font=font_h2, fill=(100, 50, 0))
    draw.text((x3 + 85, dy + 3), full, font=font_body, fill=(60, 60, 60))
    draw.text((x3 + 335, dy + 3), cn, font=font_body, fill=(140, 120, 100))

# Section 5: Multi-Agent + AI
x4, y4 = 30, 660
round_rect(x4, y4, 1140, 260, 12, (250, 245, 250), (210, 200, 220))
draw.text((x4 + 15, y4 + 10), "Multi-Agent Workflow & AI Integration", font=font_h1, fill=(100, 30, 80))

dev_tools = [
    ("Claude Code", "Architecture & core logic", (180, 60, 90)),
    ("Codex", "Frontend modifications", (180, 80, 110)),
    ("Cursor + Copilot", "Troubleshoot problems", (160, 80, 120)),
]
for i, (name, desc, bg) in enumerate(dev_tools):
    ax = x4 + 15 + i * 210
    round_rect(ax, y4 + 38, 200, 55, 8, bg + (20,))
    draw.text((ax + 10, y4 + 44), name, font=font_h2, fill=bg)
    draw.text((ax + 10, y4 + 65), desc, font=font_body, fill=(90, 90, 90))

# AI services row
ai_svcs = [
    ("DeepSeek API", "MBTI cross-validation", (120, 60, 100)),
    ("Qwen Vision MCP", "UI screenshot analysis", (60, 100, 140)),
    ("Seedream (doubao)", "Image gen for Ren'Py", (60, 120, 100)),
    ("Suno", "Music gen for Ren'Py", (60, 130, 80)),
]
for i, (name, desc, bg) in enumerate(ai_svcs):
    ax = x4 + 15 + i * 150
    ay = y4 + 110
    round_rect(ax, ay, 140, 50, 8, bg + (15,))
    draw.text((ax + 10, ay + 7), name, font=font_h2, fill=bg)
    draw.text((ax + 10, ay + 30), desc, font=font_body, fill=(90, 90, 90))

# Token box
tx = x4 + 15 + 4 * 150
round_rect(tx, y4 + 110, 230, 50, 8, (255, 245, 235))
draw.text((tx + 10, y4 + 115), "Token: DeepSeek", font=font_h2, fill=(160, 90, 30))
draw.text((tx + 10, y4 + 135), "40M-60M tokens/day", font=font_body, fill=(160, 90, 30))

# Ren'Py note
nx = x4 + 15
round_rect(nx, y4 + 178, 370, 42, 10, (235, 245, 255))
draw.text((nx + 15, y4 + 191), "github.com/PCLGO/mbti", font=font_h2, fill=(30, 80, 150))
draw.text((nx + 230, y4 + 191), "Open Source  |  WIP", font=font_body, fill=(130, 130, 130))

# Application text note
round_rect(nx + 385, y4 + 178, 355, 42, 10, (245, 240, 245))
draw.text((nx + 395, y4 + 191), "MiMo Token Plan: submitted", font=font_body, fill=(130, 100, 130))

img.save("D:/Code/1123/mbti/architecture.png")
print(f"OK: {os.path.getsize('D:/Code/1123/mbti/architecture.png')} bytes")
