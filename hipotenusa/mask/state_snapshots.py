from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

MIB: Final = 1024 * 1024
DEFAULT_CORRECTION_WINDOW_MS: Final = 400.0
DEFAULT_PREFILL_TOKEN_BUDGET: Final = 5
DEFAULT_PREFILL_MS_PER_TOKEN: Final = 0.8  # 4 ms / 5 tokens = presupuesto del handoff

# Costo medido/del handoff: los DOS snapshots por agente, no uno.
SNAPSHOT_COST_MIB: Final[dict[str, float]] = {"0.4B": 3.0, "1.5B": 12.0}


class SnapshotStateError(RuntimeError):
    """Error de ciclo de vida o transicion invalida en TurnSnapshots."""


@dataclass(frozen=True)
class MemoryReport:
    model_label: str
    per_agent_bytes: int
    agents: int
    total_bytes: int
    snapshots_per_agent: int = 2


def snapshot_cost(model_label: str = "0.4B", agents: int = 4) -> MemoryReport:
    """MemoryReport con snapshots_per_agent=2; KeyError -> ValueError con el label."""
    try:
        cost_mib = SNAPSHOT_COST_MIB[model_label]
    except KeyError as err:
        raise ValueError(f"Modelo desconocido: {model_label}") from err

    per_agent_bytes = int(cost_mib * MIB)
    total_bytes = per_agent_bytes * agents
    return MemoryReport(
        model_label=model_label,
        per_agent_bytes=per_agent_bytes,
        agents=agents,
        total_bytes=total_bytes,
        snapshots_per_agent=2,
    )


@dataclass(frozen=True)
class CorrectionResult:
    restored: bool
    within_window: bool
    replayed_tokens: int
    estimated_ms: float
    within_budget: bool


@dataclass(frozen=True)
class BargeInResult:
    state: object  # estado resultante (el "S_barge_in")
    kept_tokens: int  # tokens cuyo audio salio antes del corte
    dropped_tokens: int  # tokens generados cuyo audio NO salio
    replayed_tokens: int


class StateBackend(Protocol):
    def clone(self, state: object) -> object: ...
    def advance(self, state: object, tokens: Sequence[int]) -> object: ...


class ListStateBackend:
    """Backend trivial para tests: el estado es una tupla de ints."""

    def clone(self, state: Sequence[int]) -> tuple[int, ...]:
        return tuple(state)

    def advance(self, state: Sequence[int], tokens: Sequence[int]) -> tuple[int, ...]:
        return tuple(state) + tuple(tokens)


