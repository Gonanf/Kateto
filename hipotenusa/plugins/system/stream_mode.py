"""Modo stream: Hipotenusa comenta la partida y contesta el chat en voz alta.

Una sola cola con prioridad, de mayor a menor:

0. **donaciones** (Super Chat, Super Sticker, membresías)
1. **mensajes** del chat
2. **frases de guion** (solo si el chat está callado ``min_s``..``max_s`` segundos)

Todo sale como ``speak`` con ``literal=True``: la voz lo dice tal cual, sin LLM.
El chat entra por ``yt-dlp`` (sin OAuth, sin API key); si no hay ``video_url``
el plugin queda en modo frases.

Config (``config.toml``)::

    [plugin.stream_mode]
    enabled = true
    voice = "jane"
    video_url = ""           # URL o videoId del live; vacío = solo frases
    min_s = 60               # ventana de silencio antes de una frase de guion
    max_s = 180
    filler = true            # false = no habla sola, solo contesta el chat
    max_chars = 220          # tope por mensaje leído (URLs -> "un link")
    # phrases = ["frase 1", "frase 2"]   # override del pool

Ruteo al micrófono virtual del juego: es operación del SO, no del plugin.
OJO: el player usa sounddevice/PortAudio con backend ALSA, así que
``PULSE_SINK`` NO lo redirige (medido: con el sink default en ``hipotenusa_mic``,
``aplay -D default`` se cuelga en vez de sonar ahí). O se elige el device en el
player, o se reproduce con ``pw-play --target=hipotenusa_mic``.
"""

from __future__ import annotations

import asyncio
import glob
import json
import random
import re
import shutil
import subprocess
import tempfile
import threading
import time
from contextlib import suppress
from typing import Any

from loguru import logger

from hipotenusa.core.event import SpeakRequestData
from hipotenusa.core.plugin import Plugin

log = logger

_URL_RE = re.compile(r"https?://\S+")
_PAID = ("liveChatPaidMessageRenderer", "liveChatPaidStickerRenderer")
_SKIP = ("liveChatViewerEngagementMessageRenderer", "liveChatModeChangeMessageRenderer")

# Frases de guion (rioplatense), copiadas del pool probado en
# ~/bin/hipotenusa-phonon.py. Override por config o por constructor.
CALMA: tuple[str, ...] = (
    "Acá Hipotenusa, reportando desde el techo del Sevastopol. Todo tranquilo. Demasiado tranquilo.",
    "Che, jugador, ese ruido de tubería no es el alien. O sí. No sé. Seguí.",
    "Te estoy viendo por la cámara. Estás en el locker. El alien también te vio.",
    "Consejo gratis: el alien odia el fuego. Vos odiás morir. Hacé la cuenta.",
    "Se te cayó un frasco. El alien lo escuchó. Yo lo escuché. Todos escuchamos.",
    "Estás tardando mucho en ese ducto. No es por apurarte, pero se acerca.",
    "Hipotenusa presente. Aviso: si te agarra, no es mi culpa. Bueno, un poco.",
    "Ese sintetizador de sonido que prendiste se escucha a tres cubiertas.",
    "Mirá, yo no quiero destapARTE, pero hay algo respirando en el techo.",
    "El movimiento tracker marca algo cerca. Cerca cerca. Tipo, muy cerca.",
    "Sabés que correr hace ruido, ¿no? Bueno, ya lo hiciste. Felicitaciones.",
    "Ahí va el alien. Pasillo cuatro. No el que estás vos. Por ahora.",
    "Hipotenusa al habla: guardá la pistola, no sirve de nada y hace ruido.",
    "Podés esconderte en la ventilación. O podés morir con estilo. Elegí.",
    "Silencio. Shhh. No, pará, ese ruido lo hiciste vos. Genial.",
    "Te delato un poquito: hay un android a diez metros. Está mirándote.",
    "Muy lindo el sigilo, pero el alien tiene oído absoluto. Y hambre.",
    "Estoy conectada al stream y a tus esperanzas. Ambas se están cayendo.",
    "Ese locker está muy cerca. Yo que vos entro. Ya. Ahora. Dale.",
)

DEFAULT_MIN_S = 60.0
DEFAULT_MAX_S = 180.0


