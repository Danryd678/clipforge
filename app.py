"""ClipForge — free AI video maker. Paste a script, get a finished vertical video."""
import os
import shutil
import tempfile

import streamlit as st

from videomaker import (VOICES, build_video, estimate_narration_seconds,
                        project_from_json, project_to_json,
                        scene_prompt, split_scenes)

st.set_page_config(page_title="ClipForge — Free Video Maker", page_icon="🎬")

st.title("🎬 ClipForge — Free Video Maker")
st.caption("Script → scenes → free AI visuals → voiceover → captions. "
           "100% free, no card, no signup.")
st.success("🟢 **FREE MODE is locked ON** — ClipForge only uses free providers "
           "and will never ask for a card or silently switch to a paid service.")

# ---------------------------------------------------------------- step 1 ---
st.subheader("1️⃣ Your script")
script = st.text_area("Paste your script (one video = one script)",
                      height=200, max_chars=1500,
                      placeholder="Tell your story here...")
voice_label = st.selectbox("Voiceover voice", list(VOICES.keys()), index=0)
max_scenes = st.slider("Max scenes", 2, 10, 6)
visual_mode = st.radio("Visuals for each scene",
                       ["🤖 Free AI images (automatic)",
                        "📤 Upload my own clips/images"])
st.caption("Note: automatic visuals are AI *images* with motion — true AI video "
           "clips come from the free providers below; download and upload them.")

with st.expander("📂 Load a saved project"):
    proj_file = st.file_uploader("ClipForge project JSON", type=["json"])
    if proj_file is not None:
        try:
            p = project_from_json(proj_file.read().decode("utf-8"))
            st.session_state["cf_script"] = p["script"]
            st.session_state["cf_voice"] = p["voice"]
            st.session_state["cf_mode"] = p["visual_mode"]
            st.session_state["cf_scenes"] = p["scenes"]
            st.session_state["cf_prompts"] = {i: pr for i, pr in enumerate(p["prompts"])}
            st.session_state["cf_uploads"] = {}
            st.success("Project loaded — your storyboard is below.")
            st.rerun()
        except Exception as e:
            st.error(f"Could not load that file: {e}")

if st.button("✂️ Split into scenes", type="primary"):
    script = (script or "").strip()
    if not script:
        st.error("Paste a script first.")
        st.stop()
    scenes = split_scenes(script, max_scenes)
    st.session_state["cf_script"] = script
    st.session_state["cf_voice"] = voice_label
    st.session_state["cf_mode"] = visual_mode
    st.session_state["cf_scenes"] = scenes
    st.session_state["cf_prompts"] = {i: scene_prompt(s)
                                      for i, s in enumerate(scenes)}
    st.session_state["cf_uploads"] = {}

# ---------------------------------------------------------------- step 2 ---
scenes = st.session_state.get("cf_scenes")
if scenes:
    st.subheader("2️⃣ Storyboard — check each scene")
    est = estimate_narration_seconds(st.session_state["cf_script"])
    st.caption(f"{len(scenes)} scenes · ~{est}s of narration (estimated) · "
               "edit any image prompt, or it stays automatic.")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("💾 Save project", project_to_json(
            st.session_state["cf_script"], st.session_state["cf_voice"],
            st.session_state["cf_mode"], scenes,
            [st.session_state["cf_prompts"][i] for i in range(len(scenes))]),
            file_name="clipforge-project.json", mime="application/json")
    prompts = st.session_state["cf_prompts"]
    uploads = st.session_state["cf_uploads"]
    ai_mode = st.session_state["cf_mode"].startswith("🤖")

    for i, scene_text in enumerate(scenes):
        with st.expander(f"Scene {i + 1}: {scene_text[:60]}…", expanded=(i == 0)):
            st.write(scene_text)
            if ai_mode:
                prompts[i] = st.text_area(f"Image prompt — scene {i + 1}",
                                          value=prompts[i], key=f"prompt_{i}",
                                          height=80)
            else:
                up = st.file_uploader(
                    f"Clip/image for scene {i + 1} (mp4 or jpg/png)",
                    type=["mp4", "mov", "webm", "jpg", "jpeg", "png"],
                    key=f"up_{i}")
                if up is not None:
                    uploads[i] = up

    if st.button("🎬 Make my video", type="primary"):
        workdir = tempfile.mkdtemp(prefix="clipforge_")
        status = st.empty()
        bar = st.progress(0)

        def progress(msg):
            status.info(msg)

        try:
            # save uploads to disk
            upload_paths = {}
            for i, up in uploads.items():
                if up is not None:
                    p = os.path.join(workdir, f"upload{i:02d}_{up.name}")
                    with open(p, "wb") as f:
                        f.write(up.getbuffer())
                    upload_paths[i] = p

            ordered_prompts = [prompts[i] for i in range(len(scenes))]
            progress("🎙️ Making the voiceover...")
            bar.progress(10)
            proxy = os.environ.get("TTS_PROXY")
            final = build_video(
                st.session_state["cf_script"],
                VOICES[st.session_state["cf_voice"]],
                workdir, scenes, ordered_prompts, upload_paths,
                progress=progress, proxy=proxy)
            bar.progress(100)
            status.success("Done! Your video is ready. 🎉")
            st.video(final)
            with open(final, "rb") as f:
                st.download_button("⬇️ Download video", f,
                                   file_name="clipforge-video.mp4",
                                   mime="video/mp4")
            st.caption("Vertical + under 3 minutes posts as a Short automatically on YouTube.")
        except Exception as e:
            status.error(f"Something went wrong: {e}. Your script is still above — just try again.")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

# ---------------------------------------------------------- free clips guide
with st.expander("🎁 Get free AI video clips from Kling, Hailuo & co."):
    st.write(
        "These sites give you **free AI video clips every day** — no card needed, "
        "just a free email signup:\n\n"
        "• **Kling AI** — ~66 free credits daily (≈5–6 clips/day), the most free video anywhere\n"
        "• **Hailuo AI (MiniMax)** — ~3–5 free clips/day, great faces\n"
        "• **PixVerse** — daily free credits, fast stylized clips\n"
        "• **Luma Dream Machine** — ~30 free clips/month, cinematic moves\n"
        "• **Google Veo 3 (AI Studio)** — rate-limited free clips, no watermark\n\n"
        "Download the clips you like, then choose **📤 Upload my own clips/images** "
        "above and drop them into scenes. Free tiers watermark clips and change "
        "often — check each site's current terms."
    )

st.divider()
st.caption("🔒 ClipForge never touches a paid service. No API keys, no accounts, no charges — by design.")
st.caption("🔍 Transparency: your script text is sent to the free image API and the free "
           "voice API to generate the video — nothing else leaves the app, and nothing is stored.")
