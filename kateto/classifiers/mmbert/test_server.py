import numpy as np

from kateto.classifiers.mmbert.server import PrototypeClassifier


def test_workflow_selection_uses_the_best_available_candidate(monkeypatch) -> None:
    monkeypatch.setattr(
        "kateto.classifiers.mmbert.server._embed",
        lambda _session, _tokenizer, texts: np.array(
            [[1.0, 0.0], [0.9, 0.1], [0.1, 0.9]],
            dtype=np.float32,
        ),
    )
    classifier = PrototypeClassifier.__new__(PrototypeClassifier)
    classifier.session = None
    classifier.tokenizer = None
    result = classifier.select_workflow(
        "start a new project",
        [
            {"name": "project-initiation", "voice": "jane", "description": "start"},
            {"name": "sprint-execution", "voice": "conquest", "description": "run"},
        ],
    )

    assert result[0] == "project-initiation"
    assert result[1] == "jane"
