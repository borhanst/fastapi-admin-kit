# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Robust Django-style filtering system
  ([#52](https://github.com/borhanst/fastapi-admin-kit/issues/52)):
  - New lookup types for the JSON API and admin UI list views:
    `icontains`, `startswith`, `endswith`, `gt`, `gte`, `lt`, `lte`,
    `range`, and `in` — in addition to exact matches.
  - New `ChoiceFilter` for relation/FK fields (auto-detected in
    `FilterRegistry.auto_generate()`), plus `IntegerFilter` with full
    numeric lookups.
  - Admin UI now renders text-input filters (case-insensitive contains)
    and min/max inputs for numeric fields.
  - Filters are ORM-agnostic: `QueryBackend` gained an `and_` combinator
    and the in-memory backend now handles `%`-anchored `ilike` patterns.
- `Admin.setup()` now logs a non-blocking preflight warning naming any missing
  `admin_ai_*` tables (with the command to fix them) when `ai_enabled=True`
  but the schema is absent (Alembic / `SKIP_CREATE_TABLES=true` mode).
- `fastapi_admin_kit.schemas.builtin.AI_TABLE_NAMES` and
  `INTERNAL_TABLE_NAMES` constants for gating/identification.
- `AdminRegistry.auto_discover(exclude_tables=...)` accepts a set of table
  names to skip during discovery.

### Changed
- **AI is now gated behind `ai_enabled` (default `False`).** When AI is
  disabled, the `admin_ai_*` tables are not created, and the AI models, nav
  group, and routes are not registered in the admin UI or the JSON API.
  Notifications, auth, roles, audit, and login-attempt models are unaffected.
- Internal tables (`admin_refresh_tokens`, `admin_user_permissions`,
  `admin_user_totp`, `admin_ai_attachments`) are no longer exposed over the
  JSON API (previously a latent security hole). They remain hidden from the
  sidebar.

## [0.3.2] - 2026-07-31

### Changed
- Added Alembic database migrations so schema changes can be versioned and
  applied incrementally instead of relying solely on auto-create
  ([#39](https://github.com/borhanst/fastapi-admin-kit/pull/39)).

## [0.3.1] - 2026-07-29

### Added
- CSV export and import support for models, enabling bulk data download and
  upload from the admin UI
  ([#38](https://github.com/borhanst/fastapi-admin-kit/pull/38)).

## [0.3.0] - 2026-07-28

### Added
- Per-model permission updates and refinements to the RBAC model
  ([#20](https://github.com/borhanst/fastapi-admin-kit/pull/20)).
- Inline formset support for `ModelAdmin`, allowing related records to be
  edited on the same page
  ([#21](https://github.com/borhanst/fastapi-admin-kit/pull/21)).
- Adapter registration wired directly into `Admin`
  ([#35](https://github.com/borhanst/fastapi-admin-kit/pull/35)).
- Schema-first + protocol hybrid approach for built-in admin models
  ([#34](https://github.com/borhanst/fastapi-admin-kit/pull/34)).

### Changed
- Decoupled `DefaultQueryProvider`, `search_utils`, and the `Filter` classes
  from SQLAlchemy, improving backend portability
  ([#33](https://github.com/borhanst/fastapi-admin-kit/pull/33)).

### Fixed
- Assorted bug fixes and stability improvements
  ([#36](https://github.com/borhanst/fastapi-admin-kit/pull/36)).

## [0.2.1] - 2026-07-21

### Fixed
- Corrected a user-permission model bug and adjusted how permissions are
  stored and evaluated
  ([#19](https://github.com/borhanst/fastapi-admin-kit/pull/19)).

## [0.2.0] - 2026-07-13

### Added
- Authentication subsystem with session-based login, logout, and protected
  routes ([#14](https://github.com/borhanst/fastapi-admin-kit/pull/14)).

### Fixed
- Resolved a documentation build failure
  ([#15](https://github.com/borhanst/fastapi-admin-kit/pull/15)).

## [0.1.2] - 2026-07-09

### Added
- CLI commands for project scaffolding and user management
  ([#10](https://github.com/borhanst/fastapi-admin-kit/pull/10)).

### Fixed
- Added support for UUID primary keys on models
  ([#12](https://github.com/borhanst/fastapi-admin-kit/pull/12)).

## [0.1.1] - 2026-07-09

### Added
- Database configuration and connection handling
  ([#1](https://github.com/borhanst/fastapi-admin-kit/pull/1)).
- Inline editing — edit records directly from the list view
  ([#9](https://github.com/borhanst/fastapi-admin-kit/pull/9)).

### Changed
- Renamed the CLI from `fastapi-admin-kit` to `fak-admin`
  ([#3](https://github.com/borhanst/fastapi-admin-kit/pull/3)).

### Fixed
- Use `StrEnum` for `DatabaseType` for safer, string-compatible enums
  ([#4](https://github.com/borhanst/fastapi-admin-kit/pull/4)).
- Updated emoji configuration in the markdown extensions
  ([#5](https://github.com/borhanst/fastapi-admin-kit/pull/5)).

## [0.1.0] - 2026-07-08

### Added
- Initial release of FastAPI Admin Kit: a drop-in admin panel for FastAPI +
  SQLAlchemy + SQLModel applications with auto-discovery, RBAC, audit logging,
  and a modern UI.
