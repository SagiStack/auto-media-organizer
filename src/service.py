import time
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from src.core.analyzer import FileAnalyzer
from src.core.organizer import Organizer
from src.core.database import HistoryManager
from src.core.config import AppConfig

class OrganizeHandler(FileSystemEventHandler):
    def __init__(self, watch_path: str, target_path: str, config: AppConfig):
        self.watch_path = Path(watch_path)
        self.target_path = Path(target_path)
        self.config = config
        self.analyzer = FileAnalyzer(config=config)
        self.history = HistoryManager()
        self.logger = logging.getLogger("AutoOrganizerService")

    def on_created(self, event):
        if event.is_directory:
            return
        
        file_path = Path(event.src_path)
        # Skip if it's a temporary file or hidden
        if file_path.name.startswith('.') or file_path.suffix == '.tmp':
            return
            
        self.logger.info(f"New file detected: {file_path}")
        
        # Give it a tiny bit of time to settle
        time.sleep(0.5)
        
        try:
            # We create a unique session ID for every auto-organize event 
            # or we could group them by day. Let's do unique per event for granularity.
            session_id = f"auto-{self.history.generate_session_id()[:8]}"
            organizer = Organizer(str(self.target_path), dry_run=False, session_id=session_id, config=self.config)
            
            analysis = self.analyzer.analyze(file_path)
            if analysis['action'] != 'skipped':
                organizer.organize_file(analysis)
                self.logger.info(f"Auto-Organized: {file_path}")
        except Exception as e:
            self.logger.error(f"Error in auto-organize for {file_path}: {e}")

class AutoOrganizerService:
    def __init__(self, watch_path: str, target_path: str, config: AppConfig):
        self.watch_path = watch_path
        self.target_path = target_path
        self.config = config
        self.observer = None
        self.running = False

    def start(self):
        if self.running: return
        
        event_handler = OrganizeHandler(self.watch_path, self.target_path, self.config)
        self.observer = Observer()
        self.observer.schedule(event_handler, self.watch_path, recursive=False)
        self.observer.start()
        self.running = True
        logging.info(f"Watchdog started on {self.watch_path}")

    def stop(self):
        if not self.running: return
        
        self.observer.stop()
        self.observer.join()
        self.running = False
        logging.info("Watchdog stopped.")

if __name__ == "__main__":
    # For CLI usage
    import sys
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
    if len(sys.argv) > 2:
        config = AppConfig.load("config.yaml")
        service = AutoOrganizerService(sys.argv[1], sys.argv[2], config)
        service.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            service.stop()
    else:
        print("Usage: python service.py <watch_dir> <target_dir>")
