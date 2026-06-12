# BeyondX

AI-powered brand intelligence platform. Give it a business idea and BeyondX runs an 8-stage pipeline — market research, positioning, strategy, naming, identity, visual system, brand deck, and a live web app — producing a complete, investor-ready brand pack.

It also includes an **AI Content Creator** chatbot that generates a full social media content calendar (posts, campaigns, hashtags) for an existing brand.

## Tech stack

**Backend:** FastAPI + LangGraph (Python)
**Frontend:** React + Vite + TypeScript + Tailwind CSS

**LLM providers (by stage):**

| Stage | Task | Primary | Fallback |
|---|---|---|---|
| 1 | Market research | Groq (Llama 3.3 70B) + Tavily | Cerebras |
| 2 | Brand positioning | Groq | — |
| 3 | Go-to-market strategy | Groq | — |
| 4 | Brand naming | Groq + Tavily | — |
| 5 | Brand identity | Groq | — |
| 6 | Visual identity (colors, fonts, logos) | HuggingFace FLUX.1-schnell (logos) + Groq (visual brief) | Gemini Flash (text + image) |
| 7 | Brand deck | Groq (`openai/gpt-oss-120b`) | Gemini Pro → Gemini Flash |
| 8 | Live web app | Lovable (prompt handoff) | — |

**Content Creator Agent:** Groq (Llama 3.3 70B) + Tavily for trend research

> **Note:** Gemini's free tier was reduced to a hard quota of 0 for all models in mid-2026. Gemini keys remain in the codebase as fallbacks only — the pipeline runs entirely on free-tier Groq, Cerebras, and HuggingFace by default.

## Setup

1. Clone the repo and create a Python virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in your API keys:
   ```bash
   cp .env.example .env
   ```

   You'll need accounts (all have free tiers) for:
   - [Groq](https://console.groq.com) — primary LLM provider
   - [Tavily](https://tavily.com) — web search for research/naming
   - [HuggingFace](https://huggingface.co) — logo generation (read-only access token)
   - [Cerebras](https://cloud.cerebras.ai) — research fallback
   - [Google AI Studio](https://aistudio.google.com) — Gemini fallback keys (optional)
   - [Google Places](https://developers.google.com/maps/documentation/places) — local market data

3. Install frontend dependencies:
   ```bash
   cd frontend
   npm install
   ```

## Running locally

**Terminal 1 — API:**
```bash
source venv/bin/activate
python api/run.py
```
Runs on `http://localhost:8000`

**Terminal 2 — Frontend:**
```bash
cd frontend
npm run dev
```
Runs on `http://localhost:5173`

## Project structure

```
agents/           # Stage agents (research, naming, brand book, etc.)
nodes/            # LangGraph nodes for each pipeline stage
content_gen_agent/  # Content Creator chatbot agent
api/              # FastAPI app and routers
frontend/         # React frontend
config/           # Settings, LLM factory
brand_packs/      # Generated brand outputs (gitignored)
```

## Founders

Hana Haridy & Mohamed Abdelhalim