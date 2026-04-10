import os
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import json
import logging
from typing import List, Optional

from src.core.config import AppConfig
from src.core.database import HistoryManager
from src.cli.main import run_analysis, run_organization
from src.service import AutoOrganizerService

app = FastAPI(title="Auto-Media-Organizer API")

# Setup CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared state
class ServiceManager:
    def __init__(self):
        self.active_service: Optional[AutoOrganizerService] = None
    
    def toggle(self, watch_path, target_path, config):
        if self.active_service and self.active_service.running:
            self.active_service.stop()
            return "stopped"
        else:
            self.active_service = AutoOrganizerService(watch_path, target_path, config)
            self.active_service.start()
            return "started"

    def status(self):
        if self.active_service and self.active_service.running:
            return {"running": True, "path": self.active_service.watch_path}
        return {"running": False, "path": None}

service_manager = ServiceManager()

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

# --- Global loop reference for thread-safe broadcasting ---
_main_loop = None

def create_ws_callback(phase="analysis"):
    global _main_loop
    if _main_loop is None:
        try:
            _main_loop = asyncio.get_running_loop()
        except RuntimeError:
            _main_loop = asyncio.get_event_loop()
            
    def callback(current, total, desc, phase=phase):
        asyncio.run_coroutine_threadsafe(
            manager.broadcast({
                "type": "progress",
                "phase": phase,
                "current": current,
                "total": total,
                "description": desc
            }),
            _main_loop
        )
    return callback

# --- Core Task Runner ---

async def run_task(task_func, *args, phase="task", **kwargs):
    """
    Helper to run a synchronous task in a threadpool and broadcast its lifecycle.
    """
    try:
        loop = asyncio.get_running_loop()
        def wrapper():
            return task_func(*args, **kwargs)
        await loop.run_in_executor(None, wrapper)
        await manager.broadcast({"type": "complete", "phase": phase})
    except Exception as e:
        logging.error(f"Task {phase} failed: {e}")
        await manager.broadcast({"type": "error", "phase": phase, "message": str(e)})

# --- Endpoints ---

@app.get("/api/utils/paths")
async def get_system_paths():
    # Harden home detection for Windows environments
    home_str = os.environ.get('USERPROFILE') or str(Path.home())
    home = Path(home_str)
    
    # Common Windows folders
    return {
        "home": str(home),
        "downloads": str(home / "Downloads"),
        "pictures": str(home / "Pictures"),
        "desktop": str(home / "Desktop"),
        "documents": str(home / "Documents")
    }

@app.get("/api/service/status")
async def get_service_status():
    return service_manager.status()

@app.post("/api/service/toggle")
async def toggle_service(path: str = "test_lab", target: Optional[str] = None):
    config = AppConfig.load("config.yaml")
    # Resolve to absolute path to ensure "Global" reliability
    abs_path = str(Path(path).resolve())
    abs_target = str(Path(target).resolve()) if target else abs_path
    
    state = service_manager.toggle(abs_path, abs_target, config)
    return {"status": state, "path": abs_path}

@app.get("/api/history/sessions")
async def get_history_sessions(limit: int = 10):
    db = HistoryManager()
    with db._lock:
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        # Group by session_id
        cursor = conn.execute("""
            SELECT session_id, timestamp, COUNT(*) as count, GROUP_CONCAT(original_path, '|') as files
            FROM history 
            GROUP BY session_id 
            ORDER BY MIN(id) DESC 
            LIMIT ?
        """, (limit,))
        results = []
        for row in cursor.fetchall():
            results.append({
                "session_id": row[0],
                "timestamp": row[1],
                "count": row[2],
                "files": row[3].split('|')[:5] # Just top 5 for preview
            })
        return results

@app.post("/api/history/undo")
async def undo_session(session_id: str):
    db = HistoryManager()
    moves = db.get_session_moves(session_id)
    if not moves:
        return {"status": "error", "message": "Session not found or already undone"}
    
    undone = 0
    errors = []
    for original, new in moves:
        try:
            p_new = Path(new)
            p_original = Path(original)
            if p_new.exists():
                p_original.parent.mkdir(parents=True, exist_ok=True)
                p_new.rename(p_original)
                undone += 1
        except Exception as e:
            errors.append(str(e))
    
    db.clear_session(session_id)
    return {
        "status": "success" if not errors else "partial",
        "undone": undone,
        "errors": errors
    }
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

# --- Global loop reference for thread-safe broadcasting ---
_main_loop = None

