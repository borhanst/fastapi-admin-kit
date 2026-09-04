# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.1] - 2026-09-03

- Fix/model register: improved session management and error handling in role seeding process ([#57](https://github.com/borhanst/fastapi-admin-kit/pull/57))
- Enhanced file URL handling and storage path management for uploads
- Implemented snapshot and restore mechanism for custom auth_model adaptations in SQLAlchemy backend
- Updated file path handling in LocalStorageBackend to include leading slash and improve URL generation
- Updated image source binding in file input preview
- Implemented file handling improvements and added has_file_field support
- Renamed 'hashed_password' to 'password' in user model for consistency
- Added fixture to restore built-in mapper state for auth_model validation tests
- Enhanced SelectWidget to support enum classes for better value handling
- Enhanced user model resolution and query backend handling in notifications
- Enhanced user representation in admin templates and CLI output
- Implemented custom auth_model support and adapt built-in user relations

## [0.5.0] - 2026-09-01

- feat: add per-model endpoint export control (export_endpoint) + standalone export routes ([#48](https://github.com/borhanst/fastapi-admin-kit/pull/48))
- create security md file ([#51](https://github.com/borhanst/fastapi-admin-kit/pull/51))
- feat: add @endpoint decorator for custom ModelAdmin FastAPI routes ([#53](https://github.com/borhanst/fastapi-admin-kit/pull/53))
- feat: Django-style filtering system (#52) ([#54](https://github.com/borhanst/fastapi-admin-kit/pull/54))
- Feat/security ([#56](https://github.com/borhanst/fastapi-admin-kit/pull/56))

## [0.4.0] - 2026-08-17

- fix: update model references to use new migration path and add migration ([#40](https://github.com/borhanst/fastapi-admin-kit/pull/40))
- update readme file ([#41](https://github.com/borhanst/fastapi-admin-kit/pull/41))
- Feat/ai agent ([#42](https://github.com/borhanst/fastapi-admin-kit/pull/42))
- update release workflow ([#43](https://github.com/borhanst/fastapi-admin-kit/pull/43))

## [0.3.2] - 2026-07-31

- Alembic migration ([#39](https://github.com/borhanst/fastapi-admin-kit/pull/39))

## [0.3.1] - 2026-07-29

- Feat/export import ([#38](https://github.com/borhanst/fastapi-admin-kit/pull/38))

## [0.3.0] - 2026-07-28

- Feat/permission update ([#20](https://github.com/borhanst/fastapi-admin-kit/pull/20))
- feat: add inline formset support to model admin ([#21](https://github.com/borhanst/fastapi-admin-kit/pull/21))
- refactor: decouple DefaultQueryProvider, search_utils, and Filter classes from SQLAlchemy ([#33](https://github.com/borhanst/fastapi-admin-kit/pull/33))
- feat: wire adapter registration into Admin (#31) ([#35](https://github.com/borhanst/fastapi-admin-kit/pull/35))
- feat: schema-first + protocol hybrid approach for built-in admin models (#32) ([#34](https://github.com/borhanst/fastapi-admin-kit/pull/34))
- Fix issues ([#36](https://github.com/borhanst/fastapi-admin-kit/pull/36))
- chore: update version to 0.3.0 ([#37](https://github.com/borhanst/fastapi-admin-kit/pull/37))

## [0.2.1] - 2026-07-21

- Fix bug and change user permission model ([#19](https://github.com/borhanst/fastapi-admin-kit/pull/19))

## [0.2.0] - 2026-07-13

- Feat/authentication ([#14](https://github.com/borhanst/fastapi-admin-kit/pull/14))
- fix docs buil issue ([#15](https://github.com/borhanst/fastapi-admin-kit/pull/15))

## [0.1.2] - 2026-07-09

- feat: implement CLI commands for project scaffolding and user management ([#10](https://github.com/borhanst/fastapi-admin-kit/pull/10))
- fix: update version to 0.1.1 ([#11](https://github.com/borhanst/fastapi-admin-kit/pull/11))
- Fix/UUID pk support ([#12](https://github.com/borhanst/fastapi-admin-kit/pull/12))
- fix: update version to 0.1.2 ([#13](https://github.com/borhanst/fastapi-admin-kit/pull/13))

## [0.1.1] - 2026-07-09

- Db config ([#1](https://github.com/borhanst/fastapi-admin-kit/pull/1))
- fix: use StrEnum for DatabaseType ([#4](https://github.com/borhanst/fastapi-admin-kit/pull/4))
- feat: rename CLI from fastapi-admin-kit to fak-admin ([#3](https://github.com/borhanst/fastapi-admin-kit/pull/3))
- fix: update emoji configuration in markdown extensions ([#5](https://github.com/borhanst/fastapi-admin-kit/pull/5))
- Docs/update readme ([#8](https://github.com/borhanst/fastapi-admin-kit/pull/8))
- feat: Inline Editing — Edit records directly from list view ([#9](https://github.com/borhanst/fastapi-admin-kit/pull/9))

## [0.1.0] - 2026-07-08

_Generated from tag `v0.1.0` (no release notes)._
