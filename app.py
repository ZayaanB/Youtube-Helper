import os
import shutil
import sys
from typing import Dict, Optional

import requests
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


APP_NAME = "Youtube Helper - Clickbait and Reccomendations"


def has_api_key() -> bool:
    return bool(os.getenv("OPENROUTER_API_KEY"))


MODEL_CHOICES: Dict[str, str] = {
    "Standard check (recommended)": "meta-llama/llama-3.3-70b-instruct:free",
    "Quick check": "openai/gpt-4.1-mini",
}

def yt_dlp_options() -> Dict:
    opts: Dict = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
    }

    runtime = os.getenv("YTDLP_JS_RUNTIME")
    if runtime:
        opts["js_runtimes"] = runtime
        return opts

    if shutil.which("node"):
        opts["js_runtimes"] = "node"
        return opts

    if shutil.which("deno"):
        opts["js_runtimes"] = "deno"
        return opts

    return opts


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
        with yt_dlp.YoutubeDL(yt_dlp_options()) as ydl:
            info = ydl.extract_info(url, download=False)
            info["thumbnail_resolved"] = get_thumbnail_url(info)
            return info
    except Exception:
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


def search_youtube_videos(
    query: str,
    max_results: int = 10,
    target_minutes: Optional[int] = None,
    tolerance_minutes: int = 5,
) -> list[Dict]:
    search_query = f"ytsearch{max_results}:{query}"
    with yt_dlp.YoutubeDL(yt_dlp_options()) as ydl:
        info = ydl.extract_info(search_query, download=False)

    entries = info.get("entries") or []
    videos: list[Dict] = []

    for entry in entries:
        duration_seconds = entry.get("duration")
        duration_minutes = None
        if duration_seconds:
            duration_minutes = int(round(duration_seconds / 60))

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
        return videos

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
    return within + unknown


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
    except Exception as exc:
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

    user_background = input(
        "Tell me a little about you (optional): "
    ).strip()
    target_minutes = prompt_int(
        "Roughly how long should each video be (minutes)?", 20, 3, 120
    )
    max_results = prompt_int(
        "How many suggestions would you like?", 5, 1, 10
    )

    if user_background:
        search_query = f"{mood} for {user_background}"
    else:
        search_query = mood

    print("\nSearching YouTube for matching videos...")
    try:
        search_pool = max(30, max_results * 20)
        if search_pool > 80:
            search_pool = 80
        videos = search_youtube_videos(
            search_query,
            max_results=search_pool,
            target_minutes=target_minutes,
            tolerance_minutes=5,
        )
    except Exception as exc:
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


