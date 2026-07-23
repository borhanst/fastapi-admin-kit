# Contributing

Thank you for your interest in contributing to FastAPI Admin Kit!

## Development Setup

### Prerequisites

- Python 3.11 or higher
- uv (recommended) or pip

### Clone and Install

```bash
git clone https://github.com/borhanst/fastapi-admin-kit.git
cd fastapi-admin-kit
uv sync
```

### Run Tests

```bash
uv run pytest
```

### Run Tests with Coverage

```bash
uv run pytest --cov=fastapi_admin_kit --cov-report=term-missing
```

### Run Linter

```bash
uv run ruff check fastapi_admin_kit/
uv run ruff format --check fastapi_admin_kit/
```

### Auto-Fix Lint Issues

```bash
uv run ruff check fastapi_admin_kit/ --fix
uv run ruff format fastapi_admin_kit/
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
├── api/            # JSON API endpoints
├── auth/           # Authentication and RBAC
├── audit/          # Audit logging
├── cli/            # CLI commands (fak-admin / fak)
├── config/         # Configuration classes
├── filters/        # List view filters
├── views/          # Route handlers and view classes
├── widgets/        # Form widgets
├── templates/      # Jinja2 templates
├── static/         # CSS, JS, images
└── plugins/        # Plugin system
```

## Code Style

We use Ruff for linting and formatting:

- Line length: 100
- Target: Python 3.11
- Rules: E, F, I, N, UP

Always run the linter and formatter before submitting a PR:

```bash
uv run ruff check fastapi_admin_kit/
uv run ruff format fastapi_admin_kit/
```

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
