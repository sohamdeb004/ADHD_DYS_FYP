# PUGU (Personalized Understanding and Guidance Unit) — MVP

Two tools in one Streamlit app:

1. **ADHD Task Chunker** — breaks a task into small steps, walks you through them one at a time.
2. **Dyslexia Reading Overlay** — reformats pasted text for easier reading, with optional read-aloud.

Adaptiveness (kept simple on purpose): the app remembers each user's last-used
chunk length, font, and TTS setting in a local SQLite file, and uses those as
next-time defaults. No AI involved in that part — it's just stored state.

## Setup

```bash
cd pugu
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
streamlit run app.py
```

This opens the app in your browser at `http://localhost:8501`.

## Notes

- **API key is optional.** Leave it blank and the task chunker still works,
  using a simple built-in step template instead of an AI-generated one.
  Add an Anthropic API key later for smarter, task-specific steps.
- **OpenDyslexic font:** the code references `'OpenDyslexic'` by name. To
  actually load the font, download it (it's free/open-license) and add an
  `@font-face` rule pointing to the file, or link a CDN copy — either works,
  just needs the font file to be reachable by the browser.
- **Data:** everything is stored locally in `pugu.db` (SQLite) — nothing
  leaves your machine except the optional chunking API call.
- **Deployment:** push this folder to a GitHub repo and deploy it on
  Streamlit Community Cloud (free tier) when you're ready to share it.
