## Youtube Helper - Clickbait and Recommendations

Problem: You sit down with a plate of food, open YouTube, and suddenly 10 minutes disappear to scrolling instead of eating. The food gets cold, and the "perfect" video never appears.

YouTube Helper helps you decide in seconds whether a video is actually worth your mealtime. When you don't have a specific link in mind, it can suggest a handful of options that fit your mood and time box.

- Paste a YouTube link and get a clickbait / meal-time verdict.
- Or tell it what you're in the mood for and how long you want to watch, and get a short list of suggested videos.
- In both cases, the verdict is tuned to your background, interests, and how strict you are about clickbait.

## How it works

- Transcript + description: The app pulls the video transcript when available (via `youtube-transcript-api`).
- OpenRouter-powered analysis: Instead of a local model, the app calls OpenRouter's chat API to rate how clickbaity the title is and whether the content delivers.
- Uses your background, current interests, meal length, and clickbait tolerance to give a verdict tailored to you right now.
- Recommendation mode: When you don't have a specific link handy, it uses `yt-dlp`'s search to find videos that fit your mood and roughly match the desired length.

Mode 1 (Evaluate video):
- A short summary of the video
- A 1–10 clickbait score using a predefined rubric (found in app.py in prompt)
- Concrete reasons for the score based on the rubric and evidence from the transcript (if applicable)
- A meal-time verdict: should you watch this while eating, or look for something better?

Mode 2 (Find videos):
- Links to videos (number defined by you)
- Video titles
- Video durations

## Running the app locally

1. Install dependencies. From the project root, use a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Linux you may need the Tk GUI toolkit:

```bash
sudo apt install python3-tk
```

2. Set your OpenRouter API key so the app can score videos. Copy `.env.example` to `.env` and add your key, or export it in your shell:

```bash
cp .env.example .env
# Edit .env and set OPENROUTER_API_KEY=sk-or-...
```

or

```bash
export OPENROUTER_API_KEY="sk-or-..."
```

3. Run the app:

```bash
python app.py
```

That opens a desktop window with two tabs: Analyze video and Recommendations.

For the terminal menu instead of the GUI:

```bash
python app.py --cli
```

Other flags: `--verbose` / `-v` for debug output, `--version` to print version.

## Using the app

### Analyze a specific video

1. Choose "Analyze a specific YouTube video" in the menu.
2. Paste a YouTube link for a video you're considering.
3. Answer a few short prompts: about you, what you're in the mood for, meal length, clickbait tolerance.
4. Skim the title, channel, length, clickbait score, and meal-time verdict.

If the verdict says the video is a bad fit (too long for your meal, or fake drama you hate), you just saved 10–20 minutes of frustration.

### Let it suggest something

1. Choose "Get video recommendations based on your mood".
2. Describe what you're in the mood for.
3. Optionally add a short about yourself so suggestions skew toward you.
4. Tell it roughly how long each video should be and how many suggestions you want.
5. Skim the list and pick one that feels right.

You can copy any URL from the recommendation list back into the "Analyze a specific YouTube video" flow to get the same clickbait score and meal-time verdict.
