"""
PUGU (Personalized Understanding and Guidance Unit)
ADHD Task Chunker + Dyslexia Reading Overlay
A single-file Streamlit app. No paid backend required.

Run with:  streamlit run app.py

--------------------------------------------------------------------------
FILE MAP (for anyone extending this later)
--------------------------------------------------------------------------
1. Database helpers   -> init_db / get_settings / save_settings
2. Tool 1              -> chunk_task_simple / chunk_task_ai   (ADHD chunker)
3. Tool 2              -> render_reading_overlay              (Dyslexia overlay)
4. App / UI            -> everything below the "App" divider, run top-to-bottom
                           by Streamlit on every interaction (button click,
                           slider drag, etc. all re-run this whole script).

To add a THIRD tool: write its logic as a plain function above the "App"
section (following the pattern of Tool 1 / Tool 2), then add a new tab in
the `st.tabs([...])` call and a matching `with tab3:` block.
--------------------------------------------------------------------------
"""

import re
import sqlite3
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# Local SQLite file that stores per-user settings. Created automatically on
# first run, sitting next to this script. Safe to delete to reset all data.
DB_PATH = Path(__file__).parent / "pugu.db"


# ---------------------------------------------------------------------------
# Database: just enough to remember each user's last-used settings.
# This IS the "adaptive" part for now — simple, not an AI system.
#
# Schema: one row per user_id, storing their last-used chunk length, font,
# and TTS toggle. If you add a new setting (e.g. a new tool's preference),
# add a column here AND update get_settings/save_settings to match — the
# three functions in this section always need to stay in sync.
# ---------------------------------------------------------------------------

def init_db():
    """Open (or create) the SQLite file and make sure the settings table exists.
    Called once at app startup. check_same_thread=False is needed because
    Streamlit can touch the connection from more than one thread."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            user_id TEXT PRIMARY KEY,
            chunk_minutes INTEGER DEFAULT 10,
            font_choice TEXT DEFAULT 'OpenDyslexic',
            tts_enabled INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def get_settings(conn, user_id):
    """Look up a user's saved settings, or return sensible defaults if this
    is a new/unknown user_id. Always returns a dict with all three keys so
    callers never have to check for missing fields."""
    row = conn.execute(
        "SELECT chunk_minutes, font_choice, tts_enabled FROM settings WHERE user_id=?",
        (user_id,),
    ).fetchone()
    if row:
        return {"chunk_minutes": row[0], "font_choice": row[1], "tts_enabled": bool(row[2])}
    # Defaults for a brand-new user — keep these in sync with the table's
    # own DEFAULT values above if you change one.
    return {"chunk_minutes": 10, "font_choice": "OpenDyslexic", "tts_enabled": False}


def save_settings(conn, user_id, chunk_minutes, font_choice, tts_enabled):
    """Upsert: insert a new row for this user, or overwrite their existing
    one if they already have settings saved. Called every time the user
    takes an action so their latest choices become next session's defaults."""
    conn.execute(
        """
        INSERT INTO settings (user_id, chunk_minutes, font_choice, tts_enabled)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            chunk_minutes=excluded.chunk_minutes,
            font_choice=excluded.font_choice,
            tts_enabled=excluded.tts_enabled
        """,
        (user_id, chunk_minutes, font_choice, int(tts_enabled)),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tool 1 — ADHD Task Chunker
#
# Two ways to generate steps:
#   - chunk_task_simple: free, offline, template-based. Always used as a
#     fallback so the app never fully breaks.
#   - chunk_task_ai: optional, needs a user-supplied Anthropic API key,
#     produces steps tailored to the actual task text.
# ---------------------------------------------------------------------------

def chunk_task_simple(task: str, chunk_minutes: int):
    """Zero-cost fallback. No AI call, no API key needed. Always works.
    Returns a generic 5-step template with the task name and chunk length
    filled in. Tweak the wording/step count here if you want a different
    default flow — this is what every user sees with no API key set."""
    return [
        f"Get set up: open/gather whatever you need for '{task}'",
        f"Work on the first part of '{task}' for about {chunk_minutes} min",
        "Take a short break — stand up, stretch, water",
        f"Continue '{task}' for another {chunk_minutes} min",
        f"Review what you've done on '{task}' and note what's left",
    ]


def chunk_task_ai(task: str, chunk_minutes: int, api_key: str):
    """Optional: real LLM-generated steps, tailored to the specific task.
    Falls back to chunk_task_simple() on ANY error (bad key, network issue,
    rate limit, unexpected response shape, etc.) so a broken API call never
    crashes the app — the user just silently gets the generic steps instead.

    To change the model, prompt, or step count/format, edit the `prompt`
    string and/or the `model=` argument below.
    """
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            f"Break this task into 4-6 concrete, specific steps, each doable in about "
            f"{chunk_minutes} minutes by someone with ADHD. Task: {task}\n"
            f"Return ONLY a numbered list, nothing else."
        )
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text
        # Strip leading numbering ("1.", "2)", etc.) since we render our own
        # step numbers/UI — we just want the raw step text from each line.
        steps = [
            re.sub(r"^\d+[\.\)]\s*", "", line).strip()
            for line in text.split("\n")
            if line.strip()
        ]
        # If parsing produced nothing usable, fall back rather than show a
        # blank step list.
        return steps or chunk_task_simple(task, chunk_minutes)
    except Exception:
        return chunk_task_simple(task, chunk_minutes)