# --- lectura del chat de YouTube -------------------------------------------


def runs_text(obj: Any) -> str:
    return "".join(str(run.get("text", "")) for run in (obj or {}).get("runs", []))


def clean(text: str, max_chars: int = 220) -> str:
    return _URL_RE.sub("un link", text).replace("\n", " ").strip()[:max_chars]


def classify(item: dict[str, Any], max_chars: int = 220) -> tuple[int, str] | None:
    """item con un solo renderer -> (prioridad, frase) o None si no se dice."""
    tipo, renderer = next(iter(item.items()))
    if not isinstance(renderer, dict) or tipo in _SKIP:
        return None
    author = ((renderer.get("authorName") or {}).get("simpleText") or "alguien").lstrip("@")
    badges = renderer.get("authorBadges") or [{}]
    if any((b.get("liveChatAuthorBadgeRenderer") or {}).get("tooltip") == "Owner" for b in badges):
        return None
    if tipo in _PAID:
        amount = ((renderer.get("purchaseAmountText") or {}).get("simpleText") or "").strip()
        comment = clean(runs_text(renderer.get("message")), max_chars)
        said = f" Dice: {comment}." if comment else " No dejó mensaje."
        return 0, f"¡{amount} de {author}!{said} Gracias, {author}."
    if tipo == "liveChatMembershipItemRenderer":
        sub = clean(runs_text(renderer.get("headerSubtext")), 120)
        return 0, f"¡{author} {sub}! Gracias por bancar."
    if tipo == "liveChatTextMessageRenderer":
        text = clean(runs_text(renderer.get("message")), max_chars)
        if not text or text.lower().startswith("[hipotenusa]"):
            return None
        return 1, f"{author} dice: {text}"
    return None