def create_ws_callback(phase="analysis"):
    global _main_loop
    if _main_loop is None:
        try:
            _main_loop = asyncio.get_running_loop()
        except RuntimeError:
            _main_loop = asyncio.get_event_loop()
            
    def callback(current, total, desc, phase=phase):
        asyncio.run_coroutine_threadsafe(
            manager.broadcast({
                "type": "progress",
                "phase": phase,
                "current": current,
                "total": total,
                "description": desc
            }),
            _main_loop
        )
    return callback

# --- Endpoints ---

@app.get("/api/config")
async def get_config():
    try:
        config = AppConfig.load("config.yaml")
        return config.model_dump()
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/config")
async def save_config(config_data: dict):
    try:
        # Validate and save
        config = AppConfig(**config_data)
        import yaml
        with open("config.yaml", "w") as f:
            yaml.dump(config.model_dump(), f)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- Core Task Runner ---

async def run_task(task_func, *args, phase="task", **kwargs):
    """
    Helper to run a synchronous task in a threadpool and broadcast its lifecycle.
    """
    try:
        # We use loop.run_in_executor to keep the main loop responsive
        loop = asyncio.get_running_loop()
        
        def wrapper():
            return task_func(*args, **kwargs)
            
        await loop.run_in_executor(None, wrapper)
        
        await manager.broadcast({
            "type": "complete",
            "phase": phase
        })
    except Exception as e:
        logging.error(f"Task {phase} failed: {e}")
        await manager.broadcast({
            "type": "error",
            "phase": phase,
            "message": str(e)
        })

# --- Endpoints ---

@app.post("/api/analyze")
async def trigger_analyze(background_tasks: BackgroundTasks, path: str = ".", target: Optional[str] = None):
    config = AppConfig.load("config.yaml")
    abs_path = Path(path).resolve()
    abs_target = Path(target).resolve() if target else abs_path
    
    # We define the actual function call
    callback = create_ws_callback("analysis")
    
    background_tasks.add_task(
        run_task, 
        run_analysis, 
        abs_path, 
        abs_target, 
        config, 
        progress_callback=callback,
        phase="analysis"
    )
    return {"status": "started", "path": str(abs_path)}

@app.post("/api/organize")
async def trigger_organize(background_tasks: BackgroundTasks, path: str = ".", target: Optional[str] = None):
    config = AppConfig.load("config.yaml")
    abs_path = Path(path).resolve()
    abs_target = Path(target).resolve() if target else abs_path
    session_id = HistoryManager.generate_session_id()
    
    callback = create_ws_callback("organization")
    
    background_tasks.add_task(
        run_task, 
        run_organization, 
        abs_path, 
        abs_target, 
        config, 
        session_id,
        progress_callback=callback,
        phase="organization"
    )
    return {"status": "started", "session_id": session_id, "path": str(abs_path)}

@app.get("/api/history")
async def get_history(limit: int = 50):
    db = HistoryManager()
    with db._lock:
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        cursor = conn.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,))
        columns = [column[0] for column in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return results

@app.get("/api/stats")
async def get_stats():
    db = HistoryManager()
    with db._lock:
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        cursor = conn.execute("SELECT COUNT(*), COUNT(DISTINCT session_id) FROM history")
        count, sessions = cursor.fetchone()
        return {
            "total_organized": count,
            "total_sessions": sessions,
            "system_cpus": os.cpu_count() or 1
        }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# --- Mount Frontend ---
dashboard_path = Path(__file__).parent / "web" / "dashboard"
if (dashboard_path / "dist").exists():
    app.mount("/", StaticFiles(directory=str(dashboard_path / "dist"), html=True), name="dashboard")
else:
    app.mount("/", StaticFiles(directory=str(dashboard_path), html=True), name="dashboard")

from src.core.utils import generate_thumbnail
from fastapi.responses import FileResponse

@app.get("/api/library")
async def get_library(category: Optional[str] = None):
    db = HistoryManager()
    return db.get_library(category)

@app.get("/api/duplicates")
async def get_duplicates():
    db = HistoryManager()
    return db.get_duplicates()

@app.get("/api/thumbnails")
async def get_thumbnail(path: str):
    try:
        if not os.path.exists(path):
            return {"status": "error", "message": "File not found"}
        
        thumb_path = generate_thumbnail(path)
        return FileResponse(thumb_path)
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.delete("/api/files")
async def delete_file(path: str):
    db = HistoryManager()
    try:
        if os.path.exists(path):
            os.remove(path)
            db.remove_file(path)
            # Find and remove empty parent folders
            from src.cli.main import cleanup_empty_dirs
            cleanup_empty_dirs(Path(path).parent)
            return {"status": "success"}
        else:
            # Even if file is gone, clean up DB
            db.remove_file(path)
            return {"status": "success", "message": "File already gone from disk"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
