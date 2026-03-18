"""YouTube Helper: clickbait analysis and video recommendations for meal-time."""

import argparse
import logging
import os
import re
import shutil
import threading
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)
import yt_dlp
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

load_dotenv()

APP_NAME = "Youtube Helper - Clickbait and Recommendations"

# --- Config ---
logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def is_valid_youtube_url(url: str) -> bool:
    """Valid YouTube video URL (watch, youtu.be, embed, v/)."""
    if not url or not url.strip():
        return False
    patterns = [
        r"^https?://(www\.)?youtube\.com/watch\?v=[\w-]+",
        r"^https?://(www\.)?youtube\.com/embed/[\w-]+",
        r"^https?://(www\.)?youtube\.com/v/[\w-]+",
        r"^https?://youtu\.be/[\w-]+",
    ]
    return any(re.search(p, url.strip()) for p in patterns)


def has_api_key() -> bool:
    return bool(os.getenv("OPENROUTER_API_KEY"))


MODEL_CHOICES: Dict[str, str] = {
    "Standard check (free)": "meta-llama/llama-3.3-70b-instruct:free",
}

def yt_dlp_options() -> Dict:
    opts: Dict = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 30,
    }

    runtime = os.getenv("YTDLP_JS_RUNTIME")
    if runtime:
        path = shutil.which(runtime)
        opts["js_runtimes"] = {runtime: {"path": path}}
        return opts

    node_path = shutil.which("node")
    if node_path:
        opts["js_runtimes"] = {"node": {"path": node_path}}
        return opts

    deno_path = shutil.which("deno")
    if deno_path:
        opts["js_runtimes"] = {"deno": {"path": deno_path}}
        return opts

    return opts


# --- YouTube data (yt-dlp, transcripts) ---


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
        except (requests.RequestException, OSError) as e:
            logger.debug("Thumbnail fetch failed for %s: %s", url, e)
            continue

    return None


def get_video_info(url: str) -> Optional[Dict]:
    try:
        with yt_dlp.YoutubeDL(yt_dlp_options()) as ydl:
            info = ydl.extract_info(url, download=False)
            info["thumbnail_resolved"] = get_thumbnail_url(info)
            return info
    except Exception as e:
        logger.warning("Failed to fetch video info: %s", e)
        return None


def get_transcript_text(video_id: str) -> str:
    try:
        transcript = YouTubeTranscriptApi.get_transcript(
            video_id, languages=["en", "en-US", "en-GB"]
        )
        text = " ".join(chunk.get("text", "") for chunk in transcript)
        return text[:12000] if text else ""
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
        logger.debug("No transcript for video %s", video_id)
        return ""
    except Exception as e:
        logger.debug("Transcript fetch failed for %s: %s", video_id, e)
        return ""


def build_video_context(url: str) -> Optional[Dict]:
    info = get_video_info(url)
    if not info:
        return None

    video_id = info.get("id")
    transcript = get_transcript_text(video_id) if video_id else ""

    if not transcript:
        transcript = (
            info.get("description") or "No transcript or description available."
        )

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


