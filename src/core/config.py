import yaml
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any

class CategoryConfig(BaseModel):
    extensions: List[str]
    structure: str
    subcategories: Dict[str, List[str]] = Field(default_factory=dict)
    renaming: Optional[str] = None

class ScannerConfig(BaseModel):
    exclude_dirs: List[str] = Field(default_factory=list)
    include_hidden: bool = False

class SettingsConfig(BaseModel):
    enable_renaming: bool = True
    title_case: bool = True
    naming_convention: str = "{date}_{filename}"
    duplicate_folder: str = "Duplicates"
    recursive_undo_cleanup: bool = True

class PerformanceConfig(BaseModel):
    max_workers: int = Field(default=4)
    use_multiprocessing: bool = Field(default=False)

class AppConfig(BaseModel):
    settings: SettingsConfig
    scanner: ScannerConfig
    categories: Dict[str, CategoryConfig]
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)

    @classmethod
    def load(cls, path: str = "config.yaml") -> 'AppConfig':
        config_path = Path(path)
        if not config_path.exists():
            # Should we raise or return default? For now, we expect it to exist.
            raise FileNotFoundError(f"Config file not found: {path}")
        
        with open(config_path, 'r') as f:
            data = yaml.safe_load(f)
            return cls(**data)

    def get_category_for_ext(self, ext: str) -> Optional[str]:
        ext = ext.lower()
        for cat_name, cat_cfg in self.categories.items():
            if ext in [e.lower() for e in cat_cfg.extensions]:
                return cat_name
        return None
