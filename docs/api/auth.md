# Auth

## Auth Backend

::: fastapi_admin_kit.auth.backend.AuthBackend
    options:
      show_source: true
      show_root_heading: true
      members_order: source
      heading_level: 2

## Permission Checker

::: fastapi_admin_kit.auth.permissions.PermissionChecker
    options:
      show_source: true
      show_root_heading: true
      members_order: source
      heading_level: 2

## Models

The built-in admin models are materialized at runtime from the schemas in
`fastapi_admin_kit.schemas.builtin`. They live in `fastapi_admin_kit.migrations.models`
(the deprecated `fastapi_admin_kit.auth.models` module re-exports the same classes
and will be removed in v3.0).

### User

::: fastapi_admin_kit.migrations.models.User
    options:
      show_source: true
      show_root_heading: true
      members_order: source
      heading_level: 3

### Role

::: fastapi_admin_kit.migrations.models.Role
    options:
      show_source: true
      show_root_heading: true
      members_order: source
      heading_level: 3

### Permission

::: fastapi_admin_kit.migrations.models.Permission
    options:
      show_source: true
      show_root_heading: true
      members_order: source
      heading_level: 3

### UserPermission

::: fastapi_admin_kit.migrations.models.UserPermission
    options:
      show_source: true
      show_root_heading: true
      members_order: source
      heading_level: 3

## Dependencies

::: fastapi_admin_kit.auth.dependencies
    options:
      show_source: true
      show_root_heading: true
      members_order: source
      heading_level: 2

## Session

::: fastapi_admin_kit.auth.session
    options:
      show_source: true
      show_root_heading: true
      members_order: source
      heading_level: 2
