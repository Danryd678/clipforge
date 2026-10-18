# 🎬 ClipForge — Free Video Maker

Script → scenes → free AI visuals → voiceover → captions → finished vertical video.
100% free. No card, no signup, no API keys. Free mode is locked on by design.

## Run locally
```
pip install -r requirements.txt
streamlit run app.py
```

## Deploy free (Streamlit Community Cloud)
1. Create a public GitHub repo (e.g. `Danryd678/clipforge`) and upload
   `app.py`, `videomaker.py`, `requirements.txt`.
2. Go to share.streamlit.io → New app → pick the repo → `app.py` → Deploy.
3. Open the app URL on your phone — nothing to install.

## How the "no errors" design works
- **Provider chain:** free AI images (Pollinations, no key) with retry +
  backoff when the free tier is busy → branded placeholder fallback.
  A video ALWAYS comes out.
- **Voiceover:** edge-tts (Microsoft neural voices, no key) → gTTS fallback.
- **Upload slots:** drop in free clips from Kling / Hailuo / PixVerse / Luma /
  Veo 3 (their free tiers live on their websites) per scene.
- **Validation:** every scene and the final video are checked before the next
  step; bad outputs raise a plain-word error instead of a broken video.
- **Projects:** save/load a project JSON so work is never lost.
- **Never paid:** there are no paid-provider code paths; external providers
  stay disabled unless explicitly opted in.
