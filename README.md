## Youtube Helper - Clickbait and Recommendations

Problem: You sit down with a plate of food, open YouTube, and suddenly 10 minutes disappear to scrolling instead of eating. The food gets cold, and the “perfect” video never appears.

YouTube Helper helps you decide in seconds whether a video is actually worth your mealtime — and, when you don’t have a specific link in mind, it can suggest a handful of options that fit your mood and time box.

- Paste a YouTube link and get a clickbait / meal-time verdict.
- Or, tell it what you’re in the mood for and how long you want to watch, and get a short list of suggested videos.
- In both cases, the verdict is tuned to your background, interests, and how strict you are about clickbait.

---

## How it works

- Transcript + description: The app pulls the video transcript when available (via `youtube-transcript-api`).
- OpenRouter-powered analysis: Instead of a local model, the app calls OpenRouter’s chat API to rate how clickbaity the title is and whether the content delivers.
- Uses the user's background, current interests, meal length, and clickbait tolerance to give a verdict tailored to *the user* right now.
- Recommendation mode: When you don’t have a specific link handy, it uses `yt-dlp`’s search to find a number of videos (specified by the user) that fit your mood and roughly match the desired length.

The model responds with:

Mode 1 (Evaluate video):
- A short summary of the video
- A 1–10 clickbait score using a predefined rubric (found in app.py in prompt)
- Concrete reasons for the score based on the rubric and evidence from the transcript (if applicable)
- A meal-time verdict: should you watch this while eating, or look for something better?

Mode 2 (Find videos):
- Links to #videos defined by the user
- Video titles
- Video durations

---

## Running the app locally

### 1. Install dependencies

From the project root, it’s usually nicest to use a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On some Linux systems, you may also need the Tk GUI toolkit for the window to start:

```bash
sudo apt install python3-tk
```
```

### 2. Configure your environment

Set your OpenRouter API key so the YouTube Helper can ask the model to score videos. You can either:

- Export it directly in your shell:

  ```bash
  export OPENROUTER_API_KEY="sk-or-..."
  ```

### 3. Run the app using an activated venv.


```bash
python app.py
```

By default, this opens a small desktop window with two tabs:

- Analyze video
- Recommendations

---

## Using the app to fix meal-time indecision

### Option 1 – Analyze a specific video

1. Choose “Analyze a specific YouTube video” in the menu.
2. Paste a YouTube link for a video you’re considering.
3. Answer a few short prompts:
   - About you.
   - What are you in the mood for?
   - Meal length – roughly how many minutes you’ll be eating.
   - Clickbait tolerance – whether spicy titles are okay if the content delivers.
4. Skim:
   - The title, channel, length, and URL.
   - The clickbait score and explanation.
   - The meal-time verdict tailored specifically for you.

If the verdict says the video is a bad fit (for example, too long for your meal, or fake drama you hate), you just saved 10–20 minutes of frustration.

### Option 2 – Let it suggest something

1. Choose “Get video recommendations based on your mood”.
2. Describe what you are in the mood for.
3. (Optionally) add a short about yourself so suggestions skew toward the user.
4. Tell it roughly how long each video should be and how many suggestions you’d like.
5. Skim the list of recommended videos (title, channel, length, URL) and pick one that feels right.

You can copy any URL from the recommendation list straight back into the “Analyze a specific YouTube video” flow to get the same clickbait score and meal-time verdict as if you had found the video yourself.
