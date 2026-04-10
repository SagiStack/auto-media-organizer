import os
import hashlib
import mimetypes
import threading
from pathlib import Path
from typing import Dict, Any, Optional
import exifread
from mutagen import File as MutagenFile
import magic

from src.core.config import AppConfig

class FileAnalyzer:
    """
    Analyzes files to extract deep metadata and content information.
    """
    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config
        self._local = threading.local()

    def _get_magic(self):
        """Returns a thread-local magic instance."""
        if not hasattr(self._local, "mgc"):
            try:
                self._local.mgc = magic.Magic(mime=True)
            except Exception:
                self._local.mgc = None
        return self._local.mgc

    def get_mime_type(self, path: Path) -> str:
        """Determines the MIME type of a file."""
        mgc = self._get_magic()
        if mgc:
            try:
                return mgc.from_file(str(path))
            except Exception:
                pass
        
        # Fallback to mimetypes
        mime, _ = mimetypes.guess_type(path)
        if not mime:
            # Manual mapping for common extensions that might be missing in mimetypes
            ext_map = {
                '.webp': 'image/webp',
                '.heic': 'image/heic',
                '.mp4': 'video/mp4',
                '.mov': 'video/quicktime',
                '.pages': 'application/x-iwork-pages-v2',
            }
            mime = ext_map.get(path.suffix.lower())
            
        return mime or "application/octet-stream"

    def get_hash(self, path: Path) -> str:
        """Generates a SHA256 hash for deduplication."""
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def analyze_image(self, path: Path) -> Dict[str, Any]:
        """Extracts EXIF data from images."""
        metadata = {}
        try:
            with open(path, 'rb') as f:
                tags = exifread.process_file(f, details=False)
                if 'EXIF DateTimeOriginal' in tags:
                    metadata['date_taken'] = str(tags['EXIF DateTimeOriginal'])
                if 'Image Model' in tags:
                    metadata['camera'] = str(tags['Image Model'])
        except Exception as e:
            metadata['error'] = str(e)
        return metadata

    def analyze_audio(self, path: Path) -> Dict[str, Any]:
        """Extracts metadata from audio files."""
        metadata = {}
        try:
            audio = MutagenFile(path)
            if audio:
                metadata['artist'] = audio.get('artist', ['Unknown'])[0]
                metadata['album'] = audio.get('album', ['Unknown'])[0]
                metadata['title'] = audio.get('title', ['Unknown'])[0]
                if 'date' in audio:
                    metadata['year'] = str(audio.get('date')[0])
        except Exception as e:
            metadata['error'] = str(e)
        return metadata

    def get_file_dates(self, path: Path) -> Dict[str, Any]:
        """Fetches creation and modification dates from the filesystem."""
        from datetime import datetime
        stat = path.stat()
        return {
            "created": datetime.fromtimestamp(stat.st_ctime),
            "modified": datetime.fromtimestamp(stat.st_mtime)
        }

    def get_keyword_category(self, filename: str, cat_name: str) -> Optional[str]:
        """Guesses a sub-category based on keywords from the configuration."""
        if not self.config:
            # Fallback (old behavior) if config missing
            return None
            
        cat_cfg = self.config.categories.get(cat_name)
        if not cat_cfg or not cat_cfg.subcategories:
            return None
        
        filename_lower = filename.lower()
        for subcat, kws in cat_cfg.subcategories.items():
            if any(kw.lower() in filename_lower for kw in kws):
                return subcat
        return None

    def analyze(self, path: Path) -> Dict[str, Any]:
        """Full analysis of a file with smart metadata detection."""
        mime = self.get_mime_type(path)
        system_dates = self.get_file_dates(path)
        
        analysis = {
            "path": str(path),
            "filename": path.name,
            "extension": path.suffix.lower(),
            "mime_type": mime,
            "size": path.stat().st_size,
            "system_dates": {k: v.isoformat() for k, v in system_dates.items()},
            "metadata": {},
            "category": "Other",
            "subcategory": "General"
        }

        # 1. Primary Category Based on MIME/Extension
        ext = path.suffix.lower()
        is_document = any(x in mime for x in ["pdf", "word", "text", "spreadsheet", "presentation"]) or \
                      ext in ['.pdf', '.docx', '.txt', '.xlsx', '.pptx', '.csv', '.md']

        # 1. Primary Category Based on Config or MIME/Extension
        ext = path.suffix.lower()
        if self.config:
            config_cat = self.config.get_category_for_ext(ext)
            if config_cat:
                analysis["category"] = config_cat
        
        # Fallback to old behavior if category still "Other"
        if analysis["category"] == "Other":
            is_document = any(x in mime for x in ["pdf", "word", "text", "spreadsheet", "presentation"]) or \
                          ext in ['.pdf', '.docx', '.txt', '.xlsx', '.pptx', '.csv', '.md']

            if mime.startswith("image/"):
                analysis["category"] = "Images"
            elif mime.startswith("audio/"):
                analysis["category"] = "Audio"
            elif mime.startswith("video/"):
                analysis["category"] = "Videos"
            elif is_document:
                analysis["category"] = "Documents"

        # 2. Extract specific metadata based on category
        if analysis["category"] == "Images":
            analysis["metadata"] = self.analyze_image(path)
        elif analysis["category"] == "Audio":
            analysis["metadata"] = self.analyze_audio(path)

        # 3. Subcategory based on keywords in config
        kw_cat = self.get_keyword_category(path.name, analysis["category"])
        if kw_cat:
            analysis["subcategory"] = kw_cat
        elif analysis["category"] == "Images" and "screenshot" in path.name.lower():
             analysis["subcategory"] = "Screenshots"

        # 4. Hash for deduplication
        analysis["hash"] = self.get_hash(path)

        return analysis

if __name__ == "__main__":
    analyzer = FileAnalyzer()
    # Test with current file
    print(analyzer.analyze(Path(__file__)))
