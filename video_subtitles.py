from __future__ import annotations

import os
import argparse
import shutil
import ssl
import subprocess
import sys
import tempfile
import textwrap
import wave
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
APP_NAME = "Crea sottotitoli"
LANGUAGES = {
    "Rilevamento automatico": None,
    "Italiano": "it",
    "English": "en",
    "Español": "es",
    "Français": "fr",
}


def installation_root() -> Path:
    configured = os.environ.get("VIDEO_SUBS_ROOT")
    if configured:
        return Path(configured).resolve()
    for candidate in (APP_DIR, *APP_DIR.parents):
        if (candidate / ".venv" / "Scripts" / "python.exe").is_file():
            return candidate
    return APP_DIR


def find_ffmpeg(root: Path) -> str:
    configured = os.environ.get("VIDEO_SUBS_FFMPEG")
    if configured and Path(configured).is_file():
        return configured
    for candidate in (
        root / ".venv" / "Scripts" / "ffmpeg.exe",
        APP_DIR / "ffmpeg.exe",
    ):
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError(
            "Non trovo FFmpeg. Avvia il programma con la cartella d'installazione completa."
        ) from exc


def configure_windows_certificates() -> None:
    """Let Python use Windows' trusted roots when downloading the model."""
    try:
        import certifi

        certificates = [Path(certifi.where()).read_text(encoding="ascii")]
        for store in ("ROOT", "CA"):
            for der, encoding, _trust in ssl.enum_certificates(store):
                if encoding == "x509_asn":
                    certificates.append(ssl.DER_cert_to_PEM_cert(der))
        cache_dir = APP_DIR / "_cache"
        cache_dir.mkdir(exist_ok=True)
        bundle = cache_dir / "windows-ca-bundle.pem"
        bundle.write_text("\n".join(certificates), encoding="ascii")
        os.environ["SSL_CERT_FILE"] = str(bundle)
        os.environ["REQUESTS_CA_BUNDLE"] = str(bundle)
        os.environ["CURL_CA_BUNDLE"] = str(bundle)
    except Exception:
        # Existing Python certificate configuration remains in force.
        pass


