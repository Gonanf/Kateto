from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_space_packaging_declares_gradio_entrypoint_and_runtime_dependencies() -> None:
    # Given: the repository files that Hugging Face reads from the Space root.
    readme = (ROOT / "README.md").read_text()
    requirements = (ROOT / "requirements.txt").read_text()

    # When: the Space packaging contract is inspected statically.
    metadata = readme.split("---", 2)[1]

    # Then: Hugging Face can select the Gradio entrypoint without CPU Basic assumptions.
    assert "sdk: gradio" in metadata
    assert "app_file: space/app.py" in metadata
    assert "python_version: 3.12" in metadata
    assert "gradio==6.15.2" in requirements
    assert "spaces>=0.39.0" in requirements
    assert "cpu-basic" not in metadata
