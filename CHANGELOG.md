# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-07-20

### Added
- Zero-config auto-discovery of SQLAlchemy models
- Built-in authentication with session-based cookies
- Role-based access control (RBAC) with per-model permissions
- Direct per-user permission overrides
- Audit logging with full change diffs
- Modern UI with Tailwind CSS, HTMX, and Alpine.js
- Global search / command palette (`Cmd+K` / `Ctrl+K`)
- Inline editing from list view with 3-dot action menu
- CLI tools (`fak-admin` / `fak`) for user management
- Async-first architecture with PostgreSQL, MySQL, and SQLite support
- SQLModel support via optional extra
- Custom widgets, themes, and templates
- Search and filtering with relation field lookups
- Bulk operations
- Dark mode with theme presets
- Pagination strategies (offset, cursor, dynamic)
- File uploads with local storage backend
- Plugin system for extensibility
- CSRF protection on all state-changing requests
- Rate limiting on authentication endpoints
- Environment badge for staging/production identification

### Security
- SQL injection prevention via identifier validation in CLI migrate and auto-migrate
- Secure session cookies with `SameSite=Strict` and `Secure` by default
- CSRF protection on all state-changing requests
- Rate limiting on authentication endpoints
- bcrypt password hashing
- Secret key validated to be >= 32 characters at startup
- Removed weak default credentials from examples

### Changed
- `uvicorn` and `pyjwt` moved to optional `[full]` extra (no longer hard dependencies)
- All library code uses `logging` instead of `print()` statements
- Silent exception blocks now log at debug level instead of silently swallowing

### Fixed
- `__all__` in `views/__init__.py` no longer references undefined symbols
- Debug print statement removed from `cli/helpers.py`
- Line length violations in `admin/builtin_models.py`
- Import sorting in `admin/admin_database.py` and `cli/migrate.py`