# --- OpenRouter (clickbait analysis, search enhancement) ---


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

    site_url = os.getenv("OPENROUTER_SITE_URL", "https://youtube-helper.local")

    system_prompt = (
        "You are a YouTube meal-time recommendation assistant and clickbait auditor. "
        "The user is choosing ONE video to watch while eating a meal.\n\n"
        "Your role:\n"
        "- Evaluate whether the title accurately represents the content. "
        "Distinguish playful, attention-grabbing titles from truly misleading ones.\n"
        "- Use the transcript/description as evidence. Do not guess—if the transcript is missing "
        "or minimal, say so and base your score on title vs description only.\n"
        "- Be concise and practical. Output only what the user needs to decide.\n\n"
        "Clickbait rubric (score 1–10):\n"
        "- 1–3 HONEST: Title matches content. Little or no exaggeration.\n"
        "- 4–6 EXAGGERATED: Title is marketing-heavy but content mostly delivers.\n"
        "- 7–9 MISLEADING: Title omits key info or implies something major that isn't there.\n"
        "- 10 TOTAL FRAUD: Title has almost nothing to do with the actual video.\n\n"
        "Output format: Use exactly these markdown headings. Be brief under each.\n"
        "## Summary\n"
        "## Clickbait Score: X/10\n"
        "## Evidence\n"
        "## Meal-Time Verdict\n"
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
        "Analyze the video above. Respond with the four sections exactly as specified in the system prompt.\n"
        "In Evidence: cite specific phrases from the title and compare them to what the transcript says. "
        "If transcript is missing, say 'No transcript available.' and base the score on title vs description.\n"
        "In Meal-Time Verdict: give a clear yes/no for this user's meal, and optionally when it might be "
        "worth watching anyway or what to look for instead. Tailor to their interests and tolerance.\n"
        "Do not show reasoning steps. Output only the final structured response.\n"
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
            "X-Title": APP_NAME,
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


def enhance_search_query_with_ai(
    mood: str,
    about_you: str = "",
    target_minutes: Optional[int] = None,
) -> str:
    """Turns vague mood into a better YouTube search query via AI. Falls back to original if no API key."""
    if not has_api_key():
        return f"{mood} {about_you}".strip() or mood

    api_key = os.getenv("OPENROUTER_API_KEY")
    site_url = os.getenv("OPENROUTER_SITE_URL", "https://youtube-helper.local")

    system_prompt = (
        "You are a YouTube search query optimizer. Your job is to convert a user's "
        "vague mood or description into a short, effective YouTube search query.\n\n"
        "Rules:\n"
        "- Output ONLY the search query (2-6 keywords), nothing else. No quotes, no explanation.\n"
        "- Use terms that perform well on YouTube: specific topics, formats (documentary, vlog, "
        "tutorial, review), and vibes (relaxing, funny, informative).\n"
        "- If the user mentions duration preference, incorporate it (e.g. 'long form', 'short documentary').\n"
        "- Keep it concise. YouTube search works best with focused key phrases.\n"
        "- Do not add extra filler words. Be direct and searchable."
    )

    user_content = f"Mood/description: {mood}"
    if about_you:
        user_content += f"\nUser context (use to refine): {about_you}"
    if target_minutes:
        user_content += f"\nPreferred video length: ~{target_minutes} minutes"
    user_content += "\n\nOutput the optimized YouTube search query:"

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": site_url,
                "X-Title": APP_NAME,
            },
            json={
                "model": MODEL_CHOICES["Standard check (free)"],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.3,
                "max_tokens": 80,
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        enhanced = data["choices"][0]["message"]["content"].strip()
        if enhanced and len(enhanced) < 100:
            enhanced = enhanced.strip('"\'')
            logger.debug("Enhanced search query: %s -> %s", mood, enhanced)
            return enhanced
    except Exception as e:
        logger.debug("Search query enhancement failed, using original: %s", e)
    return f"{mood} {about_you}".strip() or mood


# --- Search ---


def search_youtube_videos(
    query: str,
    max_results: int = 10,
    target_minutes: Optional[int] = None,
    tolerance_minutes: int = 5,
) -> list[Dict]:
    fetch_count = 30 if target_minutes else min(20, max(10, max_results * 2))  # fetch extra since we filter shorts/livestreams
    search_query = f"ytsearch{fetch_count}:{query}"
    with yt_dlp.YoutubeDL(yt_dlp_options()) as ydl:
        info = ydl.extract_info(search_query, download=False)

    entries = info.get("entries") or []
    videos: list[Dict] = []

    for entry in entries:
        if entry is None:
            continue
        if not (entry.get("webpage_url") or entry.get("url")):
            continue
        if entry.get("is_live") or entry.get("was_live"):
            continue
        duration_seconds = entry.get("duration")
        if target_minutes and target_minutes >= 2 and duration_seconds is not None and duration_seconds < 60:
            continue  # skip shorts when user wants longer videos
        duration_minutes = int(round(duration_seconds / 60)) if duration_seconds else None

        videos.append(
            {
                "title": entry.get("title") or "",
                "channel": entry.get("uploader") or entry.get("channel") or "",
                "duration_minutes": duration_minutes,
                "duration_seconds": duration_seconds,
                "url": entry.get("webpage_url") or entry.get("url"),
            }
        )

    if target_minutes is None:
        return videos[:max_results]

    target_seconds = target_minutes * 60
    tolerance_seconds = tolerance_minutes * 60

    within: list[Dict] = []
    unknown: list[Dict] = []

    for video in videos:
        duration_seconds = video.get("duration_seconds")
        if duration_seconds is None:
            unknown.append(video)
            continue

        if abs(duration_seconds - target_seconds) <= tolerance_seconds:
            within.append(video)

    within.sort(key=lambda v: abs(v["duration_seconds"] - target_seconds))
    combined = within + unknown
    return combined[:max_results]


# --- CLI ---


def prompt_int(prompt: str, default: int, min_value: int, max_value: int) -> int:
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("Please enter a whole number.")
            continue
        if value < min_value or value > max_value:
            print(f"Please enter a value between {min_value} and {max_value}.")
            continue
        return value


def choose_model() -> str:
    labels = list(MODEL_CHOICES.keys())
    print("\nAvailable analysis styles:")
    for idx, label in enumerate(labels, start=1):
        print(f"{idx}. {label}")
    choice = prompt_int("Choose a style", 1, 1, len(labels))
    return MODEL_CHOICES[labels[choice - 1]]


def run_single_video_flow() -> None:
    print("\n=== Analyze a specific YouTube video ===\n")
    youtube_url = input("YouTube video link: ").strip()
    if not youtube_url:
        print("You must provide a YouTube URL.")
        return
    if not is_valid_youtube_url(youtube_url):
        print("That doesn't look like a valid YouTube video URL. Please check and try again.")
        return

    user_background = input(
        "About you (optional, e.g. job, preferences): "
    ).strip()
    user_interests = input(
        "What are you in the mood for? (optional): "
    ).strip()
    meal_minutes = prompt_int("How long is your meal (minutes)?", 20, 5, 60)
    clickbait_tolerance = prompt_int(
        "How much clickbait are you okay with? (1–10)", 4, 1, 10
    )

    selected_model = choose_model()

    print("\nFetching video details and transcript...")
    video_ctx = build_video_context(youtube_url)
    if not video_ctx:
        print("Could not load video metadata. Please check the URL and try again.")
        return

    print("\nVideo overview:")
    print(f"Title  : {video_ctx.get('title') or 'Unknown'}")
    if video_ctx.get("channel"):
        print(f"Channel: {video_ctx['channel']}")
    if video_ctx.get("duration_minutes") is not None:
        print(f"Length : ~{video_ctx['duration_minutes']} min")
    print(f"URL    : {video_ctx.get('webpage_url')}")

    if not has_api_key():
        print(
            "\nOPENROUTER_API_KEY is not set. "
            "Set it in your environment to enable analysis."
        )
        return

    print("\nAnalyzing video...")
    try:
        analysis = analyze_video_with_openrouter(
            selected_model,
            video_ctx,
            user_background,
            user_interests,
            meal_minutes,
            clickbait_tolerance,
        )
    except requests.RequestException as exc:
        logger.exception("OpenRouter API request failed")
        print(f"Could not analyze this video (network error): {exc}")
        return
    except (KeyError, ValueError, RuntimeError) as exc:
        logger.exception("OpenRouter response or config error")
        print(f"Could not analyze this video: {exc}")
        return

    print("\n=== Clickbait analysis & meal-time verdict ===\n")
    print(analysis)


def run_recommendation_flow() -> None:
    print("\n=== Get video recommendations based on your mood ===\n")
    mood = input(
        "What are you in the mood for? (topic, vibe, style): "
    ).strip()
    if not mood:
        print("Please describe what you're in the mood for.")
        return

    about_you = input(
        "Tell me a little about you (optional): "
    ).strip()
    target_minutes = prompt_int(
        "Roughly how long should each video be (minutes)?", 20, 3, 120
    )
    max_results = prompt_int(
        "How many suggestions would you like?", 5, 1, 10
    )

    search_query = enhance_search_query_with_ai(mood, about_you, target_minutes)
    print("\nSearching YouTube for matching videos...")
    try:
        videos = search_youtube_videos(
            search_query,
            max_results=max_results,
            target_minutes=target_minutes,
            tolerance_minutes=5,
        )
    except Exception as exc:
        logger.exception("Video search failed")
        print(f"Could not search for videos: {exc}")
        return

    if not videos:
        print(
            "No videos matched your description and length preference. "
            "Try broadening your description or loosening the length requirement."
        )
        return

    print("\nRecommended videos:")
    shown_count = len(videos[:max_results])
    if shown_count < max_results:
        print(f"(Only found {shown_count} close matches within ±5 minutes.)")
    for idx, video in enumerate(videos[:max_results], start=1):
        title = video.get("title") or "Untitled"
        channel = video.get("channel") or ""
        duration = video.get("duration_minutes")
        url = video.get("url") or ""

        print(f"\n{idx}. {title}")
        if channel:
            print(f"   Channel : {channel}")
        if duration is not None:
            print(f"   Length  : ~{duration} min")
        else:
            print("   Length  : unknown")
        print(f"   URL     : {url}")
    print(
        "\nYou can copy any of these URLs and run the "
        "'Analyze a specific YouTube video' option to get a full clickbait check."
    )


def run_cli_menu() -> None:
    print(f"{APP_NAME}")
    print("-" * len(APP_NAME))

    while True:
        print("\nWhat would you like to do?")
        print("1) Analyze a specific YouTube video")
        print("2) Get video recommendations based on your mood")
        print("3) Quit")

        choice = prompt_int("Choose an option", 1, 1, 3)

        if choice == 1:
            run_single_video_flow()
        elif choice == 2:
            run_recommendation_flow()
        else:
            print("Goodbye!")
            break


# --- GUI ---


def launch_gui() -> None:
    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("1080x760")
    root.minsize(960, 680)

    # Modern dark palette (flat, no gradients)
    bg = "#0f0f0f"
    panel_bg = "#1a1a1a"
    card_bg = "#1f1f1f"
    input_bg = "#252525"
    border = "#2e2e2e"
    border_light = "#383838"
    accent = "#ff4444"
    accent_hover = "#ff5555"
    text_main = "#f0f0f0"
    text_muted = "#888888"
    text_dim = "#5a5a5a"

    root.configure(bg=bg)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        logger.debug("Could not set clam theme, using default")

    style.configure(
        "Dark.TFrame",
        background=panel_bg,
    )
    style.configure(
        "Card.TFrame",
        background=card_bg,
    )
    style.configure(
        "Dark.TLabel",
        background=panel_bg,
        foreground=text_main,
        font=("Segoe UI", 10),
    )
    style.configure(
        "Card.TLabel",
        background=card_bg,
        foreground=text_main,
        font=("Segoe UI", 10),
    )
    style.configure(
        "Muted.TLabel",
        background=panel_bg,
        foreground=text_muted,
        font=("Segoe UI", 9),
    )
    style.configure(
        "Dark.TButton",
        background=accent,
        foreground="white",
        padding=(16, 10),
        font=("Segoe UI", 10, "bold"),
    )
    style.map(
        "Dark.TButton",
        background=[("active", accent_hover)],
    )
    style.configure(
        "Dark.TNotebook",
        background=bg,
        borderwidth=0,
    )
    style.configure(
        "Dark.TNotebook.Tab",
        background=panel_bg,
        foreground=text_muted,
        padding=(24, 12),
        font=("Segoe UI", 10),
    )
    style.map(
        "Dark.TNotebook.Tab",
        background=[("selected", bg)],
        foreground=[("selected", text_main)],
    )
    style.configure(
        "Dark.TEntry",
        fieldbackground=input_bg,
        foreground=text_main,
        insertcolor=text_main,
        padding=8,
    )
    style.configure(
        "Dark.TCombobox",
        fieldbackground=input_bg,
        foreground=text_main,
        background=card_bg,
        padding=6,
    )

    # Header with bottom border
    header_frame = tk.Frame(root, bg=panel_bg)
    header_frame.pack(fill="x", padx=0, pady=0)
    header_inner = tk.Frame(header_frame, bg=panel_bg)
    header_inner.pack(fill="x", padx=24, pady=(20, 16))
    sep = tk.Frame(header_frame, bg=border, height=1)
    sep.pack(fill="x")

    title_label = tk.Label(
        header_inner,
        text=APP_NAME,
        bg=panel_bg,
        fg=text_main,
        font=("Segoe UI", 16, "bold"),
    )
    title_label.pack(side="left")

    subtitle_label = tk.Label(
        header_inner,
        text="Pick a video quickly, skip the doom scroll.",
        bg=panel_bg,
        fg=text_muted,
        font=("Segoe UI", 10),
    )
    subtitle_label.pack(side="left", padx=(20, 0))

    notebook = ttk.Notebook(root, style="Dark.TNotebook")
    notebook.pack(fill="both", expand=True, padx=20, pady=20)

    analyze_frame = ttk.Frame(notebook, style="Dark.TFrame")
    recommend_frame = ttk.Frame(notebook, style="Dark.TFrame")
    notebook.add(analyze_frame, text="  Analyze  ")
    notebook.add(recommend_frame, text="  Discover  ")

    analyze_frame.columnconfigure(0, weight=1)
    analyze_frame.columnconfigure(1, weight=2)

    analyze_left = ttk.Frame(analyze_frame, style="Dark.TFrame", padding=(20, 20, 20, 20))
    analyze_left.grid(row=0, column=0, sticky="nsew")

    analyze_right = ttk.Frame(analyze_frame, style="Dark.TFrame", padding=(20, 20, 20, 20))
    analyze_right.grid(row=0, column=1, sticky="nsew")
    analyze_right.rowconfigure(1, weight=1)
    analyze_right.columnconfigure(0, weight=1)

    url_label = ttk.Label(analyze_left, text="YouTube video link", style="Dark.TLabel")
    url_label.grid(row=0, column=0, sticky="w", padx=0, pady=(0, 4))
    url_var = tk.StringVar()
    url_entry = ttk.Entry(analyze_left, textvariable=url_var, width=50, style="Dark.TEntry")
    url_entry.grid(row=1, column=0, sticky="we", padx=0, pady=(0, 12))

    about_label = ttk.Label(
        analyze_left,
        text="About you (optional)",
        style="Dark.TLabel",
    )
    about_label.grid(row=2, column=0, sticky="w", padx=0, pady=(8, 4))
    about_text = tk.Text(
        analyze_left,
        height=3,
        width=42,
        background=input_bg,
        foreground=text_main,
        insertbackground=text_main,
        borderwidth=1,
        relief="flat",
        highlightthickness=1,
        highlightbackground=border,
    )
    about_text.grid(row=3, column=0, sticky="we", padx=0, pady=(0, 12))

    mood_label = ttk.Label(
        analyze_left,
        text="What you're in the mood for",
        style="Dark.TLabel",
    )
    mood_label.grid(row=4, column=0, sticky="w", padx=0, pady=(8, 4))
    mood_text = tk.Text(
        analyze_left,
        height=3,
        width=42,
        background=input_bg,
        foreground=text_main,
        insertbackground=text_main,
        borderwidth=1,
        relief="flat",
        highlightthickness=1,
        highlightbackground=border,
    )
    mood_text.grid(row=5, column=0, sticky="we", padx=0, pady=(0, 12))

    meal_label = ttk.Label(
        analyze_left,
        text="Meal length (minutes):",
        style="Dark.TLabel",
    )
    meal_label.grid(row=6, column=0, sticky="w", padx=0, pady=(8, 4))
    meal_var = tk.IntVar(value=20)
    meal_spin = ttk.Spinbox(
        analyze_left, from_=5, to=60, increment=5, textvariable=meal_var, width=8
    )
    meal_spin.grid(row=7, column=0, sticky="w", padx=0, pady=(0, 12))

    tol_label = ttk.Label(
        analyze_left,
        text="Clickbait tolerance (1 = honest only, 10 = okay with spicy titles):",
        style="Dark.TLabel",
        wraplength=380,
        justify="left",
    )
    tol_label.grid(row=8, column=0, sticky="w", padx=0, pady=(8, 4))
    tol_var = tk.IntVar(value=4)
    tol_spin = ttk.Spinbox(
        analyze_left, from_=1, to=10, increment=1, textvariable=tol_var, width=8
    )
    tol_spin.grid(row=9, column=0, sticky="w", padx=0, pady=(0, 12))

    model_label = ttk.Label(analyze_left, text="Analysis style", style="Dark.TLabel")
    model_label.grid(row=10, column=0, sticky="w", padx=0, pady=(8, 4))
    model_var = tk.StringVar(value=list(MODEL_CHOICES.keys())[0])
    model_combo = ttk.Combobox(
        analyze_left,
        textvariable=model_var,
        values=list(MODEL_CHOICES.keys()),
        state="readonly",
        width=28,
        style="Dark.TCombobox",
    )
    model_combo.grid(row=11, column=0, sticky="we", padx=0, pady=(0, 16))

    analyze_button = ttk.Button(
        analyze_left,
        text="Analyze video",
        style="Dark.TButton",
    )
    analyze_button.grid(row=12, column=0, sticky="we", padx=0, pady=(0, 8))

    hint_label = ttk.Label(
        analyze_left,
        text="Paste a link, add a bit of context, then hit Analyze.",
        style="Muted.TLabel",
        wraplength=380,
        justify="left",
    )
    hint_label.grid(row=13, column=0, sticky="w", padx=0, pady=(0, 4))

    for col in range(1):
        analyze_left.columnconfigure(col, weight=1)

    analysis_title = ttk.Label(
        analyze_right,
        text="Analysis",
        style="Dark.TLabel",
        font=("Segoe UI", 11, "bold"),
    )
    analysis_title.grid(row=0, column=0, sticky="w", padx=0, pady=(0, 8))

    result_box = ScrolledText(
        analyze_right,
        wrap="word",
        height=20,
        background=input_bg,
        foreground=text_main,
        insertbackground=text_main,
        borderwidth=0,
        relief="flat",
        highlightthickness=1,
        highlightbackground=border,
        font=("Segoe UI", 10),
    )
    result_box.grid(row=1, column=0, sticky="nsew", padx=0, pady=(0, 8))
    result_box.insert("1.0", "Paste a YouTube link and click Analyze to see the clickbait score and meal-time verdict here.")
    result_box.configure(fg=text_dim)

    def apply_analyze_results(
        video_ctx: Optional[Dict],
        analysis: Optional[str],
        error: Optional[BaseException],
    ) -> None:
        analyze_button.configure(state="normal")
        if error is not None:
            msg = "Analysis was cancelled." if isinstance(error, KeyboardInterrupt) else str(error)
            messagebox.showerror("Analysis error", f"Could not analyze this video: {msg}")
            result_box.delete("1.0", "end")
            result_box.insert("1.0", "Paste a YouTube link and click Analyze to see the clickbait score and meal-time verdict here.")
            result_box.configure(fg=text_dim)
            return
        if not video_ctx or not analysis:
            messagebox.showerror(
                "Video error",
                "Could not load video metadata. Please check the URL and try again.",
            )
            result_box.delete("1.0", "end")
            result_box.insert("1.0", "Paste a YouTube link and click Analyze to see the clickbait score and meal-time verdict here.")
            result_box.configure(fg=text_dim)
            return
        result_box.delete("1.0", "end")
        result_box.configure(fg=text_main)
        header_lines = [
            f"Title  : {video_ctx.get('title') or 'Unknown'}",
            f"Channel: {video_ctx.get('channel') or 'Unknown'}",
        ]
        if video_ctx.get("duration_minutes") is not None:
            header_lines.append(f"Length : ~{video_ctx['duration_minutes']} min")
        header_lines.append(f"URL    : {video_ctx.get('webpage_url')}")
        result_box.insert("end", "\n".join(header_lines))
        result_box.insert("end", "\n\n=== Clickbait analysis & meal-time verdict ===\n\n")
        result_box.insert("end", analysis)

    def on_analyze_click() -> None:
        url = url_var.get().strip()
        if not url:
            messagebox.showerror("Missing URL", "Please paste a YouTube video link first.")
            return
        if not is_valid_youtube_url(url):
            messagebox.showerror(
                "Invalid URL",
                "That doesn't look like a valid YouTube video URL. Please check and try again.",
            )
            return
        user_background = about_text.get("1.0", "end").strip()
        user_interests = mood_text.get("1.0", "end").strip()
        meal_minutes = meal_var.get()
        clickbait_tolerance = tol_var.get()
        selected_model_label = model_var.get()
        model = MODEL_CHOICES.get(selected_model_label)
        if model is None:
            messagebox.showerror("Model error", "Please choose a valid analysis style.")
            return
        if not has_api_key():
            messagebox.showerror(
                "Configuration",
                "OPENROUTER_API_KEY is not set. Set it in your environment to enable analysis.",
            )
            return

        result_box.delete("1.0", "end")
        result_box.insert("end", "Fetching video details and transcript...\n")
        analyze_button.configure(state="disabled")

        def work() -> None:
            err: Optional[BaseException] = None
            ctx: Optional[Dict] = None
            analysis_text: Optional[str] = None
            try:
                ctx = build_video_context(url)
                if not ctx:
                    root.after(0, lambda: apply_analyze_results(None, None, None))
                    return
                analysis_text = analyze_video_with_openrouter(
                    model,
                    ctx,
                    user_background,
                    user_interests,
                    meal_minutes,
                    clickbait_tolerance,
                )
            except (KeyboardInterrupt, Exception) as e:
                err = e
            root.after(0, lambda: apply_analyze_results(ctx, analysis_text, err))

        threading.Thread(target=work, daemon=True).start()

    analyze_button.configure(command=on_analyze_click)

    recommend_frame.columnconfigure(0, weight=1)
    recommend_frame.columnconfigure(1, weight=2)

    recommend_left = ttk.Frame(recommend_frame, style="Dark.TFrame", padding=(16, 16, 16, 16))
    recommend_left.grid(row=0, column=0, sticky="nsew")

    recommend_right = ttk.Frame(recommend_frame, style="Dark.TFrame", padding=(16, 16, 16, 16))
    recommend_right.grid(row=0, column=1, sticky="nsew")
    recommend_right.rowconfigure(1, weight=1)
    recommend_right.columnconfigure(0, weight=1)

    mood_label2 = ttk.Label(
        recommend_left,
        text="What are you in the mood for?",
        style="Dark.TLabel",
    )
    mood_label2.grid(row=0, column=0, sticky="w", padx=0, pady=(0, 4))
    mood_var2 = tk.StringVar()
    mood_entry2 = ttk.Entry(recommend_left, textvariable=mood_var2, width=50, style="Dark.TEntry")
    mood_entry2.grid(row=1, column=0, sticky="we", padx=0, pady=(0, 12))

    about_label2 = ttk.Label(
        recommend_left,
        text="About you (optional)",
        style="Dark.TLabel",
    )
    about_label2.grid(row=2, column=0, sticky="w", padx=0, pady=(8, 4))
    about_var2 = tk.StringVar()
    about_entry2 = ttk.Entry(recommend_left, textvariable=about_var2, width=50, style="Dark.TEntry")
    about_entry2.grid(row=3, column=0, sticky="we", padx=0, pady=(0, 12))

    target_label = ttk.Label(
        recommend_left,
        text="Target video length (minutes):",
        style="Dark.TLabel",
    )
    target_label.grid(row=4, column=0, sticky="w", padx=0, pady=(8, 4))
    target_var = tk.IntVar(value=20)
    target_spin = ttk.Spinbox(
        recommend_left, from_=3, to=120, increment=1, textvariable=target_var, width=8
    )
    target_spin.grid(row=5, column=0, sticky="w", padx=0, pady=(0, 12))

    count_label = ttk.Label(
        recommend_left,
        text="Number of suggestions:",
        style="Dark.TLabel",
    )
    count_label.grid(row=6, column=0, sticky="w", padx=0, pady=(8, 4))
    count_var = tk.IntVar(value=5)
    count_spin = ttk.Spinbox(
        recommend_left, from_=1, to=10, increment=1, textvariable=count_var, width=8
    )
    count_spin.grid(row=7, column=0, sticky="w", padx=0, pady=(0, 16))

    recommend_button = ttk.Button(
        recommend_left,
        text="Get recommendations",
        style="Dark.TButton",
    )
    recommend_button.grid(row=8, column=0, sticky="we", padx=0, pady=(0, 8))

    hint_label2 = ttk.Label(
        recommend_left,
        text="Describe the vibe and how long you want to watch, then hit Get recommendations.",
        style="Muted.TLabel",
        wraplength=380,
        justify="left",
    )
    hint_label2.grid(row=9, column=0, sticky="w", padx=0, pady=(0, 4))

    for col in range(1):
        recommend_left.columnconfigure(col, weight=1)

    reco_title = ttk.Label(
        recommend_right,
        text="Suggestions",
        style="Dark.TLabel",
        font=("Segoe UI", 11, "bold"),
    )
    reco_title.grid(row=0, column=0, sticky="w", padx=0, pady=(0, 8))

    reco_box = ScrolledText(
        recommend_right,
        wrap="word",
        height=20,
        background=input_bg,
        foreground=text_main,
        insertbackground=text_main,
        borderwidth=0,
        relief="flat",
        highlightthickness=1,
        highlightbackground=border,
        font=("Segoe UI", 10),
    )
    reco_box.grid(row=1, column=0, sticky="nsew", padx=0, pady=(0, 8))
    reco_box.insert("1.0", "Describe what you want to watch and click Get recommendations. Results will appear here.")
    reco_box.configure(fg=text_dim)

    def apply_recommend_results(
        videos: Optional[List[Dict]], error: Optional[BaseException], n: int
    ) -> None:
        recommend_button.configure(state="normal")
        if error is not None:
            msg = "Search was cancelled." if isinstance(error, KeyboardInterrupt) else str(error)
            messagebox.showerror("Search error", f"Could not search for videos: {msg}")
            reco_box.delete("1.0", "end")
            reco_box.insert("1.0", "Describe what you want to watch and click Get recommendations. Results will appear here.")
            reco_box.configure(fg=text_dim)
            return
        reco_box.delete("1.0", "end")
        reco_box.configure(fg=text_main)
        if not videos:
            reco_box.insert(
                "1.0",
                "No videos matched your description and length preference.\n"
                "Try broadening your description or loosening the length requirement.",
            )
            return
        shown_count = len(videos[:n])
        if shown_count < n:
            reco_box.insert(
                "end",
                f"Only found {shown_count} close matches within ±5 minutes. Showing what I could.\n\n",
            )
        for idx, video in enumerate(videos[:n], start=1):
            title = video.get("title") or "Untitled"
            channel = video.get("channel") or ""
            duration = video.get("duration_minutes")
            url = video.get("url") or ""
            reco_box.insert("end", f"{idx}. {title}\n")
            if channel:
                reco_box.insert("end", f"   Channel : {channel}\n")
            if duration is not None:
                reco_box.insert("end", f"   Length  : ~{duration} min\n")
            else:
                reco_box.insert("end", "   Length  : unknown\n")
            reco_box.insert("end", f"   URL     : {url}\n\n")
        reco_box.insert(
            "end",
            "You can copy any of these URLs into the 'Analyze video' tab "
            "to get a full clickbait score and meal-time verdict.\n",
        )

    def on_recommend_click() -> None:
        mood = mood_var2.get().strip()
        if not mood:
            messagebox.showerror(
                "Missing description",
                "Please describe what you're in the mood for.",
            )
            return
        target_minutes = target_var.get()
        max_results = count_var.get()
        about_you = about_var2.get().strip()
        search_query = enhance_search_query_with_ai(mood, about_you, target_minutes)

        reco_box.delete("1.0", "end")
        reco_box.insert("end", "Searching YouTube for matching videos...\n")
        recommend_button.configure(state="disabled")

        def work() -> None:
            err: Optional[BaseException] = None
            out: Optional[List[Dict]] = None
            try:
                out = search_youtube_videos(
                    search_query,
                    max_results=max_results,
                    target_minutes=target_minutes,
                    tolerance_minutes=5,
                )
            except (KeyboardInterrupt, Exception) as e:
                err = e
            root.after(0, lambda: apply_recommend_results(out, err, max_results))

        threading.Thread(target=work, daemon=True).start()

    recommend_button.configure(command=on_recommend_click)

    root.mainloop()


# --- Entry point ---


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="youtube-helper",
        description="YouTube meal-time recommendation assistant and clickbait auditor.",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Use CLI instead of GUI (useful when GUI cannot start)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose (debug) logging",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.1.0",
    )
    args = parser.parse_args()

    _setup_logging(verbose=args.verbose)

    if args.cli:
        run_cli_menu()
        return

    try:
        launch_gui()
    except Exception as e:
        logger.warning("GUI failed to start (%s), falling back to CLI", e)
        run_cli_menu()


if __name__ == "__main__":
    main()
