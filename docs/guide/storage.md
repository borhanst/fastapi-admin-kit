# Storage & File Uploads

Handle file uploads with built-in local storage or custom backends.

## Overview

FastAPI Admin Kit includes a storage abstraction for file uploads. The default `LocalStorageBackend` saves files to a local directory.

## Setup

### Configure Storage

```python
from fastapi_admin_kit.storage import LocalStorageBackend

admin = Admin(
    app=app,
    engine=engine,
    secret_key="...",
    storage=LocalStorageBackend(path="/uploads"),
    uploads_url="/uploads",
)
```

### Add Static Files Route

Serve uploaded files via FastAPI's `StaticFiles`:

```python
from fastapi.staticfiles import StaticFiles

app.mount("/uploads", StaticFiles(directory="/uploads"), name="uploads")
```

## Upload Widgets

### FileUploadWidget

Generic file upload with size limits and type filtering:

```python
from fastapi_admin_kit.widgets import FileUploadWidget

@admin.register(Document)
class DocumentAdmin(ModelAdmin):
    form_widgets = {
        "file": FileUploadWidget(
            max_size_mb=10,
            accept=".pdf,.doc,.docx",
        ),
    }
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `max_size_mb` | `int` | `10` | Maximum file size in MB |
| `accept` | `str` | `""` | Comma-separated file extensions |

### ImageUploadWidget

Image-specific upload with preview:

```python
from fastapi_admin_kit.widgets import ImageUploadWidget

@admin.register(Product)
class ProductAdmin(ModelAdmin):
    form_widgets = {
        "image_url": ImageUploadWidget(
            max_size_mb=5,
            accept="image/*",
        ),
    }
```

## Storage Backend Protocol

Implement custom backends (S3, GCS, etc.) by extending `StorageBackend`:

```python
from fastapi_admin_kit.storage.base import StorageBackend

class S3StorageBackend(StorageBackend):
    def __init__(self, bucket, region, access_key, secret_key):
        self.bucket = bucket
        # ... setup S3 client

    async def save(self, file, filename, content_type):
        # Upload to S3
        ...

    async def delete(self, path):
        # Delete from S3
        ...

    def get_url(self, path):
        # Return public URL
        return f"https://{self.bucket}.s3.amazonaws.com/{path}"
```

### Backend Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `save` | `async save(file, filename, content_type) -> str` | Save file, return path |
| `delete` | `async delete(path) -> None` | Delete file |
| `get_url` | `get_url(path) -> str` | Get public URL for file |

## Next Steps

- [Widgets & Forms](widgets-forms.md) — More widget options
- [Configuration](../getting-started/configuration.md) — Storage config options
