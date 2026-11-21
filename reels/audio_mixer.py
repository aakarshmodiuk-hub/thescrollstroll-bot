"""Optional local audio for Reels; keep the silent video on any failure."""
import os
import random
import subprocess
from pathlib import Path

AUDIO_DIR = Path(__file__).resolve().parent / "audio"
AUDIO_TAGS = {"lofi-chill", "late-night-ambient", "quirky-upbeat",
              "soft-piano", "rain-focus", "warm-acoustic", "peaceful-horizon"}
EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg"}


def mix_audio(video_path, audio_tag, duration):
    """Return the filename used, or None; never replace video on failure."""
    video_path = Path(video_path)
    temporary = video_path.with_name(video_path.stem + ".audio-tmp.mp4")
    try:
        if audio_tag not in AUDIO_TAGS:
            print("AUDIO: invalid tag -> keeping silent Reel")
            return None
        candidates = sorted(
            p for p in AUDIO_DIR.glob("*")
            if p.is_file() and p.suffix.lower() in EXTENSIONS
            and (p.stem == audio_tag or p.stem.startswith(audio_tag + "-"))
        )
        if not candidates:
            print(f"AUDIO: no track for {audio_tag} -> keeping silent Reel")
            return None
        track = random.choice(candidates)
        duration = float(duration)
        if duration <= 0:
            raise ValueError("Reel duration must be positive")
        fade_out = max(0.0, duration - 2.0)
        filters = (f"atrim=duration={duration},asetpts=PTS-STARTPTS,"
                   f"volume=0.22,afade=t=in:st=0:d=1,"
                   f"afade=t=out:st={fade_out}:d=2")
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(video_path),
            "-stream_loop", "-1", "-i", str(track),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-af", filters,
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-t", str(duration), "-movflags", "+faststart", str(temporary),
        ], check=True, timeout=180, capture_output=True, text=True)
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(temporary),
        ], check=True, timeout=20, capture_output=True, text=True)
        if "audio" not in probe.stdout or temporary.stat().st_size == 0:
            raise ValueError("No audio stream in mixed output")
        os.replace(temporary, video_path)
        print(f"AUDIO: embedded {track.name} (volume 22%, fade in/out)")
        return track.name
    except Exception as exc:
        print(f"AUDIO: mixing failed ({type(exc).__name__}) -> keeping silent Reel")
        return None
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
