from __future__ import annotations
from typing import Any
from kateto.core.plugin import Plugin

class GameBridgePlugin(Plugin):
    """Bridge for external game harnesses -> Kateto overlay.
    Stores last events per game and forwards to VisualOverlay's broadcast.
    Exposed via HTTP POST /api/game/event (added in http_server.py).
    """
    def __init__(self, name: str = "game_bridge", settings=None):
        super().__init__(name=name, capabilities=("system", "game_bridge"))
        self._state: dict[str, dict[str, Any]] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._last_event: dict[str, Any] | None = None

    async def initialize(self) -> None:
        self._game_skills: dict[str, list[str]] = {}

    def _skills_for(self, game: str) -> list[str]:
        return self._game_skills.get(game, [])

    async def handle_event(self, data: dict[str, Any]) -> dict[str, Any]:
        """Called by HTTP endpoint. data = {game, event_type, voice_id, role, phase, text, rms, state}"""
        game = str(data.get("game") or "unknown")
        event_type = str(data.get("event_type") or "game_event")
        voice_id = str(data.get("voice_id") or "jane")
        role = data.get("role")
        phase = data.get("phase")
        text = str(data.get("text") or "")
        rms = data.get("rms_hint", data.get("rms", 0.12))
        state_payload = data.get("state") or {}

        # try float
        try:
            rms = float(rms)
        except Exception:
            rms = 0.12

        event = {
            "event": "game",
            "type": event_type,
            "game": game,
            "voice_id": voice_id,
            "role": role,
            "phase": phase,
            "text": text,
            "rms": rms,
            "state": state_payload,
        }
        if event_type == "game_start":
            skills = state_payload.get("skills") or state_payload.get("voyager_skills") or state_payload.get("tools")
            if isinstance(skills, list) and skills:
                self._game_skills[game] = [str(s) for s in skills]
                event["state"]["_active_skills"] = self._game_skills[game]
                try:
                    vt = self._manager.get_plugin("voyager_tools")
                    if vt and hasattr(vt, "on_game_start"):
                        import asyncio as _aio
                        _aio.create_task(vt.on_game_start(game, self._game_skills[game]))
                except: pass
        self._last_event = event
        self._state[game] = event
        hist = self._history.setdefault(game, [])
        hist.append(event)
        if len(hist) > 100:
            hist.pop(0)
        if event_type == "move_request" and game == "chess":
            try:
                import asyncio as _aio
                _aio.create_task(self._chess_llm(event))
            except Exception:
                pass
        return {"status": "ok", "game": game, "event_type": event_type, "event": event}

    async def _chess_llm(self, event: dict[str, Any]) -> None:
        import asyncio, random, re, os, httpx
        st = event.get("state") or {}
        fen = st.get("fen","")
        legal = st.get("legal_moves") or []
        req = st.get("request_id","")
        voice = event.get("voice_id") or "jane"
        if not fen or not legal:
            return
        url = os.getenv("LITELLM_URL", os.getenv("VOICE_LLM_ENDPOINT","http://127.0.0.1:11434/v1")) + "/chat/completions"
        model = os.getenv("LITELLM_MODEL", os.getenv("VOICE_LLM_MODEL","Kateto"))
        color = st.get("color","")
        opponent = st.get("opponent","")
        history = st.get("history","")
        prompt = f"Sos {voice} con {color} vs {opponent}. FEN:{fen} Historial:{history} Legales:{legal[:12]}. Respondé SOLO UCI de Legales."
        uci = None
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(url, json={"model":model,"messages":[{"role":"user","content":prompt}],"temperature":0.7})
                r.raise_for_status()
                txt = r.json()["choices"][0]["message"]["content"].strip().split()[0].lower()
                m = re.search(r"[a-h][1-8][a-h][1-8][qrbn]?", txt)
                if m: uci = m.group(0)
        except Exception:
            pass
        if not uci or uci not in legal:
            try:
                import chess
                legal_set = set(legal)
                if uci and uci not in legal_set:
                    uci = None
            except: pass
            if not uci:
                uci = random.choice(legal) if legal else "e2e4"
        await self.handle_event({"game":"chess","event_type":"game_action","voice_id":voice,"text":uci,"rms":0.2,"state":{"uci":uci,"request_id":req}})

    def get_state(self, game: str | None = None) -> dict[str, Any]:
        if game:
            return {"game": game, "current": self._state.get(game), "history": self._history.get(game, [])}
        return {"current": self._last_event, "by_game": self._state, "history": self._history}
