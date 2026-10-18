"""ClipForge pipeline: script -> scenes -> visuals -> voiceover -> captions -> MP4.

Everything is free by design. There are NO paid-provider code paths in this
file: AI images come from the free Pollinations API (no key), voiceover from
edge-tts with a gTTS fallback (no keys), assembly with a bundled ffmpeg.
If an image download fails, a branded gradient placeholder is used instead,
so a video ALWAYS comes out.
"""
import math
import os
import random
import re
import subprocess
import urllib.parse
import urllib.request

from PIL import Image, ImageDraw, ImageFont

# --- ffmpeg binary (portable) ---
try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG = "ffmpeg"

W, H = 1080, 1920
FPS = 30

VOICES = {
    "Abeo — Nigerian male": "en-NG-AbeoNeural",
    "Ezinne — Nigerian female": "en-NG-EzinneNeural",
    "Ryan — British male": "en-GB-RyanNeural",
    "Sonia — British female": "en-GB-SoniaNeural",
}


# ---------------------------------------------------------------- fonts ---

def _find_font():
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ]:
        if os.path.exists(p):
            return p
    return None


# --------------------------------------------------------------- scenes ---

def split_scenes(script, max_scenes=8):
    """Split a script into scenes (groups of sentences)."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script.strip())
                 if s.strip()]
    if not sentences:
        return []
    n = min(max_scenes, len(sentences))
    scenes, start = [], 0
    for i in range(n):
        # distribute sentences as evenly as possible
        count = (len(sentences) - start) // (n - i)
        scenes.append(" ".join(sentences[start:start + count]))
        start += count
    return scenes


def scene_prompt(scene_text):
    """Turn scene narration into an image prompt."""
    clean = re.sub(r"\s+", " ", scene_text).strip()
    if len(clean) > 220:
        clean = clean[:220].rsplit(" ", 1)[0]
    return (f"Cinematic vertical video still, {clean}, "
            f"dramatic lighting, high detail, no text, no watermark")


# ---------------------------------------------------------------- providers ---
# Provider registry (Manus idea, adapted): every visual/voice source is an
# adapter with an explicit cost flag. EXTERNAL providers are OFF by default
# and can only be enabled by explicit user opt-in — the app NEVER silently
# switches to a paid service, and free mode cannot be turned off.
PROVIDERS = {
    "pollinations_images": {"kind": "visual", "cost": "free",
                             "needs_key": False, "enabled": True},
    "user_uploads": {"kind": "visual", "cost": "free",
                     "needs_key": False, "enabled": True},
    "edge_tts": {"kind": "voice", "cost": "free",
                 "needs_key": False, "enabled": True},
    "gtts": {"kind": "voice", "cost": "free",
             "needs_key": False, "enabled": True},
    # External AI-video providers (Kling, Hailuo, ...) offer free clips on
    # their WEBSITES only — no free API. Slots for them stay disabled until
    # the user explicitly opts in with their own key. Not free => not used.
}
FREE_MODE_LOCKED = True


def _validate_media(path, what):
    """Validate an output before the pipeline moves on (Manus rule)."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        raise RuntimeError(f"{what} came out empty — retrying just this step.")
    if get_duration(path) <= 0 and what.startswith("Scene"):
        raise RuntimeError(f"{what} is not a valid video — retrying.")


# ---------------------------------------------------------------- images ---

