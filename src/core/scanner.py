from pathlib import Path
from typing import Generator, List, Optional, Dict, Any
from tqdm import tqdm
from src.core.config import AppConfig

class FileScanner:
    """
    Recursively scans a directory for files.
    """
    def __init__(self, root_dir: str, include_hidden: bool = False, target_dir: Optional[str] = None, config: Optional[AppConfig] = None):
        self.root_dir = Path(root_dir)
        self.include_hidden = include_hidden
        self.target_dir = Path(target_dir) if target_dir else None
        self.config = config
        
        # Load exclusions from config or use defaults
        self.exclusions = set(config.scanner.exclude_dirs) if config else {'.git', '__pycache__', '.venv', '.uv', 'node_modules', '.gemini'}

    def scan(self, extensions: Optional[List[str]] = None) -> Generator[Path, None, None]:
        """
        Scans the root directory and yields file Paths.
        :param extensions: Optional list of extensions to include (e.g. ['.jpg', '.pdf'])
        """
        if not self.root_dir.exists():
            raise FileNotFoundError(f"Directory {self.root_dir} does not exist.")

        # Using os.walk for better performance on large directories or rglob
        for path in self.root_dir.rglob('*'):
            # 1. Skip if it's a directory in the exclusion list
            if path.is_dir() and path.name in self.exclusions:
                continue
                
            # 2. Skip the target directory if it's a subfolder of the source
            if self.target_dir and self.target_dir != self.root_dir:
                if self.target_dir == path or self.target_dir in path.parents:
                    continue

            if path.is_file():
                # 3. Skip hidden files if not requested
                if not self.include_hidden and any(part.startswith('.') for part in path.parts):
                    continue
                
                # 4. Skip if any part of the path is in exclusions
                if any(part in self.exclusions for part in path.parts):
                    continue

                if extensions:
                    if path.suffix.lower() in [ext.lower() for ext in extensions]:
                        yield path
                else:
                    yield path

    def count_files(self) -> int:
        """Quickly count total files for progress bars."""
        return sum(1 for _ in self.root_dir.rglob('*') if _.is_file())

if __name__ == "__main__":
    # Test scanner
    scanner = FileScanner(".")
    for f in scanner.scan():
        print(f)