def stamp(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def split_segment(segment, max_chars: int = 82, max_seconds: float = 5.5):
    words = getattr(segment, "words", None) or []
    usable = [w for w in words if getattr(w, "word", "").strip()]
    if not usable:
        text = " ".join(segment.text.split())
        tokens = text.split()
        if not tokens:
            return []
        # Fallback for a model result without word-level timings.
        groups, current = [], []
        for token in tokens:
            candidate = " ".join(current + [token])
            if current and len(candidate) > max_chars:
                groups.append(current)
                current = []
            current.append(token)
        if current:
            groups.append(current)
        duration = max(0.2, segment.end - segment.start)
        total_chars = max(1, sum(len(" ".join(g)) for g in groups))
        result, cursor = [], segment.start
        for group in groups:
            fraction = sum(len(t) for t in group) / total_chars
            end = min(segment.end, cursor + duration * fraction)
            result.append((cursor, max(cursor + 0.2, end), " ".join(group)))
            cursor = end
        return result

    result, current = [], []

    def flush():
        if current:
            phrase = "".join(w.word for w in current).strip()
            if phrase:
                start = next((w.start for w in current if w.start is not None), segment.start)
                end = next((w.end for w in reversed(current) if w.end is not None), segment.end)
                result.append((start, max(start + 0.2, end), phrase))
            current.clear()

    for word in usable:
        token = word.word
        prospective = "".join(w.word for w in current) + token
        if current:
            gap = word.start - current[-1].end if word.start is not None and current[-1].end is not None else 0
            elapsed = (current[-1].end or segment.end) - (current[0].start or segment.start)
            sentence_end = current[-1].word.rstrip().endswith((".", "?", "!")) and elapsed >= 1.0
            if (
                gap > 0.65
                or elapsed >= max_seconds
                or len(prospective) > max_chars
                or len(current) >= 12
                or sentence_end
            ):
                flush()
        current.append(word)
    flush()
    return result


def write_srt(cues, path: Path) -> int:
    blocks = []
    for number, (start, end, text) in enumerate(cues, 1):
        wrapped = textwrap.fill(
            " ".join(text.split()), width=42, break_long_words=False, break_on_hyphens=False
        )
        blocks.append(f"{number}\n{stamp(start)} --> {stamp(end)}\n{wrapped}")
    path.write_text("\ufeff" + "\n\n".join(blocks) + "\n", encoding="utf-8")
    return len(blocks)


def merge_orphan_cues(cues) -> list[tuple[float, float, str]]:
    """Attach extremely short word fragments to an adjacent nearby cue."""
    merged: list[tuple[float, float, str]] = []
    for start, end, text in cues:
        if merged:
            prev_start, prev_end, prev_text = merged[-1]
            gap = start - prev_end
            if (
                end - start < 0.55
                and gap <= 0.45
                and end - prev_start <= 5.5
                and len(prev_text) + len(text) + 1 <= 82
            ):
                merged[-1] = (prev_start, max(prev_end, end), f"{prev_text} {text}")
                continue
        merged.append((start, end, text))
    return merged


def run_logged(command, cwd: Path, progress=None, duration: float | None = None) -> None:
    proc = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    tail = []
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        if line.startswith("out_time_ms=") and duration and progress:
            try:
                seconds = int(line.split("=", 1)[1]) / 1_000_000
                progress(seconds, duration)
            except ValueError:
                pass
        elif "=" not in line:
            tail.append(line)
            tail = tail[-12:]
    code = proc.wait()
    if code:
        detail = "\n".join(tail[-8:]) or f"FFmpeg ha restituito il codice {code}."
        raise RuntimeError(detail)


def process_video(
    source: Path,
    output_dir: Path,
    language: str | None,
    font_size: int,
    progress,
    status,
) -> tuple[Path, Path, int]:
    source = source.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    root = installation_root()
    ffmpeg = find_ffmpeg(root)
    model_dir = Path(os.environ.get("VIDEO_SUBS_MODEL_DIR", root / "models"))
    if not model_dir.is_dir():
        model_dir = APP_DIR / "models"
    model_dir.mkdir(parents=True, exist_ok=True)

    configure_windows_certificates()
    status("Carico il modello Whisper small; al primo avvio può scaricare circa 500 MB...")
    try:
        import ctranslate2
        from faster_whisper import WhisperModel
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "Mancano le dipendenze faster-whisper o numpy nell'ambiente Python. "
            "Consulta il MANUALE d'USO nella cartella del programma."
        ) from exc

    device = "cuda" if ctranslate2.get_cuda_device_count() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    try:
        model = WhisperModel(
            "small",
            device=device,
            compute_type=compute_type,
            cpu_threads=max(2, min(8, (os.cpu_count() or 4) - 1)),
            download_root=str(model_dir),
        )
    except Exception:
        if device == "cuda":
            status("GPU non disponibile con questo modello: passo alla modalità CPU...")
            model = WhisperModel(
                "small", device="cpu", compute_type="int8", download_root=str(model_dir)
            )
        else:
            raise

    with tempfile.TemporaryDirectory(prefix="sottotitoli_", dir=APP_DIR) as temp_name:
        temp = Path(temp_name)
        audio_path = temp / "audio.wav"
        srt_for_filter = temp / "captions.srt"

        status("Estraggo l'audio senza modificare il video originale...")
        run_logged(
            [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
                "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a",
                "pcm_s16le", str(audio_path),
            ],
            APP_DIR,
        )

        with wave.open(str(audio_path), "rb") as wav_file:
            if wav_file.getframerate() != 16000 or wav_file.getnchannels() != 1:
                raise RuntimeError("Non riesco a preparare l'audio a 16 kHz.")
            frame_count = wav_file.getnframes()
            audio_bytes = wav_file.readframes(frame_count)
        audio_samples = np.frombuffer(audio_bytes, dtype="<i2").astype(np.float32) / 32768.0
        del audio_bytes
        duration = frame_count / 16000

        status("Trascrivo il parlato in italiano (o rilevo automaticamente la lingua)...")
        segments, info = model.transcribe(
            audio_samples,
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 250},
            word_timestamps=True,
        )
        status(f"Lingua riconosciuta: {info.language} ({info.language_probability:.0%}).")
        del model
        cues = []
        for segment in segments:
            cues.extend(split_segment(segment))
            if cues:
                progress(min(65, 12 + 53 * min(1.0, segment.end / max(duration, 1))), 100)
        del audio_samples
        if not cues:
            raise RuntimeError("Non ho trovato parlato nel video, quindi non ho creato sottotitoli.")

        cues = merge_orphan_cues(cues)
        cue_count = write_srt(cues, srt_for_filter)
        srt_output = output_dir / f"{source.stem}_sottotitoli.srt"
        video_output = output_dir / f"{source.stem}_sottotitolato.mp4"
        shutil.copy2(srt_for_filter, srt_output)

        status("Incorporo i sottotitoli nel video; i silenzi restano invariati...")
        relative_srt = srt_for_filter.relative_to(APP_DIR).as_posix()
        style = (
            f"FontName=Arial,FontSize={font_size},PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,BorderStyle=1,Outline=1,Shadow=0,"
            "Alignment=2,MarginV=18"
        )
        video_filter = f"subtitles={relative_srt}:force_style='{style}'"
        partial_output = video_output.with_name(video_output.stem + ".partial.mp4")
        try:
            run_logged(
                [
                    ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
                    "-map", "0:v:0", "-map", "0:a?", "-vf", video_filter,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
                    "-progress", "pipe:1", "-nostats", str(partial_output),
                ],
                APP_DIR,
                progress=lambda seconds, total: progress(65 + 35 * min(1, seconds / total), 100),
                duration=duration,
            )
            if not partial_output.is_file() or partial_output.stat().st_size < 100_000:
                raise RuntimeError("Il file video finale non è stato creato correttamente.")
            os.replace(partial_output, video_output)
            progress(100, 100)
        except Exception:
            if partial_output.exists():
                partial_output.unlink()
            raise
        return video_output, srt_output, cue_count


