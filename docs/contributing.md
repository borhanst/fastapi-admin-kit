# Contributing

Thank you for your interest in contributing to FastAPI Console!

## Development Setup

### Prerequisites

- Python 3.11 or higher
- uv (recommended) or pip

### Clone and Install

```bash
git clone https://github.com/borhanst/fastapi-console.git
cd fastapi-console
uv sync
```

### Run Tests

```bash
uv run pytest
```

### Run Linter

```bash
uv run ruff check .
uv run ruff format .
```

### Run Documentation Server

```bash
uv run mkdocs serve
```

Open `http://localhost:8000` in your browser.

## Project Structure

```
fastapi_admin_kit/
├── admin/          # Admin class and configuration
├── auth/           # Authentication and RBAC
├── audit/          # Audit logging
├── widgets/        # Form widgets
├── views/          # Route handlers
├── templates/      # Jinja2 templates
├── static/         # CSS, JS, images
└── plugins/        # Plugin system
```

## Code Style

We use Ruff for linting and formatting:

- Line length: 100
- Target: Python 3.11
- Rules: E, F, I, N, UP

## Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests and linter
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## Reporting Issues

Use the GitHub issue tracker to report bugs or request features.

When reporting bugs, please include:

- Python version
- FastAPI version
- SQLAlchemy version
- Steps to reproduce
- Expected behavior
- Actual behavior

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