# ---------------------------------------------------------------------------
# Tool 2 — Dyslexia Reading Overlay
#
# Takes raw pasted text and returns a chunk of HTML: dyslexia-friendly
# styling (font/spacing) plus an optional "read aloud" button that uses the
# browser's built-in text-to-speech (no API key or server needed for this
# part — it's 100% client-side JavaScript).
# ---------------------------------------------------------------------------

def render_reading_overlay(text: str, font_choice: str, tts_enabled: bool) -> str:
    """Build the HTML/CSS/JS string that gets embedded via components.html().

    - font_css: swap in a different web font here (see README for how to
      actually load the OpenDyslexic font file/CDN).
    - sentences/spans: text is split into per-sentence <span> tags so the
      read-aloud feature can highlight each sentence as it's spoken.
    - tts_block: only included when the user has enabled read-aloud;
      contains the button + JS that drives the highlighting/speech.
    """
    font_css = "'OpenDyslexic', sans-serif" if font_choice == "OpenDyslexic" else "Arial, sans-serif"

    # Split on sentence-ending punctuation followed by a space. Good enough
    # for normal prose; won't handle abbreviations like "Dr." perfectly —
    # swap in a proper sentence tokenizer (e.g. nltk) if that matters.
    sentences = re.split(r"(?<=[.!?]) +", text.strip())
    spans = "".join(f'<span class="sentence" id="s{i}">{s} </span>' for i, s in enumerate(sentences))

    tts_block = ""
    if tts_enabled:
        # puguReadAloud() walks through each .sentence span in order,
        # highlights it, and speaks it with the Web Speech API. Purely
        # client-side — works offline, no external TTS service involved.
        tts_block = """
        <button onclick="puguReadAloud()" style="margin-top:12px; padding:8px 16px; font-size:16px;">
            🔊 Read aloud
        </button>
        <script>
        function puguReadAloud() {
            const sentences = document.querySelectorAll('.sentence');
            let i = 0;
            function speakNext() {
                if (i >= sentences.length) return;
                sentences.forEach(s => s.style.background = 'transparent');
                sentences[i].style.background = '#fff3b0';
                const utter = new SpeechSynthesisUtterance(sentences[i].innerText);
                utter.onend = () => { i++; speakNext(); };
                window.speechSynthesis.speak(utter);
            }
            window.speechSynthesis.cancel();  // stop any speech already in progress
            speakNext();
        }
        </script>
        """

    return f"""
    <div style="font-family: {font_css}; font-size: 20px; line-height: 2;
                letter-spacing: 0.5px; max-width: 700px;">
        {spans}
    </div>
    {tts_block}
    """


