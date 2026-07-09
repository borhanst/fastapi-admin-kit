"""Interactive project scaffolding for FastAPI projects with uv."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

LAYOUTS = {
    "flat": {
        "name": "Flat (main.py in root)",
        "description": "Simple layout — main.py at project root",
        "files": {
            "main.py": '''\
from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting up...")
    yield
    print("Shutting down...")


app = FastAPI(title="{project_name}", lifespan=lifespan)


@app.get("/")
async def root():
    return {{"message": "Hello from {project_name}!"}}


@app.get("/health")
async def health():
    return {{"status": "ok"}}
''',
        },
    },
    "app": {
        "name": "App directory (app/main.py)",
        "description": "Recommended — app/ package with __init__.py",
        "files": {
            "app/__init__.py": "",
            "app/main.py": '''\
from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting up...")
    yield
    print("Shutting down...")


app = FastAPI(title="{project_name}", lifespan=lifespan)


@app.get("/")
async def root():
    return {{"message": "Hello from {project_name}!"}}


@app.get("/health")
async def health():
    return {{"status": "ok"}}
''',
        },
    },
    "src": {
        "name": "Src layout (src/app/main.py)",
        "description": "Src layout — installable package with src/ root",
        "files": {
            "src/__init__.py": "",
            "src/app/__init__.py": "",
            "src/app/main.py": '''\
from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting up...")
    yield
    print("Shutting down...")


app = FastAPI(title="{project_name}", lifespan=lifespan)


@app.get("/")
async def root():
    return {{"message": "Hello from {project_name}!"}}


@app.get("/health")
async def health():
    return {{"status": "ok"}}
''',
        },
    },
}


def _pyproject_content(project_name: str, layout: str, description: str = "") -> str:
    """Generate pyproject.toml content."""
    entrypoints = {
        "flat": "main:app",
        "app": "app.main:app",
        "src": "app.main:app",
    }
    packages_val = {
        "flat": "main.py",
        "app": "app",
        "src": "src/app",
    }

    return f'''\
[project]
name = "{project_name}"
version = "0.1.0"
description = "{description or project_name}"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "fastapi[standard]>=0.115.0",
    "uvicorn[standard]>=0.30.0",
]

[tool.hatch.build.targets.wheel]
packages = ["{packages_val[layout]}"]

[tool.fastapi]
entrypoint = "{entrypoints[layout]}"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 100
target-version = "py311"
'''


def _gitignore_content() -> str:
    return '''\
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.venv/
.env
*.db
*.sqlite3
'''


def _python_version_content() -> str:
    return "3.11\n"


def _input(prompt: str, default: str = "") -> str:
    """Read user input with optional default."""
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def _select(options: list[str], prompt: str) -> int:
    """Display numbered options and return selected index."""
    print(f"\n{prompt}")
    for i, opt in enumerate(options, 1):
        print(f"  {i}) {opt}")
    while True:
        choice = input("\nEnter number: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return int(choice) - 1
        print(f"Invalid choice. Enter 1-{len(options)}.")


def _run(cmd: list[str], cwd: Path) -> bool:
    """Run a subprocess, return True on success."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error running {' '.join(cmd)}:")
        print(result.stderr or result.stdout)
        return False
    return True


def scaffold_project(
    project_name: str | None = None,
    layout: str | None = None,
    directory: str | None = None,
    skip_venv: bool = False,
    skip_git: bool = False,
) -> Path:
    """
    Create a new FastAPI project.

    Interactive when args are missing; non-interactive when all provided.
    Returns the project directory path.
    """
    # --- Collect inputs interactively ---
    if not project_name:
        project_name = _input("Project name", "my-fastapi-app")

    if not layout:
        options = [f"{LAYOUTS[k]['name']} — {LAYOUTS[k]['description']}" for k in LAYOUTS]
        idx = _select(options, "Select project structure:")
        layout = list(LAYOUTS.keys())[idx]

    project_dir = Path(directory or project_name).resolve()

    if project_dir.exists() and any(project_dir.iterdir()):
        confirm = _input(f"'{project_dir}' already exists. Overwrite?", "n")
        if confirm.lower() not in ("y", "yes"):
            print("Aborted.")
            sys.exit(1)

    project_dir.mkdir(parents=True, exist_ok=True)

    # --- Write files ---
    print(f"\nCreating project '{project_name}' in {project_dir} ...")

    # pyproject.toml
    (project_dir / "pyproject.toml").write_text(_pyproject_content(project_name, layout))

    # .gitignore
    (project_dir / ".gitignore").write_text(_gitignore_content())

    # .python-version
    (project_dir / ".python-version").write_text(_python_version_content())

    # README.md
    (project_dir / "README.md").write_text(f"# {project_name}\n\nA FastAPI project.\n")

    # Layout files
    layout_data = LAYOUTS[layout]
    for rel_path, content in layout_data["files"].items():
        file_path = project_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content.format(project_name=project_name))

    print("Project files created.")

    # --- uv init ---
    if not skip_venv:
        print("\nSetting up virtual environment with uv...")
        if not _run(["uv", "venv"], project_dir):
            print("Warning: uv venv creation failed. Create manually: uv venv")
        else:
            print("  Virtual environment created.")

        print("Installing dependencies...")
        if not _run(["uv", "sync"], project_dir):
            # uv sync may fail if uv.lock doesn't exist yet, try uv pip install
            print("  Trying uv pip install...")
            _run(["uv", "pip", "install", "-e", "."], project_dir)
        else:
            print("  Dependencies installed.")

    # --- git init ---
    if not skip_git:
        print("\nInitializing git repository...")
        _run(["git", "init"], project_dir)
        _run(["git", "add", "."], project_dir)
        _run(["git", "commit", "-m", "Initial commit"], project_dir)
        print("  Git repository initialized.")

    # --- Summary ---
    entrypoints = {"flat": "main:app", "app": "app.main:app", "src": "app.main:app"}
    print(f"\nDone! Project '{project_name}' is ready.\n")
    print(f"  cd {project_dir.name}")
    if not skip_venv:
        print("  source .venv/bin/activate  # or: uv run fastapi dev")
    print("  fastapi dev                # starts at http://localhost:8000")
    print(f"\n  Entrypoint: {entrypoints[layout]}")
    print(f"  Layout: {LAYOUTS[layout]['name']}")

    return project_dir
