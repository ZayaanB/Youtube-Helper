import os
from typing import Dict, Optional

import requests
import streamlit as st
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)
import yt_dlp

st.set_page_config(page_title="Clickbait Buster", page_icon="🕵️‍♂️")
st.title("Clickbait Buster – Meal-Time Edition")

st.markdown(
    """
Tired of doom-scrolling for the *right* video while your food gets cold?

Paste a YouTube link and tell me a bit about you.  
We'll check the title, transcript, and context to rate the clickbait **and** tell you if it's worth your meal-time attention.
"""
)


def has_api_key() -> bool:
    return bool(os.getenv("OPENROUTER_API_KEY"))


MODEL_CHOICES: Dict[str, str] = {
    "Standard check (recommended)": "meta-llama/llama-3.3-70b-instruct:free",
    "Quick check": "openai/gpt-4.1-mini",
}

with st.sidebar:
    st.header("Fine-tune checks")
    model_label = st.selectbox("Style of check", list(MODEL_CHOICES.keys()))
    selected_model = MODEL_CHOICES[model_label]

    st.markdown(
        """
**Tips for better recommendations**
- Add a short blurb about who you are.
- Mention what you're in the mood for.
- Set how strict you are about clickbait.
"""
    )


def get_thumbnail_url(info: Dict) -> Optional[str]:
    thumb = info.get("thumbnail")
    if thumb:
        return thumb

    video_id = info.get("id")
    if not video_id:
        return None

    base = f"https://img.youtube.com/vi/{video_id}"
    candidates = [
        f"{base}/maxresdefault.jpg",
        f"{base}/hqdefault.jpg",
        f"{base}/mqdefault.jpg",
    ]

    for url in candidates:
        try:
            resp = requests.head(url, timeout=5)
            if resp.status_code < 400:
                return url
        except Exception:
            continue

    return None


def get_video_info(url: str) -> Optional[Dict]:
    try:
        ydl_opts = {"quiet": True, "skip_download": True, "noplaylist": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            info["thumbnail_resolved"] = get_thumbnail_url(info)
            return info
    except Exception as e:
        st.error(f"Could not load video metadata: {e}")
        return None


def get_transcript_text(video_id: str) -> str:
    try:
        transcript = YouTubeTranscriptApi.get_transcript(
            video_id, languages=["en", "en-US", "en-GB"]
        )
        text = " ".join(chunk.get("text", "") for chunk in transcript)
        return text[:12000] if text else ""
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
        return ""
    except Exception:
        return ""


def build_video_context(url: str) -> Optional[Dict]:
    info = get_video_info(url)
    if not info:
        return None

    video_id = info.get("id")
    transcript = get_transcript_text(video_id) if video_id else ""

    if not transcript:
        transcript = info.get("description") or "No transcript or description available."

    duration_seconds = info.get("duration")
    duration_minutes = round(duration_seconds / 60) if duration_seconds else None

    return {
        "title": info.get("title") or "",
        "video_id": video_id,
        "channel": info.get("uploader") or info.get("channel") or "",
        "duration_minutes": duration_minutes,
        "thumbnail_url": info.get("thumbnail_resolved"),
        "transcript": transcript[:12000],
        "description": info.get("description") or "",
        "webpage_url": info.get("webpage_url") or url,
    }


def analyze_video_with_openrouter(
    model: str,
    video_ctx: Dict,
    user_background: str,
    user_interests: str,
    meal_minutes: int,
    clickbait_tolerance: int,
) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Please add it to your environment."
        )

    site_url = os.getenv("OPENROUTER_SITE_URL", "https://clickbait-buster.local")

    system_prompt = (
        "You are a YouTube meal-time recommendation assistant and clickbait auditor.\n"
        "The user is choosing ONE video to watch while eating a meal.\n"
        "You understand modern YouTube marketing tactics and can distinguish playful, "
        "attention-grabbing titles from truly misleading or fraudulent ones.\n"
        "Be concise, practical, and user-focused.\n"
    )

    duration_str = (
        f"{video_ctx['duration_minutes']} minutes"
        if video_ctx.get("duration_minutes") is not None
        else "unknown length"
    )

    user_profile_block = (
        f"User background: {user_background or 'not specified.'}\n"
        f"User current interests: {user_interests or 'not specified.'}\n"
        f"Meal duration (approx): {meal_minutes} minutes.\n"
        f"Clickbait tolerance (1=zero tolerance, 10=okay with wild titles): {clickbait_tolerance}.\n"
    )

    video_block = (
        f"Video title: {video_ctx.get('title')}\n"
        f"Channel: {video_ctx.get('channel') or 'unknown'}\n"
        f"Video length: {duration_str}\n"
        f"Video URL: {video_ctx.get('webpage_url')}\n\n"
        f"Transcript / description (may be truncated):\n"
        f"{video_ctx.get('transcript')}\n"
    )

    instructions = (
        "Using the information above, think through the analysis silently, then respond with:\n"
        "1) A 2–3 sentence summary of what the video is actually about.\n"
        "2) A clickbait score from 1–10 using this rubric:\n"
        "   - 1–3: HONEST – Title is accurate; very little is exaggerated.\n"
        "   - 4–6: EXAGGERATED – Title leans marketing-heavy but content mostly delivers.\n"
        "   - 7–9: MISLEADING – Title omits key info or implies something major that is not there.\n"
        "   - 10: TOTAL FRAUD – Title has almost nothing to do with the actual video.\n"
        "3) 1–2 concrete reasons for your score, referring to specific parts of the title vs content.\n"
        "4) A tailored verdict for THIS user, eating THIS meal, including:\n"
        "   - Whether it's worth their meal-time.\n"
        "   - When it might be worth watching anyway (e.g. certain interests, background, or mood).\n"
        "   - If not ideal, briefly suggest what type of video they should look for instead.\n"
        "Do not show your intermediate reasoning steps. Respond in clear markdown with headings.\n"
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": user_profile_block + "\n\n" + video_block + "\n\n" + instructions,
            },
        ],
        "temperature": 0.4,
        "max_tokens": 800,
    }

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": site_url,
            "X-Title": "Clickbait Buster AI",
        },
        json=payload,
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Unexpected OpenRouter response format: {data}")


