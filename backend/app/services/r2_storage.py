"""
Cloudflare R2 Storage Service
S3-compatible object storage for WhatsApp media files

boto3 is a synchronous client — every put_object / delete_object call blocks
the event loop for the duration of the round-trip (typically 100–500 ms). All
public functions here are async and route the blocking calls through
asyncio.to_thread so the event loop stays responsive. Matches the existing
to_thread pattern used by /health for head_bucket in main.py.
"""
import asyncio
import functools
import uuid
import mimetypes
from botocore.config import Config
from app.config import settings


ALLOWED_MIME_TYPES = {
    'application/pdf',
    'text/plain',
    'image/jpeg', 'image/png', 'image/webp',
    'video/mp4',
    'audio/ogg', 'audio/mpeg', 'audio/aac', 'audio/amr',
}

MEDIA_SIZE_LIMITS = {
    'image':    5  * 1024 * 1024,   # 5MB
    'video':    16 * 1024 * 1024,   # 16MB
    'audio':    16 * 1024 * 1024,   # 16MB
    'document': 100 * 1024 * 1024,  # 100MB
}


def _get_r2_client():
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


async def download_and_store_whatsapp_media(
    media_id: str,
    access_token: str,
    workspace_id: str,
) -> dict:
    """
    Download media from WhatsApp Graph API and store in R2.
    Must be called immediately — WhatsApp URLs expire in ~5 minutes.
    Returns: { url, mime_type, size_bytes, filename }
    """
    import httpx

    async with httpx.AsyncClient() as client:
        # Step 1: Resolve temporary URL
        meta = await client.get(
            f"https://graph.facebook.com/v17.0/{media_id}",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        meta.raise_for_status()
        download_url = meta.json()["url"]
        mime_type = meta.json().get("mime_type", "application/octet-stream")

        # Step 2: Download bytes
        file_resp = await client.get(
            download_url,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        file_resp.raise_for_status()
        file_bytes = file_resp.content

    # Step 3: Upload to R2 (off-loaded to worker thread — boto3 is sync)
    ext = mimetypes.guess_extension(mime_type) or ""
    key = f"media/{workspace_id}/{uuid.uuid4()}{ext}"

    r2 = _get_r2_client()
    await asyncio.to_thread(
        functools.partial(
            r2.put_object,
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
            Body=file_bytes,
            ContentType=mime_type,
        )
    )

    public_url = f"https://{settings.R2_PUBLIC_DOMAIN}/{key}"

    return {
        "url": public_url,
        "mime_type": mime_type,
        "size_bytes": len(file_bytes),
        "filename": key.split("/")[-1],
    }


async def upload_agent_media(
    file_bytes: bytes,
    mime_type: str,
    workspace_id: str,
    original_filename: str = "",
) -> dict:
    """
    Upload media sent by an agent (from dashboard file picker) to R2.
    Returns: { url, mime_type, size_bytes, filename }
    """
    ext = mimetypes.guess_extension(mime_type) or ""
    key = f"media/{workspace_id}/{uuid.uuid4()}{ext}"

    r2 = _get_r2_client()
    await asyncio.to_thread(
        functools.partial(
            r2.put_object,
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
            Body=file_bytes,
            ContentType=mime_type,
        )
    )

    return {
        "url": f"https://{settings.R2_PUBLIC_DOMAIN}/{key}",
        "mime_type": mime_type,
        "size_bytes": len(file_bytes),
        "filename": original_filename or key.split("/")[-1],
    }


async def upload_webchat_media(
    file_bytes: bytes,
    mime_type: str,
    workspace_id: str,
    original_filename: str = "",
) -> dict:
    """
    Upload media sent by a webchat visitor to R2.
    Validates mime type and enforces per-category size limits before upload.
    Returns: { url, mime_type, size_bytes, filename }
    Raises: ValueError on unsupported type or oversized file.
    """
    if mime_type not in ALLOWED_MIME_TYPES:
        raise ValueError(f"Unsupported file type: {mime_type}")

    category = mime_type.split("/")[0]
    if mime_type in ("application/pdf", "text/plain"):
        category = "document"
    limit = MEDIA_SIZE_LIMITS.get(category)
    if limit and len(file_bytes) > limit:
        raise ValueError(
            f"File too large: {len(file_bytes)} bytes (limit {limit} bytes for {category})"
        )

    return await upload_agent_media(file_bytes, mime_type, workspace_id, original_filename)


async def upload_rag_document(
    file_bytes: bytes,
    mime_type: str,
    workspace_id: str,
    original_filename: str = "",
) -> dict:
    """
    Upload a RAG knowledge-base document to R2.
    Stored under documents/{workspace_id}/ (separate from media/).
    Returns: { url, mime_type, size_bytes, filename }
    """
    ext = {
        'application/pdf': '.pdf',
        'text/plain': '.txt',
    }.get(mime_type) or mimetypes.guess_extension(mime_type) or ''
    key = f"documents/{workspace_id}/{uuid.uuid4()}{ext}"

    r2 = _get_r2_client()
    await asyncio.to_thread(
        functools.partial(
            r2.put_object,
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
            Body=file_bytes,
            ContentType=mime_type,
        )
    )

    return {
        "url": f"https://{settings.R2_PUBLIC_DOMAIN}/{key}",
        "mime_type": mime_type,
        "size_bytes": len(file_bytes),
        "filename": original_filename or key.split("/")[-1],
    }


async def delete_r2_object(file_url: str) -> bool:
    """
    Delete an R2 object by its public URL.
    Returns True on success, False if the URL doesn't belong to this R2 domain.
    boto3.delete_object is sync; runs off the event loop via to_thread.
    """
    prefix = f"https://{settings.R2_PUBLIC_DOMAIN}/"
    if not file_url.startswith(prefix):
        return False  # not our R2 URL, skip silently
    key = file_url[len(prefix):]
    r2 = _get_r2_client()
    await asyncio.to_thread(
        functools.partial(r2.delete_object, Bucket=settings.R2_BUCKET_NAME, Key=key)
    )
    return True