# ---------------------------------------------------------------------------
# App / UI
#
# Everything below runs top-to-bottom on EVERY interaction (Streamlit
# re-executes the whole script on each button click, slider move, etc.).
# Session-scoped state that needs to survive between reruns (like the
# current step index) lives in st.session_state.
# ---------------------------------------------------------------------------

st.set_page_config(page_title="PUGU", page_icon="🧠")
conn = init_db()  # one connection, reused for the whole session

st.title("🧠 PUGU")
st.caption("Personalized Understanding and Guidance Unit")

# user_id is just a free-text name typed by the user — it's the primary key
# used to look up/save their settings. No auth; anyone can type any name to
# load "their" settings. Fine for an MVP, but swap for real auth/session IDs
# before sharing this beyond trusted testers.
user_id = st.text_input("Your name (so the app remembers your settings)", value="guest")
settings = get_settings(conn, user_id)

tab1, tab2 = st.tabs(["ADHD: Task Chunker", "Dyslexia: Reading Overlay"])

# --- Tab 1: Task Chunker ---
with tab1:
    st.subheader("Break a task into small steps")
    task = st.text_input("What do you need to do?")
    chunk_minutes = st.slider("Preferred step length (minutes)", 3, 20, settings["chunk_minutes"])
    # API key is entered fresh each session (type="password" hides it) and
    # is never saved to disk — only the chunk_minutes/font/tts settings are
    # persisted in the DB.
    api_key = st.text_input("Anthropic API key (optional — leave blank to use the free version)", type="password")

    if st.button("Break it down") and task:
        # Save settings first so the choice sticks even if the AI call below fails.
        save_settings(conn, user_id, chunk_minutes, settings["font_choice"], settings["tts_enabled"])
        steps = chunk_task_ai(task, chunk_minutes, api_key) if api_key else chunk_task_simple(task, chunk_minutes)
        # Stashed in session_state so the step-by-step walkthrough below
        # persists across reruns (e.g. when "Done, next step" is clicked).
        st.session_state["steps"] = steps
        st.session_state["current_step"] = 0

    # Step-by-step walkthrough: shows one step at a time, advances on
    # either button. This block only renders once a task has been chunked.
    if "steps" in st.session_state:
        idx = st.session_state["current_step"]
        steps = st.session_state["steps"]
        if idx < len(steps):
            st.markdown(f"### Step {idx + 1} of {len(steps)}")
            st.info(steps[idx])
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Done, next step"):
                    st.session_state["current_step"] += 1
                    st.rerun()  # force immediate re-render with the new step
            with col2:
                if st.button("⏭️ Skip"):
                    st.session_state["current_step"] += 1
                    st.rerun()
        else:
            st.success("All steps complete! 🎉")

# --- Tab 2: Reading Overlay ---
with tab2:
    st.subheader("Read text in a dyslexia-friendly format")
    text = st.text_area("Paste your text here", height=150)
    font_choice = st.selectbox(
        "Font", ["OpenDyslexic", "Standard"],
        index=0 if settings["font_choice"] == "OpenDyslexic" else 1,
    )
    tts_enabled = st.checkbox("Enable read-aloud", value=settings["tts_enabled"])

    if text:
        # Settings are saved as soon as there's text, before rendering, so
        # the user's font/TTS choice is captured even if they never click
        # an explicit "save" button (there isn't one in this tab).
        save_settings(conn, user_id, settings["chunk_minutes"], font_choice, tts_enabled)
        components.html(render_reading_overlay(text, font_choice, tts_enabled), height=420, scrolling=True)