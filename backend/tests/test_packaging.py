from pathlib import Path
import tomllib


BACKEND_DIR = Path(__file__).parents[1]


def test_backend_readme_is_package_local() -> None:
    metadata = tomllib.loads((BACKEND_DIR / "pyproject.toml").read_text())
    readme = metadata["project"]["readme"]

    assert isinstance(readme, str)
    readme_path = (BACKEND_DIR / readme).resolve()
    assert readme_path.is_relative_to(BACKEND_DIR.resolve())
    assert readme_path.is_file()
