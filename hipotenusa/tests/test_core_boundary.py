"""Gate de frontera arquitectónica del Core de Hipotenusa.

Verifica mediante análisis estático de AST (sin importar hipotenusa) que ningún
módulo bajo hipotenusa/core/ importe hacia hipotenusa.voices o hipotenusa.mask, salvaguardando
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
    ("hipotenusa/core/workflow_engine.py", 290, "hipotenusa.voices.base"),
    # Deuda aceptada: import lazy dentro de _scan_voices para instanciar agentes configurados
    ("hipotenusa/core/discovery.py", 101, "hipotenusa.voices.factory"),
]


def imports_prohibidos(
    core_dir: Path,
    excepciones: list[tuple[str, int, str]] | None = None,
    repo_root: Path | None = None,
) -> list[tuple[str, int, str]]:
    """Escanea core_dir buscando imports a hipotenusa.voices o hipotenusa.mask.

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
                        name == "hipotenusa.voices"
                        or name.startswith("hipotenusa.voices.")
                        or name == "hipotenusa.mask"
                        or name.startswith("hipotenusa.mask.")
                    ):
                        item = (rel_path, node.lineno, name)
                        if item not in exc_set:
                            hallazgos.append(item)

            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    mod = node.module
                    if (
                        mod == "hipotenusa.voices"
                        or mod.startswith("hipotenusa.voices.")
                        or mod == "hipotenusa.mask"
                        or mod.startswith("hipotenusa.mask.")
                    ):
                        item = (rel_path, node.lineno, mod)
                        if item not in exc_set:
                            hallazgos.append(item)
                    elif mod == "hipotenusa":
                        for alias in node.names:
                            sub = alias.name
                            if (
                                sub == "voices"
                                or sub.startswith("voices.")
                                or sub == "mask"
                                or sub.startswith("mask.")
                            ):
                                full_mod = f"hipotenusa.{sub}"
                                item = (rel_path, node.lineno, full_mod)
                                if item not in exc_set:
                                    hallazgos.append(item)

    return sorted(hallazgos, key=lambda x: (x[0], x[1], x[2]))


def test_core_no_importa_voices_ni_mask():
    """El árbol real de hipotenusa/core/ no debe tener imports prohibidos fuera de EXCEPCIONES."""
    repo_root = Path(__file__).resolve().parents[2]
    core_dir = repo_root / "hipotenusa" / "core"
    prohibidos = imports_prohibidos(core_dir, EXCEPCIONES, repo_root=repo_root)

    assert not prohibidos, (
        f"Se encontraron imports prohibidos en hipotenusa/core/ hacia hipotenusa.voices o hipotenusa.mask: "
        f"{prohibidos}. Si un import nuevo es intencional, debe declararse en la lista "
        f"EXCEPCIONES de hipotenusa/tests/test_core_boundary.py en el mismo commit explicando el motivo."
    )


def test_excepciones_no_son_obsoletas():
    """Cada entrada de EXCEPCIONES debe seguir existiendo exactamente en archivo:línea con ese módulo."""
    repo_root = Path(__file__).resolve().parents[2]
    core_dir = repo_root / "hipotenusa" / "core"
    todos_los_imports = imports_prohibidos(core_dir, excepciones=[], repo_root=repo_root)
    todos_set = set(todos_los_imports)

    for exc in EXCEPCIONES:
        rel_path, lineno, mod = exc
        assert exc in todos_set, (
            f"La excepción declarada {exc} es obsoleta o cambió de línea. "
            f"El archivo {rel_path} ya no contiene el import a {mod} en la línea {lineno}. "
            f"Actualice la lista EXCEPCIONES en hipotenusa/tests/test_core_boundary.py para reflejar el estado actual."
        )


def test_gate_detecta_import_prohibido(tmp_path: Path):
    """Prueba que el gate detecta tanto 'import' como 'from ... import' cuando aparecen en core."""
    fake_core = tmp_path / "hipotenusa" / "core"
    fake_core.mkdir(parents=True)
    fake_file = fake_core / "fake_module.py"
    fake_file.write_text(
        "import hipotenusa.mask\n"
        "from hipotenusa.voices.base import Dummy\n",
        encoding="utf-8",
    )

    hallazgos = imports_prohibidos(fake_core, excepciones=[], repo_root=tmp_path)
    assert len(hallazgos) == 2
    assert ("hipotenusa/core/fake_module.py", 1, "hipotenusa.mask") in hallazgos
    assert ("hipotenusa/core/fake_module.py", 2, "hipotenusa.voices.base") in hallazgos
