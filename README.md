# MBTI Personality Test

> **⚠️ WORK IN PROGRESS — This project is still under active development and not yet feature-complete.**

A single-page MBTI (Myers-Briggs Type Indicator) personality test application with a Python backend and AI-powered analysis.

## Features

- **50 Likert-scale questions** covering 5 dimensions: EI, SN, TF, JP, AT
- **Traditional scoring** with percentage-based dimension results
- **5 customized open-ended questions** dynamically selected based on your initial results
- **AI cross-validation** using DeepSeek (configurable to other providers) to verify type against your written responses
- **32 personality types** (16 types × A/T identity variants)
- **Type library** with detailed profiles, strengths, weaknesses, and career suggestions

## Why "Work In Progress"?

Several areas are still being refined:

- **UI/UX polish**: Text copy, layout details, and visual consistency are being iterated on
- **State persistence**: Refresh/save behavior across screens is still being stabilized
- **Open-ended analysis**: The AI analysis flow (quality scoring, fallback handling) is being improved
- **i18n**: Currently Chinese-only; English translation is planned
- **Mobile responsiveness**: Some screens need better mobile layout handling

## Quick Start

```bash
# 1. Configure AI API key
cp mbti/config.example.json mbti/config.json
# Edit mbti/config.json with your API key

# 2. Start the server
python mbti/server.py --port 8899

# 3. Open in browser
open http://127.0.0.1:8899
```

## Project Structure

```
mbti/
├── server.py            # Python backend (stdlib only, no Flask)
├── index.html           # Single-page frontend (Tailwind CSS CDN)
├── questions.json       # 50 Likert questions + open-ended pool + type profiles
├── config.example.json  # AI provider configuration template
└── vision_mcp.py        # [Optional] MCP server for Qwen vision (screenshot analysis)
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/questions` | GET | Returns all questions and dimension config |
| `/api/score` | POST | Submit 50 Likert answers → returns type + custom open-ended questions |
| `/api/analyze` | POST | Submit open-ended answers → returns AI analysis results |

## Tech Stack

- **Backend**: Python stdlib (`http.server`) — no dependencies
- **Frontend**: Single HTML file, vanilla JavaScript, Tailwind CSS (CDN)
- **AI**: DeepSeek (default), configurable to GLM, Kimi, or any OpenAI-compatible API

## License

MIT
