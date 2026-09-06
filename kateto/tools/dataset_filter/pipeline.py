"""
Pipeline: lee hermes.db / jsonl / txt, aplica filtros, clasifica Q/A, genera faltante, escribe jsonl.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import AsyncIterator

from .ai_filter import is_ai_like
from .classifier import MmBertQAClassifier
from .generator import Mode, generate_complement
from .secrets_filter import contains_secret, redact
from .splitter import split_long_text

log = logging.getLogger("dataset_filter.pipeline")


def iter_input_texts(input_path: Path, limit: int | None = None) -> AsyncIterator[str]:
    """
    Soporta:
      - .db / .sqlite : lee tablas con columna text/content/message/body (autodetect)
      - .jsonl / .json : cada línea {text|content|message}
      - .txt : una línea por item
    Es sync generator pero yield en async context; el caller hace 'async for'.
    """
    # Implementado como sync iterator envuelto — el pipeline lo consume sin await
    # Para simplificar, exponemos versión sync y el pipeline la adapta.
    raise NotImplementedError


def _read_texts_sync(input_path: Path, limit: int | None) -> list[str]:
    p = Path(input_path)
    if not p.exists():
        raise FileNotFoundError(p)
    out: list[str] = []
    suf = p.suffix.lower()

    def _add(t: str) -> None:
        t = (t or "").strip()
        if t:
            out.append(t)

    if suf in (".db", ".sqlite", ".sqlite3"):
        conn = sqlite3.connect(str(p))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # caso especial Hermes: messages con role=user -> solo lo mío
        try:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
            has_messages = cur.fetchone() is not None
            if has_messages:
                # detectar columnas
                cur.execute("SELECT * FROM messages LIMIT 1")
                cols = [d[0] for d in cur.description] if cur.description else []
                has_role = "role" in cols
                has_content = "content" in cols
                if has_content:
                    log.info("DB: modo Hermes detectado (messages.role=user, col content)")
                    if has_role:
                        q = "SELECT content FROM messages WHERE role='user' AND content IS NOT NULL AND length(content)>10"
                    else:
                        q = "SELECT content FROM messages WHERE content IS NOT NULL"
                    if limit:
                        q += f" LIMIT {limit*3}"
                    for row in cur.execute(q):
                        v = row[0]
                        if isinstance(v, str):
                            _add(v)
                            if limit and len(out) >= limit*3:
                                break
                    conn.close()
                    if out:
                        if limit:
                            out = out[:limit*3]
                        return out
                    # fallback a autodetect si no hubo resultados
        except Exception as e:
            log.debug("Hermes fast-path falló, fallback autodetect: %s", e)
        # autodetect genérico tabla/columna
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        if not tables:
            raise ValueError(f"DB sin tablas: {p}")
        # probar columnas comunes en orden
        col_candidates = ["text", "content", "message", "body", "data", "utterance"]
        found = False
        for tbl in tables:
            try:
                cur.execute(f"SELECT * FROM {tbl} LIMIT 1")
                cols = [d[0] for d in cur.description] if cur.description else []
            except Exception:
                continue
            hit = next((c for c in col_candidates if c in cols), None)
            if not hit and cols:
                hit = cols[0]
            if not hit:
                continue
            log.info("DB: leyendo tabla %s col %s", tbl, hit)
            q = f"SELECT {hit} FROM {tbl}"
            if limit:
                q += f" LIMIT {limit}"
            for row in cur.execute(q):
                v = row[0]
                if isinstance(v, (bytes, bytearray)):
                    try:
                        v = v.decode()
                    except Exception:
                        continue
                if isinstance(v, str):
                    _add(v)
                    if limit and len(out) >= limit:
                        break
            found = True
            break
        conn.close()
        if not found:
            raise ValueError(f"no se encontró columna de texto en {tables}")

    elif suf == ".jsonl":
        with p.open(encoding="utf-8") as f:
            for line in f:
                if limit and len(out) >= limit:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        t = obj.get("text") or obj.get("content") or obj.get("message") or obj.get("body") or ""
                    else:
                        t = str(obj)
                except Exception:
                    t = line
                _add(t)

    elif suf == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else [data]
        for obj in items:
            if limit and len(out) >= limit:
                break
            if isinstance(obj, dict):
                t = obj.get("text") or obj.get("content") or obj.get("message") or ""
            else:
                t = str(obj)
            _add(t)

    else:
        # tratar como texto plano
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            if limit and len(out) >= limit:
                break
            _add(line)

    if limit:
        out = out[:limit]
    return out


async def run_pipeline(
    *,
    input_path: Path,
    output_path: Path,
    classifier: MmBertQAClassifier,
    limit: int | None = None,
    batch_size: int = 32,
    dry_run: bool = False,
    filter_ai: bool = True,
    filter_secrets: bool = True,
    generate_missing: bool = True,
    dataset_mode: Mode = "argento",
    max_chars: int = 800,
    openai_model: str | None = None,
    openai_base_url: str | None = None,
    openai_api_key: str | None = None,
    concurrency: int = 4,
    ref_rate: float = 0.3,
    crude_rate: float = 0.25,
    align_filter: bool = True,
    judge: bool = False,
    judge_threshold: int = 3,
    progress_file: str | Path | None = None,
    progress_every: int = 1,
) -> dict:
    texts = _read_texts_sync(input_path, limit=None if generate_missing else limit)
    # si generate_missing y limit, el limit aplica a pares finales; leer más para compensar splits/filtros
    # simplificación: aplicar limit al final sobre pares generados
    total_in = len(texts)
    log.info("input: %d textos crudos desde %s", total_in, input_path)

    # 1) split
    expanded: list[str] = []
    for t in texts:
        chunks = split_long_text(t, max_chars=max_chars)
        expanded.extend(chunks)
    log.info("split: %d -> %d chunks", total_in, len(expanded))

    # 1b) filtro secretos — ANTES del filtro IA: barato y un leak en el
    # dataset es peor que perder un par por falso positivo
    no_secrets: list[str] = []
    dropped_secrets = 0
    if filter_secrets:
        for t in expanded:
            r = contains_secret(t)
            if r.found:
                dropped_secrets += 1
                log.debug("drop SECRET (%s): %.60s", r.reasons, redact(t))
            else:
                no_secrets.append(t)
        log.info("filtro secretos: dropped %d / %d", dropped_secrets, len(expanded))
    else:
        no_secrets = expanded

    # 2) filtro IA
    kept: list[str] = []
    dropped_ai = 0
    if filter_ai:
        for t in no_secrets:
            r = is_ai_like(t)
            if r.is_ai_like:
                dropped_ai += 1
                log.debug("drop IA (%.2f %s): %.60s", r.score, r.reasons, t)
            else:
                kept.append(t)
        log.info("filtro IA: dropped %d / %d", dropped_ai, len(no_secrets))
    else:
        kept = expanded

    # 2b) dedup exacto + near-dup (normaliza, baja repeticiones tipo 'continua')
    def _norm(s: str) -> str:
        import re as _re
        s = s.strip().lower()
        s = _re.sub(r"\s+", " ", s)
        s = _re.sub(r"^[>\-\*•\d\.\)]+\s*", "", s)
        return s

    seen: set[str] = set()
    deduped: list[str] = []
    dropped_dup = 0
    for t in kept:
        n = _norm(t)
        # colapsa repeticiones cortas tipo 'continua', 'dale', 'sisi' -> drop si ya visto o si es muy corto y repetitivo
        if n in seen:
            dropped_dup += 1
            continue
        # también drop si es ultra repetitivo (mismo token 3+ veces)
        toks = n.split()
        if len(toks) >= 3 and len(set(toks)) == 1 and len(n) < 30:
            dropped_dup += 1
            continue
        seen.add(n)
        deduped.append(t)
    log.info("dedup: dropped %d dups / %d -> %d únicos", dropped_dup, len(kept), len(deduped))
    kept = deduped
    # guardar para stats al final
    _dropped_dup = dropped_dup

    # 3) clasificar Q/A en batches + 4) generar faltante
    pairs: list[dict] = []
    extras: list[dict] = []  # follow-ups de reconocimiento de referencias
    _dropped_align = [0]
    _dropped_judge = [0]
    sem = asyncio.Semaphore(concurrency)

    async def _gen_one(text: str, label: str) -> dict | None:
        async with sem:
            # --no-generate: emitir solo clasificación sin requerir par completo
            if not generate_missing:
                return {"question": text if label == "question" else "", "answer": text if label != "question" else "", "source_label": label, "source_text": text, "generated": False}
            comp = None
            gen_flags: dict = {}
            if not dry_run:
                comp = await generate_complement(text, label, model=openai_model, base_url=openai_base_url, api_key=openai_api_key, mode=dataset_mode, ref_rate=ref_rate, crude_rate=crude_rate, flags=gen_flags)
            reference: dict | None = None
            if dataset_mode == "referencias" and comp and not dry_run:
                from .generator import build_reference_followup, parse_reference_response
                line, reference = parse_reference_response(comp)
                comp = line
                if reference:
                    q2, a2 = build_reference_followup(line, reference)
                    extras.append({"question": q2, "answer": a2, "source_label": "reference-followup",
                                   "source_text": line, "generated": True, "reference": reference})
            if label == "question":
                q, a = text, comp or ""
            elif label == "answer":
                q, a = comp or "", text
            else:
                q, a = comp or "", text
            if dry_run:
                if label == "question":
                    a = "[DRY-RUN answer]"
                else:
                    q = "[DRY-RUN question]"
            if not q or not a:
                return None
            pair = {"question": q, "answer": a, "source_label": label, "source_text": text, "generated": True}
            if reference:
                pair["reference"] = reference
            if gen_flags.get("crude"):
                pair["crude"] = True
            if align_filter and not dry_run:
                from .generator import pair_aligned
                ok, reason = pair_aligned(q, a, has_reference=bool(reference))
                pair["align"] = reason
                if not ok:
                    _dropped_align[0] += 1
                    return None
            if judge and not dry_run:
                from .generator import judge_alignment
                score = await judge_alignment(q, a, model=openai_model, base_url=openai_base_url, api_key=openai_api_key)
                pair["judge"] = score
                if score is not None and score < judge_threshold:
                    _dropped_judge[0] += 1
                    return None
            return pair

    # batch classify
    import time as _time
    _t0 = _time.time()
    _prog_path = Path(progress_file) if progress_file else None
    def _write_progress(done_chunks: int, total_chunks: int) -> None:
        if not _prog_path:
            return
        try:
            _prog_path.parent.mkdir(parents=True, exist_ok=True)
            _prog_path.write_text(json.dumps({
                "done_chunks": done_chunks,
                "total_chunks": total_chunks,
                "pairs": len(pairs),
                "dropped_align": _dropped_align[0],
                "dropped_judge": _dropped_judge[0],
                "elapsed_s": round(_time.time() - _t0, 1),
            }, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    for i in range(0, len(kept), batch_size):
        batch = kept[i : i + batch_size]
        labels = classifier.classify_batch(batch)
        # generar en paralelo por batch
        tasks = [_gen_one(t, lab) for t, lab in zip(batch, labels)]
        results = await asyncio.gather(*tasks)
        for r in results:
            if r is not None:
                pairs.append(r)
        if limit and len(pairs) >= limit:
            pairs = pairs[:limit]
            _write_progress(min(i + batch_size, len(kept)), len(kept))
            try:
                part = output_path.with_suffix(output_path.suffix + ".part")
                part.parent.mkdir(parents=True, exist_ok=True)
                with part.open("w", encoding="utf-8") as _pf:
                    for _p in pairs:
                        _pf.write(json.dumps(_p, ensure_ascii=False) + "\n")
            except Exception:
                pass
            break
        # progreso en tiempo real: log cada batch + archivo json para tail
        done = min(i + batch_size, len(kept))
        el = _time.time() - _t0
        rate = done / max(el, 0.1)
        log.info("progreso: %d/%d chunks -> %d pares (%.1f chunks/s, %.0fs)", done, len(kept), len(pairs), rate, el)
        if (i // batch_size) % max(progress_every, 1) == 0:
            _write_progress(done, len(kept))
            # volcado parcial para ver datos reales sin esperar al final
            try:
                part = output_path.with_suffix(output_path.suffix + ".part")
                part.parent.mkdir(parents=True, exist_ok=True)
                with part.open("w", encoding="utf-8") as _pf:
                    for _p in pairs:
                        _pf.write(json.dumps(_p, ensure_ascii=False) + "\n")
            except Exception:
                pass

    if limit:
        pairs = pairs[:limit]

    # follow-ups de reconocimiento: entran después del límite de pares base
    # (son chicos y determinísticos, no gastan LLM)
    n_followups = 0
    if extras and not dry_run:
        room = None if not limit else max(0, limit - len(pairs))
        for e in extras if room is None else extras[:room]:
            pairs.append(e)
            n_followups += 1

    stats = {
        "input_texts": total_in,
        "chunks": len(expanded),
        "kept_after_ai": len(kept),
        "dropped_secrets": dropped_secrets,
        "dropped_ai": dropped_ai,
        "dropped_dup": _dropped_dup,
        "dropped_align": _dropped_align[0],
        "dropped_judge": _dropped_judge[0],
        "pairs": len(pairs),
        "reference_followups": n_followups,
        "dry_run": dry_run,
    }

    if not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            for p in pairs:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
        log.info("escrito %d pares -> %s", len(pairs), output_path)
    else:
        log.info("dry-run: no se escribió %s (%d pares generados)", output_path, len(pairs))

    return stats
