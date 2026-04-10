import os
from pathlib import Path
from PIL import Image
import hashlib

def get_thumbnail_path(file_path: str, thumbnail_dir: str = ".thumbnails") -> Path:
    """Generates a unique thumbnail path based on the file's absolute path hash."""
    abs_path = os.path.abspath(file_path)
    path_hash = hashlib.md5(abs_path.encode()).hexdigest()
    
    # We store thumbnails in a hidden folder inside the project or target
    # For now, let's use a local project folder to avoid polluting user space too much
    # but the implementation plan suggested target root. Let's stick to a central cache for now.
    cache_dir = Path("data/thumbnails")
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    return cache_dir / f"{path_hash}.webp"

def generate_thumbnail(file_path: str) -> Path:
    """
    Generates a 200px WebP thumbnail for an image file.
    Returns the path to the generated thumbnail.
    """
    thumb_path = get_thumbnail_path(file_path)
    
    if thumb_path.exists():
        return thumb_path
        
    try:
        with Image.open(file_path) as img:
            # Convert to RGB if necessary (for RGBA/CMYK)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            
            img.thumbnail((200, 200))
            img.save(thumb_path, "WEBP", quality=80)
            return thumb_path
    except Exception as e:
        # If it fails, we might want to return a 'broken' icon or similar
        raise e
