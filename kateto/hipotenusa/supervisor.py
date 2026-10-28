from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from .config import Expose, Profile, Sidecar
from .forward import proxy_client

WATCH_INTERVAL_S = 1.0
MAX_RESTARTS = 5
RESTART_BACKOFF_S = (1.0, 2.0, 4.0, 8.0, 16.0)
EXPOSE_FAILURES_BEFORE_REBIND = 2


def health(url: str, expect: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            return expect in response.read().decode(errors="replace")
    except Exception:
        return False


class Supervisor:
    def __init__(
        self,
        profile: Profile,
        children: list[tuple[str, subprocess.Popen[Any]]],
        adopted: list[str],
        servers: list[asyncio.AbstractServer],
        *,
        health_fn: Callable[[str, str], bool] = health,
        spawn: Callable[[Sidecar], subprocess.Popen[Any]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        emit: Callable[..., None] | None = None,
        max_restarts: int = MAX_RESTARTS,
        backoff: tuple[float, ...] = RESTART_BACKOFF_S,
        watch_interval_s: float = WATCH_INTERVAL_S,
    ) -> None:
        # children/adopted/servers son las MISMAS listas de run(): se mutan in
        # place (append/removal/reemplazo), nunca se reemplazan por listas nuevas.
        self.profile = profile
        self._children = children
        self._adopted = adopted
        self._servers = servers
        self._health_fn = health_fn
        self._spawn = spawn if spawn is not None else self._default_spawn
        self._clock = clock
        self._emit = emit if emit is not None else self._default_emit
        self._max_restarts = max_restarts
        self._backoff = backoff
        self._watch_interval_s = watch_interval_s
        self._health_failures: dict[str, int] = {}
        self._restarts: dict[str, int] = {}
        self._next_attempt_at: dict[str, float] = {}
        self._expose_failures: dict[str, int] = {}
        self._exhausted: set[str] = set()
        self._spawn_failed: set[str] = set()
        self._expose_broken: set[str] = set()
        self._rebind_failed: set[str] = set()
        self._map_expose_servers()

    @property
    def children(self) -> list[tuple[str, subprocess.Popen[Any]]]:
        return self._children

    @property
    def adopted(self) -> list[str]:
        return self._adopted

    @property
    def servers(self) -> list[asyncio.AbstractServer]:
        # no estaba en la lista de propiedades del contrato, pero el test de expose lo lee
        return self._servers

    @staticmethod
    def _default_spawn(item: Sidecar) -> subprocess.Popen[Any]:
        log_dir = Path.home() / ".local/state/hipotenusa"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / f"{item.name}.log").open("ab") as log:
            return subprocess.Popen(item.argv, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

    @staticmethod
    def _default_emit(message: str, level: str = "info") -> None:
        if level == "error":
            logger.error(message)
        else:
            logger.info(message)

    def _forget(self, name: str) -> None:
        # reset de contadores/flags cuando el sidecar vuelve a estar sano
        self._health_failures[name] = 0
        self._restarts[name] = 0
        self._next_attempt_at.pop(name, None)
        self._exhausted.discard(name)
        self._spawn_failed.discard(name)

    def _child_index(self, name: str) -> int | None:
        for index, (child_name, _) in enumerate(self._children):
            if child_name == name:
                return index
        return None

    async def tick(self) -> None:
        # Una pasada de supervision, sin sleeps. Cada item va envuelto asi un
        # error aca no apaga el watchdog (ni el runtime; solo capta Exception,
        # CancelledError sigue subiendo y apaga el watchdog solo).
        for item in self.profile.sidecars:
            try:
                self._supervise_sidecar(item)
            except Exception as exc:
                self._emit(f"supervisor: sidecar '{item.name}': {exc}", "error")
        for item in self.profile.exposes:
            try:
                await self._supervise_expose(item)
            except Exception as exc:
                self._emit(f"supervisor: expose '{item.name}': {exc}", "error")

    def _supervise_sidecar(self, item: Sidecar) -> None:
        name = item.name
        if name in self._adopted:
            if self._health_fn(item.health_url, item.health_expect):
                self._forget(name)
                return
            failures = self._health_failures.get(name, 0) + 1
            self._health_failures[name] = failures
            if failures < EXPOSE_FAILURES_BEFORE_REBIND:
                return
            if self._clock() < self._next_attempt_at.get(name, 0.0):
                return
            try:
                proc = self._spawn(item)
            except OSError as exc:
                if name not in self._spawn_failed:
                    self._spawn_failed.add(name)
                    self._emit(f"sidecar '{name}' no se puede relanzar: {exc}", "error")
                self._next_attempt_at[name] = self._clock() + self._backoff[min(failures - 1, len(self._backoff) - 1)]
                return
            self._adopted.remove(name)
            self._children.append((name, proc))
            self._spawn_failed.discard(name)
            self._emit(f"sidecar '{name}' repuesto, pid={proc.pid}")
            return
        index = self._child_index(name)
        if index is None:
            return
        _, proc = self._children[index]
        if proc.poll() is None:
            # vivo: NUNCA se lo toca; solo se resetea si ademas volvio a estar sano
            if self._health_fn(item.health_url, item.health_expect):
                self._forget(name)
            return
        now = self._clock()
        if now < self._next_attempt_at.get(name, 0.0):
            return
        restarts = self._restarts.get(name, 0)
        if restarts >= self._max_restarts:
            if name not in self._exhausted:
                self._exhausted.add(name)
                self._emit(f"sidecar '{name}' sin reponer tras {self._max_restarts} intentos", "error")
            return
        try:
            new_proc = self._spawn(item)
        except OSError as exc:
            if name not in self._spawn_failed:
                self._spawn_failed.add(name)
                self._emit(f"sidecar '{name}' no se puede relanzar: {exc}", "error")
            self._next_attempt_at[name] = now + self._backoff[min(restarts, len(self._backoff) - 1)]
            return
        self._children[index] = (name, new_proc)
        self._restarts[name] = restarts + 1
        self._next_attempt_at[name] = now + self._backoff[min(restarts, len(self._backoff) - 1)]
        self._spawn_failed.discard(name)
        self._emit(f"sidecar '{name}' repuesto, pid={new_proc.pid}")

    def _map_expose_servers(self) -> None:
        # Apareo expose<->server resuelto UNA vez en __init__: server.sockets
        # queda vacia despues de close(), y run() salta los exposes opcionales
        # sin apuntar server. Con la lista 1:1 normal cae en el mismo indice.
        self._expose_server_index: dict[str, int | None] = {}
        free = list(range(len(self._servers)))
        for item in self.profile.exposes:
            port = int(item.listen.rsplit(":", 1)[1])
            chosen = next(
                (index for index in free if port in {l.getsockname()[1] for l in (self._servers[index].sockets or ())}),
                None,
            )
            if chosen is not None:
                free.remove(chosen)
            self._expose_server_index[item.name] = chosen

    async def _supervise_expose(self, item: Expose) -> None:
        if not self._health_fn(item.health_url, item.health_expect):
            return  # upstream caido: el listener no es el problema, no rebindear
        index = self._expose_server_index.get(item.name)
        if index is None:
            return
        host, port = item.listen.rsplit(":", 1)
        probe_host = "127.0.0.1" if host == "0.0.0.0" else host
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(probe_host, int(port)), 0.5)
        except (OSError, asyncio.TimeoutError):
            writer = None
        else:
            writer.close()  # socket de prueba cerrado enseguida
            self._expose_failures[item.name] = 0
            self._expose_broken.discard(item.name)
            self._rebind_failed.discard(item.name)
            return
        failures = self._expose_failures.get(item.name, 0) + 1
        self._expose_failures[item.name] = failures
        if item.name not in self._expose_broken:
            self._expose_broken.add(item.name)
            self._emit(f"expose '{item.name}' no acepta conexiones: rebindeando", "error")
        if failures < EXPOSE_FAILURES_BEFORE_REBIND:
            return
        old = self._servers[index]
        try:
            old.close()
            await old.wait_closed()
            target_host, target_port = item.target.rsplit(":", 1)
            new_server = await asyncio.start_server(
                lambda r, w, h=target_host, p=int(target_port): proxy_client(r, w, h, p),
                host, int(port),
            )
        except OSError as exc:
            if item.name not in self._rebind_failed:
                self._rebind_failed.add(item.name)
                self._emit(f"expose '{item.name}' no se pudo rebindear en {item.listen}: {exc}", "error")
            return
        self._servers[index] = new_server
        self._expose_failures[item.name] = 0
        self._expose_broken.discard(item.name)
        self._rebind_failed.discard(item.name)
        self._emit(f"expose '{item.name}' rebindeado en {item.listen}")

    async def serve(self) -> None:
        try:
            while True:
                await self.tick()
                await asyncio.sleep(self._watch_interval_s)
        except asyncio.CancelledError:
            pass  # apagado limpio del watchdog, no enrera al runtime


async def run(profile: Profile, *, json_output: bool = False) -> None:
    children: list[tuple[str, subprocess.Popen[Any]]] = []
    adopted: list[str] = []
    servers: list[asyncio.AbstractServer] = []
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    installed_handlers: list[signal.Signals] = []
    watch: asyncio.Task[None] | None = None
    if task is not None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, task.cancel)
                installed_handlers.append(sig)
            except (NotImplementedError, RuntimeError):
                pass
    try:
        for item in profile.sidecars:
            if item.adopt_if_healthy and health(item.health_url, item.health_expect):
                adopted.append(item.name)
                continue
            log_dir = Path.home() / ".local/state/hipotenusa"
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
                log = (log_dir / f"{item.name}.log").open("ab")
            except OSError as exc:
                raise RuntimeError(f"cannot create Hipotenusa log for {item.name}: {exc}") from exc
            proc = subprocess.Popen(item.argv, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            children.append((item.name, proc))
            deadline = time.monotonic() + item.ready_timeout_s
            delay = .2
            while time.monotonic() < deadline and proc.poll() is None:
                if health(item.health_url, item.health_expect):
                    break
                await asyncio.sleep(delay)
                delay = min(delay * 1.5, 3)
            else:
                if item.required:
                    tail = "\n".join((log_dir / f"{item.name}.log").read_text(errors="replace").splitlines()[-20:])
                    returncode = proc.poll()
                    if returncode is None:
                        os.killpg(proc.pid, signal.SIGTERM)
                    raise RuntimeError(f"{item.name} failed readiness (returncode={returncode}):\n{tail}")
        for item in profile.exposes:
            if not health(item.health_url, item.health_expect):
                if item.required:
                    raise RuntimeError(f"expose target unhealthy: {item.name}")
                continue
            host, port = item.listen.rsplit(":", 1)
            try:
                target_host, target_port = item.target.rsplit(":", 1)
                server = await asyncio.start_server(lambda r, w, h=target_host, p=int(target_port): proxy_client(r, w, h, p), host, int(port))
            except OSError as exc:
                occupant = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True).stdout
                raise RuntimeError(f"cannot bind {item.listen}; ss -ltnp: {occupant}") from exc
            servers.append(server)
        supervisor = Supervisor(profile, children, adopted, servers)
        watch = asyncio.create_task(supervisor.serve())
        from kateto.core.config import load_config
        from kateto.run_mode import run_event_runtime
        config_dir = Path.home() / ".config/kateto"
        overrides = dict(profile.overrides)
        overrides.update({"plugin.http_server.host": profile.host, "plugin.http_server.port": profile.port, "plugin.http_server.token": profile.token})
        loaded = load_config(config_dir=config_dir, overrides=overrides)
        if json_output:
            print(json.dumps({"pids": [p.pid for _, p in children], "adopted": adopted, "exposed": [e.listen for e in profile.exposes], "runtime": f"{profile.host}:{profile.port}"}), flush=True)
        await run_event_runtime(loaded)
    finally:
        if watch is not None:
            # apagar primero el watchdog, despues el teardown de hoy
            watch.cancel()
            await asyncio.gather(watch, return_exceptions=True)
        for sig in installed_handlers:
            loop.remove_signal_handler(sig)
        for server in servers:
            server.close()
            await server.wait_closed()
        for _, proc in children:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