class TurnSnapshots:
    """Administra los dos snapshots de estado RWKV: S_turn_start y S_barge_in."""

    def __init__(
        self,
        backend: StateBackend,
        *,
        correction_window_ms: float = DEFAULT_CORRECTION_WINDOW_MS,
        prefill_token_budget: int = DEFAULT_PREFILL_TOKEN_BUDGET,
        prefill_ms_per_token: float = DEFAULT_PREFILL_MS_PER_TOKEN,
    ) -> None:
        self._backend = backend
        self._correction_window_ms = float(correction_window_ms)
        self._prefill_token_budget = int(prefill_token_budget)
        self._prefill_ms_per_token = float(prefill_ms_per_token)

        self._state: object = None
        self._turn_start: object = None
        self._barge_in_base: object = None
        self._emitted: list[tuple[int, float, float]] = []

    # turno del usuario
    def begin_turn(self, state: object) -> None:
        """Guarda S_turn_start = backend.clone(state). El estado vivo pasa a ser `state`."""
        # Se clona explicitamente para blindar S_turn_start ante cualquier mutacion externa.
        self._turn_start = self._backend.clone(state)
        self._state = state
        self._barge_in_base = None
        self._emitted.clear()

    def prefill_partial(self, tokens: Sequence[int]) -> object:
        """Prefill incremental mientras el usuario habla. Devuelve el estado vivo."""
        if self._turn_start is None:
            raise SnapshotStateError("No hay turno iniciado para prefill")
        self._state = self._backend.advance(self._state, tokens)
        return self._state

    def correct_partial(
        self, corrected_tokens: Sequence[int], *, at_ms: float
    ) -> CorrectionResult:
        """Si at_ms <= correction_window_ms: estado vivo = clone(S_turn_start) + prefill de
        SOLO corrected_tokens. Si at_ms > ventana: no toca el estado, within_window=False,
        restored=False. within_budget = replayed <= prefill_token_budget.
        estimated_ms = replayed * prefill_ms_per_token."""
        if self._turn_start is None:
            raise SnapshotStateError("No hay turno iniciado para corregir")

        if at_ms > self._correction_window_ms:
            return CorrectionResult(
                restored=False,
                within_window=False,
                replayed_tokens=0,
                estimated_ms=0.0,
                within_budget=True,
            )

        replayed = len(corrected_tokens)
        estimated_ms = replayed * self._prefill_ms_per_token
        within_budget = replayed <= self._prefill_token_budget

        # Restauracion desde snapshot limpio: nunca mutamos el snapshot original.
        base = self._backend.clone(self._turn_start)
        self._state = self._backend.advance(base, corrected_tokens)

        return CorrectionResult(
            restored=True,
            within_window=True,
            replayed_tokens=replayed,
            estimated_ms=estimated_ms,
            within_budget=within_budget,
        )

    # respuesta de Chaman
    def begin_response(self) -> None:
        """Exige begin_turn previo (si no: SnapshotStateError). Guarda la base de barge-in =
        clone(estado vivo) — el estado en el ms en que empieza a generarse la respuesta.
        Limpia los tokens emitidos."""
        if self._turn_start is None:
            raise SnapshotStateError("Exige begin_turn previo antes de begin_response")

        self._barge_in_base = self._backend.clone(self._state)
        self._emitted.clear()

    def note_emitted(
        self, token: int, *, audio_start_ms: float, audio_end_ms: float
    ) -> object:
        """Registra un token que se mandó al TTS con la ventana de audio en que suena, y lo
        avanza en el estado vivo (la generación NO espera al TTS). Devuelve el estado vivo."""
        if self._barge_in_base is None:
            raise SnapshotStateError("No se inicio la respuesta (falta begin_response)")

        self._emitted.append((token, audio_start_ms, audio_end_ms))
        self._state = self._backend.advance(self._state, [token])
        return self._state

    def barge_in(self, *, cut_ms: float) -> BargeInResult:
        """Estado vivo = clone(base de barge-in) + prefill SOLO de los tokens con
        audio_start_ms <= cut_ms. NUNCA restaura S_turn_start. Idempotente: llamarla dos veces
        con el mismo cut_ms da el mismo estado y los mismos conteos."""
        if self._barge_in_base is None:
            raise SnapshotStateError("No hay respuesta activa para barge-in")

        kept_tokens: list[int] = []
        dropped_count = 0

        for tok, start_ms, _ in self._emitted:
            if start_ms <= cut_ms:
                kept_tokens.append(tok)
            else:
                dropped_count += 1

        # Reconstruccion: base limpia de inicio de respuesta + tokens audibles.
        restored = self._backend.clone(self._barge_in_base)
        self._state = self._backend.advance(restored, kept_tokens)

        return BargeInResult(
            state=self._state,
            kept_tokens=len(kept_tokens),
            dropped_tokens=dropped_count,
            replayed_tokens=len(kept_tokens),
        )

    @property
    def state(self) -> object:
        return self._state

    @property
    def turn_start(self) -> object:
        """S_turn_start (copia guardada)."""
        if self._turn_start is None:
            return None
        return self._backend.clone(self._turn_start)

    def reset(self) -> None:
        """Limpia todo (para reuso entre turnos)."""
        self._state = None
        self._turn_start = None
        self._barge_in_base = None
        self._emitted.clear()