def launch_gui() -> None:
    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("1000x720")
    root.minsize(900, 640)

    bg = "#111111"
    panel_bg = "#181818"
    accent = "#3b82f6"
    text_main = "#f5f5f5"
    text_muted = "#c4c4c4"

    root.configure(bg=bg)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(
        "Dark.TFrame",
        background=panel_bg,
    )
    style.configure(
        "Dark.TLabel",
        background=panel_bg,
        foreground=text_main,
    )
    style.configure(
        "Muted.TLabel",
        background=panel_bg,
        foreground=text_muted,
    )
    style.configure(
        "Dark.TButton",
        background=accent,
        foreground=text_main,
        padding=6,
    )
    style.map(
        "Dark.TButton",
        background=[("active", "#2563eb")],
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
        padding=(16, 8),
    )
    style.map(
        "Dark.TNotebook.Tab",
        background=[("selected", bg)],
        foreground=[("selected", text_main)],
    )

    header_frame = ttk.Frame(root, style="Dark.TFrame")
    header_frame.pack(fill="x", padx=12, pady=(10, 0))

    title_label = ttk.Label(
        header_frame,
        text=APP_NAME,
        style="Dark.TLabel",
        font=("Segoe UI", 16, "bold"),
    )
    title_label.pack(side="left")

    subtitle_label = ttk.Label(
        header_frame,
        text="Pick a video quickly, skip the meal-time doom scroll.",
        style="Muted.TLabel",
        font=("Segoe UI", 10),
    )
    subtitle_label.pack(side="left", padx=(12, 0))

    notebook = ttk.Notebook(root, style="Dark.TNotebook")
    notebook.pack(fill="both", expand=True, padx=12, pady=12)

    analyze_frame = ttk.Frame(notebook, style="Dark.TFrame")
    recommend_frame = ttk.Frame(notebook, style="Dark.TFrame")
    notebook.add(analyze_frame, text="Analyze video")
    notebook.add(recommend_frame, text="Recommendations")

    analyze_frame.columnconfigure(0, weight=1)
    analyze_frame.columnconfigure(1, weight=2)

    analyze_left = ttk.Frame(analyze_frame, style="Dark.TFrame", padding=(8, 8, 8, 8))
    analyze_left.grid(row=0, column=0, sticky="nsew")

    analyze_right = ttk.Frame(analyze_frame, style="Dark.TFrame", padding=(8, 8, 8, 8))
    analyze_right.grid(row=0, column=1, sticky="nsew")
    analyze_right.rowconfigure(1, weight=1)
    analyze_right.columnconfigure(0, weight=1)

    url_label = ttk.Label(analyze_left, text="YouTube video link", style="Dark.TLabel")
    url_label.grid(row=0, column=0, sticky="w", padx=5, pady=(0, 2))
    url_var = tk.StringVar()
    url_entry = ttk.Entry(analyze_left, textvariable=url_var, width=60)
    url_entry.grid(row=1, column=0, sticky="we", padx=5, pady=(0, 8))

    about_label = ttk.Label(
        analyze_left,
        text="About you (optional)",
        style="Dark.TLabel",
    )
    about_label.grid(row=2, column=0, sticky="w", padx=5, pady=(4, 2))
    about_text = tk.Text(
        analyze_left,
        height=4,
        width=40,
        background=bg,
        foreground=text_main,
        insertbackground=text_main,
        borderwidth=1,
        relief="solid",
    )
    about_text.grid(row=3, column=0, sticky="we", padx=5, pady=(0, 8))

    mood_label = ttk.Label(
        analyze_left,
        text="What you're in the mood for",
        style="Dark.TLabel",
    )
    mood_label.grid(row=4, column=0, sticky="w", padx=5, pady=(4, 2))
    mood_text = tk.Text(
        analyze_left,
        height=4,
        width=40,
        background=bg,
        foreground=text_main,
        insertbackground=text_main,
        borderwidth=1,
        relief="solid",
    )
    mood_text.grid(row=5, column=0, sticky="we", padx=5, pady=(0, 8))

    meal_label = ttk.Label(
        analyze_left,
        text="Meal length (minutes):",
        style="Dark.TLabel",
    )
    meal_label.grid(row=6, column=0, sticky="w", padx=5, pady=(4, 2))
    meal_var = tk.IntVar(value=20)
    meal_spin = ttk.Spinbox(
        analyze_left, from_=5, to=60, increment=5, textvariable=meal_var, width=6
    )
    meal_spin.grid(row=7, column=0, sticky="w", padx=5, pady=(0, 4))

    tol_label = ttk.Label(
        analyze_left,
        text="Clickbait tolerance (1 = honest only, 10 = okay with spicy titles):",
        style="Dark.TLabel",
        wraplength=420,
        justify="left",
    )
    tol_label.grid(row=8, column=0, sticky="w", padx=5, pady=(6, 2))
    tol_var = tk.IntVar(value=4)
    tol_spin = ttk.Spinbox(
        analyze_left, from_=1, to=10, increment=1, textvariable=tol_var, width=6
    )
    tol_spin.grid(row=9, column=0, sticky="w", padx=5, pady=(0, 8))

    model_label = ttk.Label(analyze_left, text="Analysis style", style="Dark.TLabel")
    model_label.grid(row=10, column=0, sticky="w", padx=5, pady=(4, 2))
    model_var = tk.StringVar(value=list(MODEL_CHOICES.keys())[0])
    model_combo = ttk.Combobox(
        analyze_left,
        textvariable=model_var,
        values=list(MODEL_CHOICES.keys()),
        state="readonly",
        width=30,
    )
    model_combo.grid(row=11, column=0, sticky="we", padx=5, pady=(0, 10))

    analyze_button = ttk.Button(
        analyze_left,
        text="Analyze video",
        style="Dark.TButton",
    )
    analyze_button.grid(row=12, column=0, sticky="we", padx=5, pady=(0, 4))

    hint_label = ttk.Label(
        analyze_left,
        text="Paste a link, add a bit of context, then hit Analyze.",
        style="Muted.TLabel",
        wraplength=360,
        justify="left",
    )
    hint_label.grid(row=13, column=0, sticky="w", padx=5, pady=(0, 4))

    for col in range(1):
        analyze_left.columnconfigure(col, weight=1)

    analysis_title = ttk.Label(
        analyze_right,
        text="Analysis",
        style="Dark.TLabel",
        font=("Segoe UI", 11, "bold"),
    )
    analysis_title.grid(row=0, column=0, sticky="w", padx=5, pady=(0, 4))

    result_box = ScrolledText(
        analyze_right,
        wrap="word",
        height=20,
        background=bg,
        foreground=text_main,
        insertbackground=text_main,
        borderwidth=1,
        relief="solid",
    )
    result_box.grid(row=1, column=0, sticky="nsew", padx=5, pady=(0, 5))

    def on_analyze_click() -> None:
        url = url_var.get().strip()
        if not url:
            messagebox.showerror("Missing URL", "Please paste a YouTube video link first.")
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

        result_box.delete("1.0", "end")
        result_box.insert("end", "Fetching video details and transcript...\n")
        root.update_idletasks()

        video_ctx = build_video_context(url)
        if not video_ctx:
            messagebox.showerror(
                "Video error",
                "Could not load video metadata. Please check the URL and try again.",
            )
            return

        if not has_api_key():
            messagebox.showerror(
                "Configuration",
                "OPENROUTER_API_KEY is not set. Set it in your environment to enable analysis.",
            )
            return

        result_box.insert("end", "\nAnalyzing video...\n")
        root.update_idletasks()

        try:
            analysis = analyze_video_with_openrouter(
                model,
                video_ctx,
                user_background,
                user_interests,
                meal_minutes,
                clickbait_tolerance,
            )
        except Exception as exc:
            messagebox.showerror("Analysis error", f"Could not analyze this video: {exc}")
            return

        result_box.delete("1.0", "end")
        header_lines = [
            f"Title  : {video_ctx.get('title') or 'Unknown'}",
            f"Channel: {video_ctx.get('channel') or 'Unknown'}",
        ]
        if video_ctx.get("duration_minutes") is not None:
            header_lines.append(
                f"Length : ~{video_ctx['duration_minutes']} min",
            )
        header_lines.append(f"URL    : {video_ctx.get('webpage_url')}")
        result_box.insert("end", "\n".join(header_lines))
        result_box.insert("end", "\n\n=== Clickbait analysis & meal-time verdict ===\n\n")
        result_box.insert("end", analysis)

    analyze_button.configure(command=on_analyze_click)

    recommend_frame.columnconfigure(0, weight=1)
    recommend_frame.columnconfigure(1, weight=2)

    recommend_left = ttk.Frame(recommend_frame, style="Dark.TFrame", padding=(8, 8, 8, 8))
    recommend_left.grid(row=0, column=0, sticky="nsew")

    recommend_right = ttk.Frame(recommend_frame, style="Dark.TFrame", padding=(8, 8, 8, 8))
    recommend_right.grid(row=0, column=1, sticky="nsew")
    recommend_right.rowconfigure(1, weight=1)
    recommend_right.columnconfigure(0, weight=1)

    mood_label2 = ttk.Label(
        recommend_left,
        text="What are you in the mood for?",
        style="Dark.TLabel",
    )
    mood_label2.grid(row=0, column=0, sticky="w", padx=5, pady=(0, 2))
    mood_var2 = tk.StringVar()
    mood_entry2 = ttk.Entry(recommend_left, textvariable=mood_var2, width=60)
    mood_entry2.grid(row=1, column=0, sticky="we", padx=5, pady=(0, 8))

    about_label2 = ttk.Label(
        recommend_left,
        text="About you (optional):",
        style="Dark.TLabel",
    )
    about_label2.grid(row=2, column=0, sticky="w", padx=5, pady=(4, 2))
    about_var2 = tk.StringVar()
    about_entry2 = ttk.Entry(recommend_left, textvariable=about_var2, width=60)
    about_entry2.grid(row=3, column=0, sticky="we", padx=5, pady=(0, 8))

    target_label = ttk.Label(
        recommend_left,
        text="Target video length (minutes):",
        style="Dark.TLabel",
    )
    target_label.grid(row=4, column=0, sticky="w", padx=5, pady=(4, 2))
    target_var = tk.IntVar(value=20)
    target_spin = ttk.Spinbox(
        recommend_left, from_=3, to=120, increment=1, textvariable=target_var, width=6
    )
    target_spin.grid(row=5, column=0, sticky="w", padx=5, pady=(0, 4))

    count_label = ttk.Label(
        recommend_left,
        text="Number of suggestions:",
        style="Dark.TLabel",
    )
    count_label.grid(row=6, column=0, sticky="w", padx=5, pady=(4, 2))
    count_var = tk.IntVar(value=5)
    count_spin = ttk.Spinbox(
        recommend_left, from_=1, to=10, increment=1, textvariable=count_var, width=6
    )
    count_spin.grid(row=7, column=0, sticky="w", padx=5, pady=(0, 8))

    recommend_button = ttk.Button(
        recommend_left,
        text="Get recommendations",
        style="Dark.TButton",
    )
    recommend_button.grid(row=8, column=0, sticky="we", padx=5, pady=(0, 4))

    hint_label2 = ttk.Label(
        recommend_left,
        text="Describe the vibe and how long you want to watch, then hit Get recommendations.",
        style="Muted.TLabel",
        wraplength=360,
        justify="left",
    )
    hint_label2.grid(row=9, column=0, sticky="w", padx=5, pady=(0, 4))

    for col in range(1):
        recommend_left.columnconfigure(col, weight=1)

    reco_title = ttk.Label(
        recommend_right,
        text="Suggestions",
        style="Dark.TLabel",
        font=("Segoe UI", 11, "bold"),
    )
    reco_title.grid(row=0, column=0, sticky="w", padx=5, pady=(0, 4))

    reco_box = ScrolledText(
        recommend_right,
        wrap="word",
        height=20,
        background=bg,
        foreground=text_main,
        insertbackground=text_main,
        borderwidth=1,
        relief="solid",
    )
    reco_box.grid(row=1, column=0, sticky="nsew", padx=5, pady=(0, 5))

    def on_recommend_click() -> None:
        mood = mood_var2.get().strip()
        if not mood:
            messagebox.showerror(
                "Missing description",
                "Please describe what you're in the mood for.",
            )
            return

        user_background = about_var2.get().strip()
        target_minutes = target_var.get()
        max_results = count_var.get()

        if user_background:
            search_query = f"{mood} for {user_background}"
        else:
            search_query = mood

        reco_box.delete("1.0", "end")
        reco_box.insert("end", "Searching YouTube for matching videos...\n")
        root.update_idletasks()

        try:
            search_pool = max(30, max_results * 20)
            if search_pool > 80:
                search_pool = 80
            videos = search_youtube_videos(
                search_query,
                max_results=search_pool,
                target_minutes=target_minutes,
                tolerance_minutes=5,
            )
        except Exception as exc:
            messagebox.showerror("Search error", f"Could not search for videos: {exc}")
            return

        if not videos:
            reco_box.insert(
                "end",
                "No videos matched your description and length preference.\n"
                "Try broadening your description or loosening the length requirement.",
            )
            return

        reco_box.delete("1.0", "end")
        shown_count = len(videos[:max_results])
        if shown_count < max_results:
            reco_box.insert(
                "end",
                f"Only found {shown_count} close matches within ±5 minutes. Showing what I could.\n\n",
            )
        for idx, video in enumerate(videos[:max_results], start=1):
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

    recommend_button.configure(command=on_recommend_click)

    root.mainloop()


def main() -> None:
    if "--cli" in sys.argv:
        run_cli_menu()
        return

    try:
        launch_gui()
    except Exception:
        run_cli_menu()


if __name__ == "__main__":
    main()
