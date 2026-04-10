import os
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from src.core.database import HistoryManager

from src.core.config import AppConfig

class Organizer:
    """
    Handles the movement of files based on their analysis.
    """
    def __init__(self, target_root: str, dry_run: bool = True, session_id: str = None, config: Optional[AppConfig] = None):
        self.target_root = Path(target_root)
        self.dry_run = dry_run
        self.session_id = session_id
        self.db = HistoryManager()
        self.config = config
        self.history: List[Dict[str, str]] = []

    def get_clean_filename(self, analysis: Dict[str, Any]) -> str:
        """Constructs a clean, standardized filename based on metadata and config."""
        import re
        category = analysis.get("category", "Other")
        ext = analysis.get("extension", "")
        basename = Path(analysis["filename"]).stem
        
        # 0. Check if renaming is enabled
        if self.config and not self.config.settings.enable_renaming:
            return analysis["filename"]

        # 1. Avoid Double-Prefixing
        date_pattern = r"^\d{4}-\d{2}-\d{2}_"
        if re.match(date_pattern, basename):
            basename = re.sub(date_pattern, "", basename)

        # 2. Get Date Variables
        date_str = analysis["metadata"].get("date_taken") or analysis["system_dates"].get("created")
        try:
            dt = datetime.fromisoformat(date_str) if "T" in date_str else datetime.strptime(date_str.split()[0], "%Y:%m:%d")
        except:
            fallback = analysis["system_dates"].get("modified", datetime.now().isoformat())
            dt = datetime.fromisoformat(fallback)
        
        date_vars = {
            "year": str(dt.year),
            "month": dt.strftime("%B"),
            "day": dt.strftime("%d"),
            "date": dt.strftime("%Y-%m-%d"),
            "filename": basename,
            "extension": ext,
            "artist": analysis["metadata"].get("artist", "Unknown"),
            "album": analysis["metadata"].get("album", "Unknown"),
            "title": analysis["metadata"].get("title", basename),
            "subcategory": analysis.get("subcategory", "General")
        }

        # 3. Determine Template
        template = self.config.settings.naming_convention if self.config and self.config.settings.naming_convention else "{date}_{filename}{extension}"
        if self.config and category in self.config.categories:
            cat_cfg = self.config.categories[category]
            if cat_cfg.renaming:
                template = cat_cfg.renaming + "{extension}"

        try:
            filename = template.format(**date_vars)
            # Safety Check: If the template somehow dropped the extension, force-append it
            if not filename.lower().endswith(ext.lower()):
                filename += ext
            return filename
        except:
            return f"{date_vars['date']}_{basename}{ext}"

    def get_destination(self, analysis: Dict[str, Any]) -> Path:
        """Determines the nested target path based on config patterns."""
        category = analysis.get("category", "Other")
        subcategory = analysis.get("subcategory", "General")
        filename = self.get_clean_filename(analysis)
        
        # 1. Determine Folder Variables
        date_str = analysis["metadata"].get("date_taken") or analysis["system_dates"].get("created")
        try:
            dt = datetime.fromisoformat(date_str) if "T" in date_str else datetime.strptime(date_str.split()[0], "%Y:%m:%d")
        except:
            fallback = analysis["system_dates"].get("modified", datetime.now().isoformat())
            dt = datetime.fromisoformat(fallback)

        folder_vars = {
            "year": str(dt.year),
            "month": dt.strftime("%B"),
            "day": dt.strftime("%d"),
            "category": category,
            "subcategory": subcategory,
            "artist": analysis["metadata"].get("artist", "Unknown"),
            "album": analysis["metadata"].get("album", "Unknown")
        }

        # Apply TitleCase if enabled
        if self.config and self.config.settings.title_case:
            folder_vars = {k: v.title() if isinstance(v, str) else v for k, v in folder_vars.items()}
            category = category.title()

        # 2. Build Path using Template
        root_dir = self.target_root / category
        structure = "{subcategory}/{year}" # Default
        
        if self.config and category in self.config.categories:
            structure = self.config.categories[category].structure
        elif category == "Images":
            structure = "{year}/{month}"
        elif category == "Audio":
            structure = "{artist}/{album}"

        # Special logic for screenshots (could also be in config eventually)
        if subcategory.title() == "Screenshots" and category.title() == "Images":
            dest_dir = root_dir / "Screenshots" / folder_vars["year"]
        else:
            try:
                # Format the structure string with our variables
                rel_path = structure.format(**folder_vars)
                dest_dir = root_dir / rel_path
            except:
                dest_dir = root_dir / folder_vars["subcategory"]

        return dest_dir / filename

    def organize_file(self, analysis: Dict[str, Any]) -> str:
        """
        Moves a file to its destination and records the action.
        """
        source = Path(analysis["path"])
        dest = self.get_destination(analysis)
        
        # 1. Handle Duplicates based on hash
        # If a file exists at 'dest', we check if it's the SAME content
        if dest.exists():
            import hashlib
            def get_dest_hash(p):
                sha256 = hashlib.sha256()
                with open(p, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        sha256.update(chunk)
                return sha256.hexdigest()
            
            if analysis.get("hash") == get_dest_hash(dest):
                # It's a duplicate! Move to Duplicates folder
                duplicate_folder = self.config.settings.duplicate_folder if self.config else "Duplicates"
                dest = self.target_root / duplicate_folder / dest.name
                
                # Check if it already exists in Duplicates too
                if dest.exists() and analysis.get("hash") == get_dest_hash(dest):
                    # Already in duplicates, we can safely skip or delete (let's skip for safety)
                    self.history.append({
                        "source": str(source),
                        "dest": "DELETED (Exact Duplicate Found)",
                        "action": "skipped",
                        "category": analysis["category"],
                        "size": analysis["size"]
                    })
                    return "skipped"

        # 2. Avoid moving if it's already exactly where it should be
        if source == dest:
            self.history.append({
                "source": str(source),
                "dest": str(dest),
                "action": "skipped",
                "category": analysis["category"],
                "size": analysis["size"]
            })
            return "skipped"

        # 3. Handle naming collisions (different files, same name)
        if dest.exists():
            count = 1
            while dest.exists():
                dest = dest.with_name(f"{dest.stem}_{count}{dest.suffix}")
                count += 1

        action = "moved" if not self.dry_run else "would_move"
        
        if not self.dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(dest))
            
            # 1. Log to History DB (Undo support)
            if self.session_id:
                self.db.log_move(self.session_id, source, dest)
            
            # 2. Log to File Catalog (Gallery/Duplicates)
            self.db.log_file(
                file_hash=analysis.get("hash"),
                file_path=str(dest),
                category=analysis["category"],
                subcategory=analysis.get("subcategory", "General"),
                size=analysis["size"]
            )
            # Remove old entry if it existed
            if source != dest:
                self.db.remove_file(str(source))
        
        self.history.append({
            "source": str(source),
            "dest": str(dest),
            "action": action,
            "category": analysis["category"],
            "size": analysis["size"]
        })
        
        return action

    def get_summary(self) -> Dict[str, Any]:
        """Returns a summary of all actions taken."""
        summary = {
            "total_files": len(self.history),
            "total_size": sum(h["size"] for h in self.history),
            "categories": {},
            "actions": {"moved": 0, "would_move": 0, "skipped": 0}
        }
        
        for h in self.history:
            cat = h["category"]
            summary["categories"][cat] = summary["categories"].get(cat, 0) + 1
            summary["actions"][h["action"]] = summary["actions"].get(h["action"], 0) + 1
            
        return summary