def main():
    parser = argparse.ArgumentParser(description="Crea un MP4 con sottotitoli automatici e un SRT.")
    parser.add_argument("video", nargs="?", help="Percorso del video (opzionale in modalità guidata)")
    parser.add_argument("--output-dir", help="Cartella in cui salvare MP4 e SRT")
    parser.add_argument("--language", choices=("it", "en", "es", "fr", "auto"), default="it")
    parser.add_argument("--font-size", type=int, default=9)
    args = parser.parse_args()

    guided = args.video is None
    print("CREA SOTTOTITOLI DA UN VIDEO")
    print("Il programma trascrive l'audio, crea MP4 e SRT e conserva i silenzi.")
    print("Il video originale non viene modificato.\n")

    video_text = args.video
    if guided:
        video_text = input("Trascina qui il video (oppure incolla il percorso) e premi Invio: ").strip()
        video_text = video_text.strip('"')
    source = Path(video_text).expanduser().resolve()
    if not source.is_file():
        print(f"\nERRORE: non trovo il video: {source}")
        if guided:
            input("\nPremi Invio per chiudere.")
        return 2

    if guided:
        output_text = input(f"Cartella di destinazione [Invio = {source.parent}]: ").strip().strip('"')
        output_dir = Path(output_text).expanduser().resolve() if output_text else source.parent
        print("\nLingua parlata:")
        print("  1. Italiano (consigliato per le lezioni)")
        print("  2. Rilevamento automatico")
        print("  3. English   4. Español   5. Français")
        language_choice = input("Scelta [1]: ").strip() or "1"
        lang_codes = {"1": "it", "2": "auto", "3": "en", "4": "es", "5": "fr"}
        if language_choice not in lang_codes:
            print("Scelta non valida: uso Italiano.")
            language_choice = "1"
        language = lang_codes[language_choice]
        size_text = input("Dimensione sottotitoli 8-18 [9]: ").strip()
        font_size = int(size_text) if size_text.isdigit() else 9
    else:
        output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else source.parent
        language = args.language
        font_size = args.font_size

    if not 8 <= font_size <= 18:
        print("Dimensione non valida: imposto 9.")
        font_size = 9
    if language == "auto":
        language = None

    expected_video = output_dir / f"{source.stem}_sottotitolato.mp4"
    expected_srt = output_dir / f"{source.stem}_sottotitoli.srt"
    if expected_video.exists() or expected_srt.exists():
        answer = input("Esistono già risultati con questo nome. Sovrascriverli? [s/N]: ").strip().lower()
        if answer not in {"s", "si", "sì", "y", "yes"}:
            print("Operazione annullata.")
            if guided:
                input("Premi Invio per chiudere.")
            return 0

    def show_progress(value, _maximum):
        print(f"\rAvanzamento: {max(0, min(100, int(value))):3d}%", end="", flush=True)

    def show_status(message):
        print(f"\n{message}", flush=True)

    try:
        video, srt, count = process_video(
            source, output_dir, language, font_size, show_progress, show_status
        )
        print(f"\n\nCompletato: {count} segmenti di sottotitoli.")
        print(f"Video: {video}")
        print(f"SRT:   {srt}")
        result = 0
    except Exception as exc:
        print(f"\n\nERRORE: {exc}")
        result = 1
    if guided:
        input("\nPremi Invio per chiudere.")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