st.subheader("1. Drop in your video and context")

with st.form("clickbait_form"):
    youtube_url = st.text_input(
        "YouTube video link",
        placeholder="https://www.youtube.com/watch?v=...",
    )
    col1, col2 = st.columns(2)
    with col1:
        user_background = st.text_area(
            "About you (optional)",
            placeholder="e.g. Software engineer, loves tech and storytelling, hates over-the-top drama.",
            height=100,
        )
    with col2:
        user_interests = st.text_area(
            "What are you in the mood for?",
            placeholder="e.g. light entertainment, educational deep-dive, cooking inspo, chill vlog.",
            height=100,
        )

    meal_minutes = st.slider(
        "How long is your meal?",
        min_value=5,
        max_value=60,
        value=20,
        step=5,
    )

    clickbait_tolerance = st.slider(
        "How much clickbait are you okay with?",
        min_value=1,
        max_value=10,
        value=4,
        help="1 = I only want honest titles. 10 = I'm fine with spicy clickbait if it's fun.",
    )

    submitted = st.form_submit_button("Analyze this video")


if submitted:
    if not youtube_url:
        st.error("Please paste a valid YouTube URL first.")
    else:
        with st.spinner("Fetching video details and transcript..."):
            video_ctx = build_video_context(youtube_url)

        if not video_ctx:
            st.stop()

        left_col, right_col = st.columns([1, 2])

        with left_col:
            if video_ctx.get("thumbnail_url"):
                st.image(
                    video_ctx["thumbnail_url"],
                    caption=video_ctx.get("title", "Video thumbnail"),
                    use_column_width=True,
                )
            st.markdown(f"**Title:** {video_ctx.get('title')}")
            if video_ctx.get("channel"):
                st.markdown(f"**Channel:** {video_ctx['channel']}")
            if video_ctx.get("duration_minutes") is not None:
                st.markdown(f"**Length:** ~{video_ctx['duration_minutes']} min")
            st.markdown(f"[Open on YouTube]({video_ctx.get('webpage_url')})")

        with right_col:
            if not has_api_key():
                st.error(
                    "This app isn’t set up to rate videos yet. "
                    "Ask the person who deployed it to finish configuration."
                )
            else:
                with st.spinner("Checking if this is a good meal-time pick..."):
                    try:
                        analysis = analyze_video_with_openrouter(
                            selected_model,
                            video_ctx,
                            user_background,
                            user_interests,
                            meal_minutes,
                            clickbait_tolerance,
                        )
                        st.subheader("2. Clickbait analysis & meal-time verdict")
                        st.markdown(analysis)
                    except Exception as e:
                        st.error(f"Could not analyze this video: {e}")

