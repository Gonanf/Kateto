"""Gate de frontera arquitectónica del Core de Kateto.

Verifica mediante análisis estático de AST (sin importar kateto) que ningún
módulo bajo kateto/core/ importe hacia kateto.voices o kateto.mask, salvaguardando
el principio de que el Core no debe acoplarse hacia capas superiores.
"""
from __future__ import annotations

import ast
from pathlib import Path
import pytest

# Lista cerrada de excepciones de deuda técnica aceptada hoy.
# Cada entrada debe mantenerse actualizada con (archivo_relativo, línea_exacta, módulo_importado).
# Si un import cambia de línea o se remueve, test_excepciones_no_son_obsoletas fallará.
EXCEPCIONES: list[tuple[str, int, str]] = [
    # Deuda aceptada: import lazy dentro de WorkflowEngine._voice_target para resolver display_name
    ("kateto/core/workflow_engine.py", 290, "kateto.voices.base"),
    # Deuda aceptada: import lazy dentro de _scan_voices para instanciar agentes configurados
    ("kateto/core/discovery.py", 101, "kateto.voices.factory"),
]


def imports_prohibidos(
    core_dir: Path,
    excepciones: list[tuple[str, int, str]] | None = None,
    repo_root: Path | None = None,
) -> list[tuple[str, int, str]]:
    """Escanea core_dir buscando imports a kateto.voices o kateto.mask.

    Retorna una lista de tuplas (archivo_relativo, línea, módulo_importado) que no
    estén contempladas en la lista de excepciones.
    """
    exc_set = set(excepciones or [])
    base_root = repo_root if repo_root is not None else core_dir.resolve().parents[1]
    hallazgos: list[tuple[str, int, str]] = []

    for py_file in sorted(core_dir.rglob("*.py")):
        rel_path = py_file.resolve().relative_to(base_root.resolve()).as_posix()
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError as err:
            pytest.fail(f"Error de sintaxis parseando {rel_path}: {err}")

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if (
                        name == "kateto.voices"
                        or name.startswith("kateto.voices.")
                        or name == "kateto.mask"
                        or name.startswith("kateto.mask.")
                    ):
                        item = (rel_path, node.lineno, name)
                        if item not in exc_set:
                            hallazgos.append(item)

            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    mod = node.module
                    if (
                        mod == "kateto.voices"
                        or mod.startswith("kateto.voices.")
                        or mod == "kateto.mask"
                        or mod.startswith("kateto.mask.")
                    ):
                        item = (rel_path, node.lineno, mod)
                        if item not in exc_set:
                            hallazgos.append(item)
                    elif mod == "kateto":
                        for alias in node.names:
                            sub = alias.name
                            if (
                                sub == "voices"
                                or sub.startswith("voices.")
                                or sub == "mask"
                                or sub.startswith("mask.")
                            ):
                                full_mod = f"kateto.{sub}"
                                item = (rel_path, node.lineno, full_mod)
                                if item not in exc_set:
                                    hallazgos.append(item)

    return sorted(hallazgos, key=lambda x: (x[0], x[1], x[2]))


def test_core_no_importa_voices_ni_mask():
    """El árbol real de kateto/core/ no debe tener imports prohibidos fuera de EXCEPCIONES."""
    repo_root = Path(__file__).resolve().parents[2]
    core_dir = repo_root / "kateto" / "core"
    prohibidos = imports_prohibidos(core_dir, EXCEPCIONES, repo_root=repo_root)

    assert not prohibidos, (
        f"Se encontraron imports prohibidos en kateto/core/ hacia kateto.voices o kateto.mask: "
        f"{prohibidos}. Si un import nuevo es intencional, debe declararse en la lista "
        f"EXCEPCIONES de kateto/tests/test_core_boundary.py en el mismo commit explicando el motivo."
    )


def test_excepciones_no_son_obsoletas():
    """Cada entrada de EXCEPCIONES debe seguir existiendo exactamente en archivo:línea con ese módulo."""
    repo_root = Path(__file__).resolve().parents[2]
    core_dir = repo_root / "kateto" / "core"
    todos_los_imports = imports_prohibidos(core_dir, excepciones=[], repo_root=repo_root)
    todos_set = set(todos_los_imports)

    for exc in EXCEPCIONES:
        rel_path, lineno, mod = exc
        assert exc in todos_set, (
            f"La excepción declarada {exc} es obsoleta o cambió de línea. "
            f"El archivo {rel_path} ya no contiene el import a {mod} en la línea {lineno}. "
            f"Actualice la lista EXCEPCIONES en kateto/tests/test_core_boundary.py para reflejar el estado actual."
        )


def test_gate_detecta_import_prohibido(tmp_path: Path):
    """Prueba que el gate detecta tanto 'import' como 'from ... import' cuando aparecen en core."""
    fake_core = tmp_path / "kateto" / "core"
    fake_core.mkdir(parents=True)
    fake_file = fake_core / "fake_module.py"
    fake_file.write_text(
        "import kateto.mask\n"
        "from kateto.voices.base import Dummy\n",
        encoding="utf-8",
    )

    hallazgos = imports_prohibidos(fake_core, excepciones=[], repo_root=tmp_path)
    assert len(hallazgos) == 2
    assert ("kateto/core/fake_module.py", 1, "kateto.mask") in hallazgos
    assert ("kateto/core/fake_module.py", 2, "kateto.voices.base") in hallazgos
