#!/usr/bin/env python3
"""Genera el evento de entrevista: sintetiza las voces, mide la envolvente de cada línea,
construye el guion con tiempos absolutos y mezcla la pista de audio.

Uso:
    python3 scripts/build_interview_event.py [--out assets/entrevista]

Salida: <out>/guion.json, <out>/audio/<linea>.wav, <out>/mix.wav
El video se produce después con scripts/render_interview_event.mjs sobre el guion.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VOICES = Path.home() / ".local/share/piper/voices"
PIPER = Path.home() / ".local/bin/piper"

# Voz de piper + factor de pitch (1.0 = la voz tal cual). El pitch se aplica con ffmpeg.
VOICE_OF = {
    "vos": ("es_MX-ald-medium.onnx", 1.0),
    "teto": ("es_AR-daniela-high.onnx", 1.0),
    "conquest": ("es_ES-davefx-medium.onnx", 0.94),
    "jane": ("es_MX-claude-high.onnx", 1.02),
    "whisperer": ("es_MX-ald-medium.onnx", 0.90),
    "rice": ("es_AR-daniela-high.onnx", 1.14),
}

CAST = {
    "vos": {"name": "VOS", "role": "Entrevistador", "color": "#7dd3fc"},
    "teto": {
        "name": "Teto",
        "role": "Recepción",
        "color": "#f2a1c6",
    },
    "conquest": {
        "name": "Conquest",
        "role": "Agile facilitator",
        "color": "#e0b061",
        "model": "/media/live2d/mark/Mark.model3.json",
    },
    "jane": {
        "name": "Jane",
        "role": "Operadora de guardia",
        "color": "#9be2a0",
        "model": "/media/live2d/hiyori/Hiyori.model3.json",
    },
    "whisperer": {
        "name": "Whisperer",
        "role": "Analista silencioso",
        "color": "#c4a6ff",
        "model": "/media/live2d/mao/Mao.model3.json",
    },
    "rice": {
        "name": "Rice",
        "role": "Runner de QA",
        "color": "#ffc98a",
        "model": "/media/live2d/rice/Rice.model3.json",
    },
}

# Cada candidato: dos preguntas del entrevistador y sus respuestas. La última frase es el veredicto.
CANDIDATES = [
    {
        "id": "conquest",
        "score": 62,
        "result": "rejected",
        "verdict": "Sabe conquistar. No sabe repartir el botín.",
        "qa": [
            ("¿Por qué deberíamos contratarte?",
             "Porque yo no negocio con el backlog: lo conquisto. Tres sprints, un mapa, cero excusas."),
            ("¿Y si el equipo no está de acuerdo con el mapa?",
             "Entonces el mapa miente. Se redibuja, se avanza, y el que queda atrás queda atrás."),
        ],
    },
    {
        "id": "jane",
        "score": 78,
        "result": "rejected",
        "verdict": "La mejor del día en procesos. Pidió dos sueldos.",
        "qa": [
            ("¿Qué hacés cuando el deploy falla un viernes?",
             "Rollback, aviso, y recién después busco el porqué. El viernes es de la gente que espera."),
            ("¿Y el lunes?",
             "Postmortem sin culpables. Con culpables, la gente aprende a esconder los logs."),
        ],
    },
    {
        "id": "rice",
        "score": 44,
        "result": "rejected",
        "verdict": "Honesto hasta el bug. No es lo que pide el puesto.",
        "qa": [
            ("¿Cuál es tu mayor defecto?",
             "Contesto con la verdad aunque incomode: esto es una entrevista de mentira y yo ya leí el guion."),
            ("¿Y tu mayor virtud?",
             "Que puedo correr este evento entero en veinte segundos. Miralo."),
        ],
    },
    {
        "id": "whisperer",
        "score": 91,
        "result": "hired",
        "verdict": "Ve lo que el equipo no dice. Contratado.",
        "qa": [
            ("¿Qué ves cuando mirás un equipo?",
             "Veo lo que no dicen en el daily. Eso es lo que decide si el proyecto llega."),
            ("¿Y lo vas a decir en voz alta?",
             "Sólo cuando importe. El resto del tiempo escucho."),
        ],
    },
]

INTRO = {
    "title": "ENTREVISTA DE TRABAJO",
    "subtitle": "4 agentes · 1 puesto",
    "footer": "Oficina 3B · Hipotenusa Labs",
}


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, **kw)


def synth(text: str, voice_key: str, out_wav: Path) -> float:
    model, pitch = VOICE_OF[voice_key]
    model_path = VOICES / model
    if not model_path.is_file():
        raise SystemExit(f"falta la voz de piper: {model_path}")
    raw = out_wav.with_suffix(".raw.wav")
    run([str(PIPER), "-m", str(model_path), "-f", str(raw), "--length-scale", "1.02"],
        input=text.encode())
    if abs(pitch - 1.0) > 0.01:
        with wave.open(str(raw)) as w:
            sr = w.getframerate()
        # asetrate cambia tono y velocidad; atempo compensa la velocidad y deja sólo el tono.
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
             "-af", f"asetrate={sr}*{pitch},aresample={sr},atempo={1/pitch}", str(out_wav)])
        raw.unlink()
    else:
        raw.replace(out_wav)
    return wav_duration(out_wav)


def wav_duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(path)]).stdout.decode().strip()
    return round(float(out), 3)


def envelope(path: Path, step: float = 0.04) -> list[float]:
    """RMS por ventana de 40 ms, normalizada a 1.0. Es lo que mueve la boca del modelo."""
    raw = run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
               "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]).stdout
    samples = memoryview(raw).cast("f")
    win = max(1, int(16000 * step))
    env, peak = [], 1e-6
    for i in range(0, len(samples), win):
        chunk = samples[i:i + win]
        if not len(chunk):
            break
        rms = math.sqrt(sum(float(s) * float(s) for s in chunk) / len(chunk))
        env.append(rms)
        peak = max(peak, rms)
    return [round(min(1.0, r / peak), 3) for r in env]


def validate_guion(g: dict) -> list[str]:
    """Post-condiciones del evento. Ninguna es cosmética: si fallan, el video miente."""
    errs: list[str] = []
    hired = [c["id"] for c in CANDIDATES if c["result"] == "hired"]
    if len(hired) != 1:
        errs.append(f"tiene que haber exactamente un contratado, hay {len(hired)}")
    cues = g["cues"]
    if any(b["t"] < a["t"] for a, b in zip(cues, cues[1:])):
        errs.append("los cues no están en orden temporal")
    for ln in g["lines"]:
        if ln["t"] + ln["dur"] > g["duration"] + 0.01:
            errs.append(f"la línea {ln['id']} se sale del evento")
        if not ln["env"]:
            errs.append(f"la línea {ln['id']} no tiene envolvente")
    # un candidato entra y sale una sola vez, y no hay dos adentro a la vez
    inside: set[str] = set()
    for c in cues:
        if c["kind"] == "enter":
            if inside:
                errs.append(f"entró {c['who']} con la sala ocupada por {sorted(inside)}")
            inside.add(c["who"])
        elif c["kind"] == "clear":
            inside.clear()
    if inside:
        errs.append(f"quedaron candidatos sin salir: {sorted(inside)}")
    return errs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "assets/entrevista"))
    ap.add_argument("--check", action="store_true", help="sólo valida el guion que ya está en disco")
    args = ap.parse_args()
    out = Path(args.out)

    if args.check:
        g = json.loads((out / "guion.json").read_text())
        errs = validate_guion(g)
        print(json.dumps({"guion": str(out / "guion.json"), "duration": g["duration"],
                          "lines": len(g["lines"]), "errors": errs}, ensure_ascii=False))
        raise SystemExit(1 if errs else 0)

    audio_dir = out / "audio"
    if audio_dir.exists():
        shutil.rmtree(audio_dir)
    audio_dir.mkdir(parents=True)

    cues: list[dict] = []
    lines: list[dict] = []

    def line(t: float, speaker: str, text: str) -> float:
        """Sintetiza una línea, la agenda en `t` y devuelve su duración."""
        lid = f"l{len(lines)+1:02d}"
        path = audio_dir / f"{lid}.wav"
        dur = synth(text, speaker, path)
        lines.append({"id": lid, "speaker": speaker, "text": text, "t": round(t, 3),
                      "dur": dur, "wav": f"audio/{lid}.wav", "env": envelope(path)})
        return dur

    cues.append({"t": 0.0, "kind": "slate", "phase": "intro", **INTRO})
    cursor = 4.2

    for cand in CANDIDATES:
        cid = cand["id"]
        # Recepción llama al candidato y abre la puerta.
        cursor += 0.4
        cues.append({"t": round(cursor - 0.3, 3), "kind": "reception", "who": "teto",
                     "text": f"{CAST[cid]['name']}, puede pasar."})
        cursor += line(cursor, "teto", f"{CAST[cid]['name']}, puede pasar.") + 0.5

        cues.append({"t": round(cursor - 0.45, 3), "kind": "door", "state": "open"})
        cues.append({"t": round(cursor, 3), "kind": "enter", "who": cid, "walk": 2.4})
        cursor += 2.6
        cues.append({"t": round(cursor, 3), "kind": "sit", "who": cid})
        cursor += 0.5

        for q, a in cand["qa"]:
            cues.append({"t": round(cursor, 3), "kind": "question", "text": q})
            dur = line(cursor, "vos", q)
            cursor += dur + 0.45
            cues.append({"t": round(cursor, 3), "kind": "talk", "who": cid})
            dur = line(cursor, cid, a)
            cursor += dur + 0.55

        cues.append({"t": round(cursor, 3), "kind": "verdict", "who": cid,
                     "score": cand["score"], "result": cand["result"], "text": cand["verdict"]})
        cursor += 3.0
        cues.append({"t": round(cursor, 3), "kind": "leave", "who": cid, "walk": 1.9})
        cues.append({"t": round(cursor + 0.1, 3), "kind": "door", "state": "open"})
        cursor += 2.2
        cues.append({"t": round(cursor - 0.2, 3), "kind": "door", "state": "closed"})
        cues.append({"t": round(cursor, 3), "kind": "clear"})

    hired = next(c for c in CANDIDATES if c["result"] == "hired")
    cursor += 0.8
    cues.append({"t": round(cursor, 3), "kind": "slate", "phase": "outro",
                 "title": f"CONTRATADO: {CAST[hired['id']]['name'].upper()}",
                 "subtitle": f"{hired['score']}/100 — {hired['verdict']}",
                 "footer": "4 candidatos · 1 puesto · 0 preguntas de RRHH"})
    duration = round(cursor + 7.0, 3)
    cues.append({"t": duration, "kind": "end"})

    guion = {
        "title": "Entrevista — Oficina 3B",
        "width": 1920, "height": 1080, "fps": 25,
        "duration": duration,
        "cast": CAST,
        "cues": cues,
        "lines": lines,
    }
    (out / "guion.json").write_text(json.dumps(guion, ensure_ascii=False, indent=1))

    # Mezcla: cada línea en su instante absoluto sobre un lecho de silencio.
    inputs, filters, labels = [], [], []
    for i, ln in enumerate(lines):
        inputs += ["-i", str(out / ln["wav"])]
        ms = int(ln["t"] * 1000)
        filters.append(f"[{i}:a]adelay={ms}|{ms},apad=whole_dur={duration}[a{i}]")
        labels.append(f"[a{i}]")
    graph = ";".join(filters) + ";" + "".join(labels) + \
        f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0," \
        f"alimiter=limit=0.94,aresample=44100[mix]"
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", graph,
         "-map", "[mix]", "-t", str(duration), str(out / "mix.wav")])

    errs = validate_guion(guion)
    print(json.dumps({"duration": duration, "lines": len(lines), "cues": len(cues),
                      "mix": str(out / "mix.wav"), "errors": errs}, ensure_ascii=False))
    if errs:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
