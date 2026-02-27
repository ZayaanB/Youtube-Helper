## Clickbait Buster AI – Meal-Time Edition

Problem: You sit down with a plate of food, open YouTube, and suddenly 10 minutes disappear to scrolling instead of eating. The food gets cold, and the “perfect” video never appears.

Clickbait Buster AI helps you decide in seconds whether a video is actually worth your meal-time.

- Paste a YouTube link
- Describe yourself and what you’re in the mood for
- Get an AI-powered clickbait score and a meal-time verdict tuned to your background and interests.

---

## How it works

- Transcript + description aware: The app pulls the video transcript when available (via `youtube-transcript-api`), and falls back to the video description when it is not.
- Robust thumbnail handling: It resolves a reliable thumbnail URL using `yt-dlp` and known YouTube thumbnail patterns so the preview almost always works.
- OpenRouter-powered analysis: Instead of a local model, the app calls OpenRouter’s chat API to rate how clickbaity the title is and whether the content delivers.
- You in the loop: It uses your background, current interests, meal length, and clickbait tolerance to give a verdict tailored to *you* right now.

The model responds with:

- A short summary of the video
- A 1–10 clickbait score using a clear rubric
- Concrete reasons for the score
- A meal-time verdict: should you watch this while eating, or look for something better?

---

## Running the app locally

### 1. Clone and install dependencies


### 2. Configure your environment

You can optionally choose a specific OpenRouter model:

### 3. Run Streamlit

```bash
streamlit run app.py
```

Open the URL that Streamlit prints (usually `http://localhost:8501`).

---

## Using the app to fix meal-time indecision

1. Paste a YouTube link for a video you’re considering.
2. Fill in:
   - About you – e.g. your background, what kind of content you like or dislike.
   - What you’re in the mood for – light entertainment, deep dive, cooking inspo, etc.
   - Meal length – roughly how many minutes you’ll be eating.
   - Clickbait tolerance – whether spicy titles are okay if the content delivers.
3. Hit “Analyze this video”.
4. Skim:
   - The thumbnail, title, channel, and length
   - The clickbait score and explanation
   - The meal-time verdict tailored specifically for you.

If the verdict says the video is a bad fit (for example, too long for your meal, or fake-drama you hate), you just saved 10–20 minutes of frustration.