def fetch_free_image(prompt, out_path, seed, timeout=90):
    """Free AI image via Pollinations (no key, no signup).

    The free tier rate-limits under load (HTTP 503 "at its limit, retry
    after 10s"), so we back off and retry before giving up — the caller
    then falls back to a branded placeholder so the video still builds.
    """
    import time
    q = urllib.parse.quote(prompt)
    url = (f"https://image.pollinations.ai/prompt/{q}"
           f"?width=1080&height=1920&nologo=true&seed={seed}")
    last_err = "unknown"
    for attempt, wait in enumerate([0, 12, 25]):
        if wait:
            time.sleep(wait)
        try:
            req = urllib.request.Request(url,
                                         headers={"User-Agent": "ClipForge/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                ctype = r.headers.get("Content-Type", "")
                data = r.read()
            if not ctype.startswith("image/") or len(data) < 5000:
                last_err = f"bad response ({ctype}, {len(data)}b)"
                continue
            with open(out_path, "wb") as f:
                f.write(data)
            with Image.open(out_path) as im:  # validate real image
                im.verify()
            return
        except Exception as e:
            last_err = str(e)[:120]
            print(f"image fetch attempt {attempt + 1} failed: {last_err}")
    raise RuntimeError(f"free image API busy: {last_err}")


def placeholder_image(out_path, label="ClipForge"):
    """Branded gradient fallback — used only if the free image API fails."""
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    top = (13, 60, 74)      # dark teal
    bottom = (88, 40, 140)  # purple
    for y in range(H):
        t = y / H
        draw.line([(0, y), (W, y)],
                  fill=(int(top[0] + (bottom[0] - top[0]) * t),
                        int(top[1] + (bottom[1] - top[1]) * t),
                        int(top[2] + (bottom[2] - top[2]) * t)))
    font_path = _find_font()
    if font_path:
        font = ImageFont.truetype(font_path, 64)
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((W - tw) / 2, H // 2), label, font=font,
                  fill="white", stroke_width=3, stroke_fill="black")
    img.save(out_path, "JPEG", quality=88)


def get_visual_for_scene(i, prompt, workdir, uploaded_path=None):
    """Return a local image/video path for scene i. Never raises."""
    if uploaded_path and os.path.exists(uploaded_path):
        return uploaded_path
    img_path = os.path.join(workdir, f"scene{i:02d}.jpg")
    try:
        fetch_free_image(prompt, img_path, seed=random.randint(1, 999999))
        return img_path
    except Exception as e:
        print(f"scene {i} free image unavailable ({e}); using placeholder")
    placeholder_image(img_path, f"Scene {i + 1}")
    return img_path


# -------------------------------------------------------------- voiceover ---

def make_voiceover_edge(script, voice_id, out_mp3, proxy=None):
    """Edge TTS with real word-boundary timings. Returns [(start, end, word)]."""
    import asyncio
    import edge_tts

    async def _run():
        comm = edge_tts.Communicate(script, voice_id, proxy=proxy)
        words = []
        with open(out_mp3, "wb") as f:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    words.append((
                        chunk["offset"] / 10_000_000,
                        (chunk["offset"] + chunk["duration"]) / 10_000_000,
                        chunk["text"],
                    ))
        return words

    return asyncio.run(_run())


def make_voiceover_gtts(script, out_mp3):
    """gTTS fallback. Returns [(start, end, word)] with evenly spread timings."""
    from gtts import gTTS

    gTTS(script, lang="en", tld="com.ng").save(out_mp3)
    dur = get_duration(out_mp3)
    words = script.split()
    per = dur / max(len(words), 1)
    return [(i * per, (i + 1) * per, w) for i, w in enumerate(words)]


def make_voiceover(script, voice_id, out_mp3, proxy=None):
    """Try Edge TTS, fall back to gTTS. Returns word timings."""
    try:
        words = make_voiceover_edge(script, voice_id, out_mp3, proxy=proxy)
        if words and os.path.getsize(out_mp3) > 1000:
            return words
    except Exception as e:
        print("edge-tts failed, falling back to gTTS:", e)
    return make_voiceover_gtts(script, out_mp3)


def get_duration(path):
    """Duration via ffmpeg -i stderr parse (works with static binary)."""
    out = subprocess.run([FFMPEG, "-i", path], capture_output=True, text=True)
    for line in out.stderr.splitlines():
        if "Duration:" in line:
            parts = line.split("Duration:")[1].split(",")[0].strip().split(":")
            try:
                h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
                return h * 3600 + m * 60 + s
            except Exception:
                pass
    return 0.0


def chunk_words(words, max_words=4):
    """Group word timings into caption chunks."""
    chunks, cur = [], []
    for start, end, w in words:
        cur.append((start, end, w))
        if len(cur) >= max_words or w.rstrip().endswith((".", "!", "?", ",")):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return [(c[0][0], c[-1][1], " ".join(w for _, _, w in c)) for c in chunks]


def render_caption_png(text, path, font_path):
    img = Image.new("RGBA", (W, 520), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, 72)
    words, lines, line = text.split(), [], ""
    for w in words:
        if len(line) + len(w) + 1 <= 18:
            line = (line + " " + w).strip()
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    y = 20
    for ln in lines:
        bbox = draw.textbbox((0, 0), ln, font=font, stroke_width=4)
        tw = bbox[2] - bbox[0]
        draw.text(((W - tw) / 2, y), ln, font=font, fill="white",
                  stroke_width=4, stroke_fill="black")
        y += (bbox[3] - bbox[1]) + 14
    img.save(path)


# ------------------------------------------------------- project helpers ---
# Manus ideas, web-sized: pre-flight estimate before generation, and a
# portable project file so work is never lost (save after each step).

def estimate_narration_seconds(script):
    """Rough TTS duration estimate (~850 chars/min for English)."""
    return max(3, int(len(script) / 850 * 60))


def project_to_json(script, voice_label, visual_mode, scenes, prompts):
    import json
    return json.dumps({
        "app": "clipforge", "version": 1,
        "script": script, "voice": voice_label, "visual_mode": visual_mode,
        "scenes": scenes, "prompts": prompts,
    })


def project_from_json(data):
    import json
    p = json.loads(data)
    if p.get("app") != "clipforge":
        raise ValueError("not a ClipForge project file")
    return p


# ----------------------------------------------------------------- video ---

def _is_video_file(path):
    return path.lower().endswith((".mp4", ".mov", ".webm", ".mkv", ".3gp"))


def kenburns_segment(image_path, duration, out_path, zoom_in=True):
    frames = max(int(duration * FPS), 1)
    z_expr = f"1+0.12*on/{frames}" if zoom_in else f"1.12-0.12*on/{frames}"
    vf = (
        "scale=2160:3840:force_original_aspect_ratio=increase,"
        "crop=2160:3840,"
        f"zoompan=z='{z_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={W}x{H}:fps={FPS}"
    )
    subprocess.run(
        [FFMPEG, "-y", "-i", image_path, "-vf", vf, "-frames:v", str(frames),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
         out_path],
        check=True, capture_output=True,
    )


def clip_segment(video_path, duration, out_path):
    """Fit an uploaded video clip to a scene: crop to vertical, trim."""
    vf = ("scale=1080:1920:force_original_aspect_ratio=increase,"
          "crop=1080:1920")
    subprocess.run(
        [FFMPEG, "-y", "-i", video_path, "-vf", vf, "-t", f"{duration:.2f}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
         "-an", out_path],
        check=True, capture_output=True,
    )


def build_video(script, voice_id, workdir, scenes, prompts, uploads,
                progress=None, proxy=None):
    """Full build. scenes: list of scene texts; prompts: image prompt per
    scene; uploads: dict scene_index -> local file path (or None)."""
    os.makedirs(workdir, exist_ok=True)
    audio_path = os.path.join(workdir, "voice.mp3")

    if progress:
        progress("🎙️ Making the voiceover...")
    words = make_voiceover(script, voice_id, audio_path, proxy=proxy)
    duration = get_duration(audio_path)
    if duration <= 0:
        raise RuntimeError("Voiceover came out empty — try again.")

    # split the narration time across scenes by word count
    weights = [max(len(s.split()), 1) for s in scenes]
    total_w = sum(weights)
    scene_durs = [duration * w / total_w for w in weights]

    seg_paths = []
    for i, (scene_text, dur) in enumerate(zip(scenes, scene_durs)):
        if progress:
            progress(f"🎬 Scene {i + 1}/{len(scenes)}...")
        visual = get_visual_for_scene(i, prompts[i], workdir,
                                      uploaded_path=uploads.get(i))
        seg = os.path.join(workdir, f"seg{i:02d}.mp4")
        if _is_video_file(visual):
            clip_segment(visual, dur, seg)
        else:
            kenburns_segment(visual, dur, seg, zoom_in=(i % 2 == 0))
        _validate_media(seg, f"Scene {i + 1}")  # never build on a bad scene
        seg_paths.append(seg)

    list_path = os.path.join(workdir, "list.txt")
    with open(list_path, "w") as f:
        for s in seg_paths:
            f.write(f"file '{s}'\n")
    silent = os.path.join(workdir, "silent.mp4")
    subprocess.run(
        [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", list_path,
         "-c", "copy", silent],
        check=True, capture_output=True,
    )

    if progress:
        progress("💬 Adding captions...")
    font_path = _find_font()
    chunks = chunk_words(words)
    overlay_inputs, fc_parts = [], []
    prev = "0:v"
    for i, (cs, ce, text) in enumerate(chunks):
        if not font_path:
            break
        cap = os.path.join(workdir, f"cap{i:02d}.png")
        render_caption_png(text, cap, font_path)
        overlay_inputs += ["-i", cap]
        idx = i + 1
        out_label = f"[v{i}]" if i < len(chunks) - 1 else "[vout]"
        fc_parts.append(
            f"[{prev}][{idx}:v]overlay=0:1180:"
            f"enable='between(t,{cs:.2f},{ce:.2f})'{out_label}"
        )
        prev = f"v{i}"

    final = os.path.join(workdir, "final.mp4")
    if overlay_inputs:
        fc = ";".join(fc_parts)
        num_caps = len(overlay_inputs) // 2
        cmd = ([FFMPEG, "-y", "-i", silent] + overlay_inputs +
               ["-i", audio_path, "-filter_complex", fc,
                "-map", "[vout]", "-map", f"{1 + num_caps}:a",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
                "-c:a", "aac", "-shortest", final])
    else:
        cmd = ([FFMPEG, "-y", "-i", silent, "-i", audio_path,
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
                "-c:a", "aac", "-shortest", final])
    if progress:
        progress("✨ Assembling your video...")
    subprocess.run(cmd, check=True, capture_output=True)
    _validate_media(final, "Final video")
    return final
