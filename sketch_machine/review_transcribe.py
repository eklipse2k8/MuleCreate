"""Transcript of a review recording (review.py) with faster-whisper - runs as its own program in the Python where
faster-whisper is installed (not in Mule): python review_transcribe.py <review folder> [model] [language]

Reads ton.wav, writes transkript.json: {"model", "language", "duration", "segments": [{"start", "end", "text",
"words": [[word, start, end], ...]}]}. Standard library, numpy and faster_whisper only - no Mule modules.
On an error: transkript_fehler.txt and return value 1."""
import json
import os
import sys
import traceback
import wave

import numpy as np

RATE = 16000


def load_wav(path):
    """WAV (16 Bit) -> float32 mono, 16 kHz."""
    with wave.open(path, "rb") as w:
        ch, rate, width = w.getnchannels(), w.getframerate(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"expected 16-bit audio, got {width * 8} bit")
    a = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
    if ch > 1:
        a = a[: len(a) // ch * ch].reshape(-1, ch).mean(axis=1)
    if rate != RATE and len(a):
        n = int(round(len(a) * RATE / rate))
        a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)
    return a


def _cuda_paths():
    """Windows: make the CUDA libraries from the pip packages nvidia-cublas-cu12 / nvidia-cudnn-cu12 findable
    (they live in site-packages/nvidia/*/bin, where ctranslate2 does not look on its own)."""
    if sys.platform != "win32":
        return
    import site
    for base in site.getsitepackages() + [site.getusersitepackages()]:
        root = os.path.join(base, "nvidia")
        if not os.path.isdir(root):
            continue
        for sub in os.listdir(root):
            path = os.path.join(root, sub, "bin")
            if os.path.isdir(path):
                os.add_dll_directory(path)
                os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")


def transcribe(audio, name, language):
    """First on the graphics card, otherwise (no CUDA, library missing) on the processor -> (segments, info)."""
    from faster_whisper import WhisperModel
    _cuda_paths()
    kw = dict(language=language or None, word_timestamps=True, vad_filter=True, beam_size=5)
    try:
        model = WhisperModel(name, device="cuda", compute_type="float16")
        segs, info = model.transcribe(audio, **kw)
        return list(segs), info  # the segments are only produced while iterating - errors surface here
    except Exception as exc:
        print(f"GPU not usable ({exc}) - computing on the CPU", file=sys.stderr)
    model = WhisperModel(name, device="cpu", compute_type="int8")
    segs, info = model.transcribe(audio, **kw)
    return list(segs), info


def main(folder, name="large-v3-turbo", language=None):
    busy = os.path.join(folder, "transkript.laeuft")  # Mule and the MCP server do not start twice
    open(busy, "w").close()
    try:
        _run(folder, name, language)
    finally:
        if os.path.isfile(busy):
            os.remove(busy)


def _run(folder, name, language):
    audio = load_wav(os.path.join(folder, "ton.wav"))
    segs, info = transcribe(audio, name, language)
    out = {"model": name, "language": info.language, "duration": round(len(audio) / RATE, 2), "segments": []}
    for s in segs:
        out["segments"].append({
            "start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
            "words": [[w.word.strip(), round(w.start, 2), round(w.end, 2)] for w in (s.words or [])]})
    tmp = os.path.join(folder, "transkript.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(folder, "transkript.json"))
    err = os.path.join(folder, "transkript_fehler.txt")
    if os.path.isfile(err):
        os.remove(err)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    try:
        main(sys.argv[1], *(sys.argv[2:4]))
    except Exception:
        with open(os.path.join(sys.argv[1], "transkript_fehler.txt"), "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        traceback.print_exc()
        sys.exit(1)
