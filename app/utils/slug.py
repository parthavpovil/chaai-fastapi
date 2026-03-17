"""
Slug Generation Utilities
Generate unique URL-safe slugs from business names
"""
import re
import secrets
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.workspace import Workspace


def slugify(text: str) -> str:
    """
    Convert text to URL-safe slug
    
    Args:
        text: Input text to slugify
        
    Returns:
        URL-safe slug string
    """
    # Convert to lowercase
    slug = text.lower()
    
    # Replace spaces with hyphens
    slug = re.sub(r'\s+', '-', slug)
    
    # Remove all non-ASCII alphanumeric characters except hyphens
    slug = re.sub(r'[^a-z0-9-]', '', slug)
    
    # Replace multiple consecutive hyphens with single hyphen
    slug = re.sub(r'-+', '-', slug)
    
    # Remove leading/trailing hyphens
    slug = slug.strip('-')
    
    # Ensure minimum length
    if len(slug) < 3:
        slug = f"workspace-{slug}" if slug else "workspace"
    
    # Limit maximum length
    if len(slug) > 50:
        slug = slug[:50].rstrip('-')
    
    return slug


async def generate_unique_slug(
    business_name: str, 
    db: AsyncSession,
    max_attempts: int = 10
) -> str:
    """
    Generate unique workspace slug from business name
    
    Args:
        business_name: Business name to convert to slug
        db: Database session
        max_attempts: Maximum attempts to find unique slug
        
    Returns:
        Unique slug string
        
    Raises:
        ValueError: If unable to generate unique slug after max attempts
    """
    base_slug = slugify(business_name)
    
    for attempt in range(max_attempts):
        # First attempt uses base slug, subsequent attempts add suffix
        if attempt == 0:
            candidate_slug = base_slug
        else:
            # Add random suffix for uniqueness
            suffix = secrets.token_hex(3)  # 6 character hex string
            candidate_slug = f"{base_slug}-{suffix}"
        
        # Check if slug is already taken
        result = await db.execute(
            select(Workspace).where(Workspace.slug == candidate_slug)
        )
        existing_workspace = result.scalar_one_or_none()
        
        if not existing_workspace:
            return candidate_slug
    
    # If we couldn't generate a unique slug, raise an error
    raise ValueError(f"Unable to generate unique slug after {max_attempts} attempts")