def chat_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Línea JSON (VOD o vivo) -> items de chat, ya sin envoltorio."""
    actions = (payload.get("replayChatItemAction") or {}).get("actions") or payload.get("actions") or []
    items = []
    for action in actions:
        item = (action.get("addChatItemAction") or {}).get("item")
        if isinstance(item, dict) and item:
            items.append(item)
    return items


def item_id(item: dict[str, Any]) -> str | None:
    renderer = next(iter(item.values()), {})
    return renderer.get("id") if isinstance(renderer, dict) else None


class _ChatTail(threading.Thread):
    """Corre yt-dlp y empuja cada línea del JSONL al loop, sin bloquearlo."""

    def __init__(self, video_url: str, loop: asyncio.AbstractEventLoop, sink: asyncio.Queue[str]) -> None:
        super().__init__(name="hipotenusa-chat-tail", daemon=True)
        self._url = video_url
        self._loop = loop
        self._sink = sink
        self._stop_flag = threading.Event()

    def stop(self) -> None:
        self._stop_flag.set()

    def run(self) -> None:
        workdir = tempfile.mkdtemp(prefix="hipotenusa-chat-")
        proc = subprocess.Popen(  # noqa: S603 - argv fijo + url de config
            ["yt-dlp", "--skip-download", "--write-subs", "--sub-langs", "live_chat",
             "-o", f"{workdir}/%(id)s.%(ext)s", self._url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            path = self._wait_for_file(proc, workdir)
            if path is None:
                log.warning("stream_mode: yt-dlp no abrió el chat (¿stream terminado?)")
                return
            with open(path, errors="ignore") as handle:
                while not self._stop_flag.is_set():
                    line = handle.readline()
                    if line:
                        self._push(line)
                    elif proc.poll() is not None:
                        break
                    else:
                        time.sleep(0.3)
        finally:
            proc.terminate()

    def _wait_for_file(self, proc: subprocess.Popen[str], workdir: str) -> str | None:
        for _ in range(60):
            found = glob.glob(f"{workdir}/*.json")
            if found:
                return found[0]
            if proc.poll() is not None or self._stop_flag.is_set():
                return None
            time.sleep(0.5)
        return None

    def _push(self, line: str) -> None:
        if self._loop.is_closed():
            return
        try:
            self._loop.call_soon_threadsafe(self._sink.put_nowait, line)
        except (RuntimeError, asyncio.QueueFull):
            pass  # loop cerrado o reader atrasado: se descarta la línea


def _opt(settings: Any | None, key: str, default: Any) -> Any:
    """Read a key from PluginSettings (or any dict-like) with a default."""
    if settings is None:
        return default
    value = getattr(settings, key, None)
    if value is None:
        getter = getattr(settings, "get", None)
        if callable(getter):
            try:
                value = getter(key, None)
            except Exception:  # noqa: BLE001
                value = None
    return default if value is None else value


class StreamModePlugin(Plugin):
    """Chat + frases de guion en una sola cola, con las donaciones primero."""

    def __init__(
        self,
        settings: Any | None = None,
        *,
        rng: random.Random | None = None,
        phrases: list[str] | tuple[str, ...] | None = None,
        voice: str | None = None,
        min_s: float | None = None,
        max_s: float | None = None,
        filler: bool | None = None,
        video_url: str | None = None,
        max_chars: int | None = None,
    ) -> None:
        super().__init__("stream_mode", capabilities=("system", "stream"))
        self._enabled_by_config = bool(_opt(settings, "enabled", False))
        self._filler = bool(_opt(settings, "filler", True)) if filler is None else filler
        self._voice = str(voice or _opt(settings, "voice", "jane"))
        lo = float(min_s if min_s is not None else _opt(settings, "min_s", DEFAULT_MIN_S))
        hi = float(max_s if max_s is not None else _opt(settings, "max_s", DEFAULT_MAX_S))
        if lo <= 0 or hi <= 0 or lo > hi:
            log.warning("stream_mode: invalid range {}-{}s, using {}-{}s", lo, hi, DEFAULT_MIN_S, DEFAULT_MAX_S)
            lo, hi = DEFAULT_MIN_S, DEFAULT_MAX_S
        self._min_s, self._max_s = lo, hi
        pool = phrases if phrases is not None else _opt(settings, "phrases", None)
        self._phrases: tuple[str, ...] = tuple(pool) if pool else CALMA
        self._video_url = str(video_url if video_url is not None else _opt(settings, "video_url", "") or "")
        self._max_chars = int(max_chars if max_chars is not None else _opt(settings, "max_chars", 220))
        self._rng = rng or random.Random()
        self._task: asyncio.Task[None] | None = None
        self._reader: asyncio.Task[None] | None = None
        # ponytail: tope fijo de 200; en floods se descarta lo que no entra
        self._queue: asyncio.PriorityQueue[tuple[int, int, str]] = asyncio.PriorityQueue(200)
        self._lines: asyncio.Queue[str] | None = None
        self._tail: _ChatTail | None = None
        self._seq = 0
        self._seen: set[str] = set()

    @property
    def available(self) -> bool:
        """Configured on and with something to say: chat source or phrases."""
        return self._enabled_by_config and bool(self._video_url or (self._filler and self._phrases))

    async def initialize(self) -> None:
        self.required_manager.register_event("speak", SpeakRequestData)

    async def enable(self) -> None:
        if not self.available:
            log.debug(
                "stream_mode: off (enabled={}, filler={}, url={})",
                self._enabled_by_config,
                self._filler,
                bool(self._video_url),
            )
            return
        if self._video_url and not shutil.which("yt-dlp"):
            log.warning("stream_mode: yt-dlp no está en PATH, sigo solo con frases")
        elif self._video_url:
            self._lines = asyncio.Queue(maxsize=1000)
            self._tail = _ChatTail(self._video_url, asyncio.get_running_loop(), self._lines)
            self._tail.start()
            self._reader = asyncio.create_task(self._read_loop(), name="hipotenusa-stream-chat-reader")
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._speak_loop(), name="hipotenusa-stream-mode")
            log.info(
                "stream_mode: {:.0f}-{:.0f}s as {} | chat={}",
                self._min_s,
                self._max_s,
                self._voice,
                bool(self._tail),
            )

    async def disable(self) -> None:
        task, self._task = self._task, None
        reader, self._reader = self._reader, None
        for candidate in (task, reader):
            if candidate is not None and candidate is not asyncio.current_task():
                candidate.cancel()
                with suppress(asyncio.CancelledError):
                    await candidate
        if self._tail is not None:
            self._tail.stop()
            await asyncio.to_thread(self._tail.join, 2.0)
            self._tail = None

    async def say(self, text: str | None = None) -> None:
        """Emit one literal ``speak``: ``text`` as-is, or a random phrase."""
        prompt = text or self._rng.choice(self._phrases)
        # El player encola el PCM: emitir rápido no corta la frase anterior.
        # ponytail: sin espera por speaking_state; si el turn gate empieza a
        # descartar frases encadenadas, agregar la espera acá.
        await self.required_manager.emit(
            "speak",
            SpeakRequestData(voice=self._voice, prompt=prompt, origin="external", literal=True),
            source=self.name,
            target=self._voice,
        )

    def _say_later(self, prio: int, text: str) -> None:
        self._seq += 1
        try:
            self._queue.put_nowait((prio, self._seq, text))
        except asyncio.QueueFull:
            log.debug("stream_mode: cola llena, se descarta: {}", text[:60])

    async def _read_loop(self) -> None:
        assert self._lines is not None
        while True:
            line = (await self._lines.get()).strip().rstrip(",")
            if not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            for item in chat_items(payload):
                mid = item_id(item)
                if mid is not None:
                    if mid in self._seen:
                        continue
                    self._seen.add(mid)
                said = classify(item, self._max_chars)
                if said is not None:
                    log.info("stream_mode: prio={} {}", said[0], said[1])
                    self._say_later(*said)
            if len(self._seen) > 20000:
                # ponytail: dedupe en RAM sin TTL; recorta a lo viejo si crece de más
                self._seen = set(list(self._seen)[-5000:])

    async def _speak_loop(self) -> None:
        while True:
            # Espera un mensaje hasta la próxima ventana; si no llega nada, frase.
            try:
                _, _, text = await asyncio.wait_for(
                    self._queue.get(), timeout=self._rng.uniform(self._min_s, self._max_s)
                )
            except TimeoutError:
                if not self._filler or not self._phrases:
                    continue
                text = self._rng.choice(self._phrases)
            try:
                await self.say(text)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                log.warning("stream_mode: say failed ({}), keep going", error)


def _demo() -> None:
    """Check runnable sin red ni audio: python -m hipotenusa.plugins.system.stream_mode."""
    text_item = {"liveChatTextMessageRenderer": {"id": "1", "authorName": {"simpleText": "@tester"},
                 "message": {"runs": [{"text": "hola hipotenusa, se escucha?"}]}}}
    paid = {"liveChatPaidMessageRenderer": {"id": "2", "authorName": {"simpleText": "@dona"},
            "purchaseAmountText": {"simpleText": "$5.00"},
            "message": {"runs": [{"text": "morite alien"}]}}}
    owner = {"liveChatTextMessageRenderer": {"id": "3", "authorName": {"simpleText": "@dueno"},
             "authorBadges": [{"liveChatAuthorBadgeRenderer": {"tooltip": "Owner"}}],
             "message": {"runs": [{"text": "hola"}]}}}
    link = {"liveChatTextMessageRenderer": {"id": "4", "authorName": {"simpleText": "@spam"},
            "message": {"runs": [{"text": "https://ejemplo.com/no-leas-esto"}]}}}

    paid_said = classify(paid)
    assert paid_said is not None and paid_said[0] == 0 and "5.00" in paid_said[1]
    assert classify(text_item) == (1, "tester dice: hola hipotenusa, se escucha?")
    assert classify(owner) is None and classify(link) == (1, "spam dice: un link")

    line = json.dumps({"replayChatItemAction": {"actions": [{"addChatItemAction": {"item": paid}}]}})
    items = chat_items(json.loads(line.rstrip(",")))
    assert len(items) == 1 and item_id(items[0]) == "2"
    assert chat_items({"actions": [{"addChatItemAction": {"item": text_item}}]})

    async def order() -> list[str]:
        plugin = StreamModePlugin(settings=None)
        plugin._say_later(1, "mensaje-1")
        plugin._say_later(1, "mensaje-2")
        plugin._say_later(0, "donacion")
        return [(await plugin._queue.get())[2] for _ in range(3)]

    assert asyncio.run(order()) == ["donacion", "mensaje-1", "mensaje-2"]
    assert StreamModePlugin._run is Plugin._run  # no pisa el worker del base
    print("stream_mode OK")


if __name__ == "__main__":
    _demo()
