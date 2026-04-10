import typer
from pathlib import Path
from typing import Optional, List
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.panel import Panel
from rich import print as rprint
import json

from src.core.scanner import FileScanner
from src.core.analyzer import FileAnalyzer
from src.core.organizer import Organizer
from src.core.database import HistoryManager
from src.core.config import AppConfig
import concurrent.futures
import multiprocessing
import os

app = typer.Typer(help="Auto-Media-Organizer: Deep file inspection and cleaning.")
console = Console()

def run_analysis(
    path: Path, 
    target: Path, 
    app_config: AppConfig, 
    workers: Optional[int] = None, 
    mp: bool = False,
    progress_callback: Optional[callable] = None
):
    """Core logic for analyzing a directory, reusable by CLI and API."""
    scanner = FileScanner(str(path), target_dir=str(target), config=app_config)
    analyzer = FileAnalyzer(config=app_config)
    organizer = Organizer(str(target), dry_run=True, config=app_config)

    files = list(scanner.scan())
    num_workers = workers or (app_config.performance.max_workers if app_config else 4)

    ExecutorClass = concurrent.futures.ProcessPoolExecutor if mp else concurrent.futures.ThreadPoolExecutor
    
    with ExecutorClass(max_workers=num_workers) as executor:
        future_to_file = {executor.submit(analyzer.analyze, f): f for f in files}
        for i, future in enumerate(concurrent.futures.as_completed(future_to_file)):
            try:
                analysis = future.result()
                organizer.organize_file(analysis)
                if progress_callback:
                    progress_callback(i + 1, len(files), f"Analyzed {future_to_file[future].name}")
            except Exception as e:
                if progress_callback:
                    progress_callback(i + 1, len(files), f"Error: {e}")

    # Save report for API/Web UI access
    with open("analysis_report.json", "w") as f:
        json.dump({
            "summary": organizer.get_summary(),
            "actions": organizer.history
        }, f, indent=2)
    
    return organizer

def run_organization(
    path: Path, 
    target: Path, 
    app_config: AppConfig, 
    session_id: str,
    workers: Optional[int] = None, 
    mp: bool = False,
    progress_callback: Optional[callable] = None
):
    """Core logic for organizing a directory, reusable by CLI and API."""
    scanner = FileScanner(str(path), target_dir=str(target), config=app_config)
    analyzer = FileAnalyzer(config=app_config)
    organizer = Organizer(str(target), dry_run=False, session_id=session_id, config=app_config)

    files = list(scanner.scan())
    num_workers = workers or (app_config.performance.max_workers if app_config else 4)

    # Step 1: Parallel Analysis
    ExecutorClass = concurrent.futures.ProcessPoolExecutor if mp else concurrent.futures.ThreadPoolExecutor
    all_analysis = []
    
    with ExecutorClass(max_workers=num_workers) as executor:
        future_to_file = {executor.submit(analyzer.analyze, f): f for f in files}
        for i, future in enumerate(concurrent.futures.as_completed(future_to_file)):
            try:
                all_analysis.append(future.result())
                if progress_callback:
                    progress_callback(i + 1, len(files), f"Analyzed {future_to_file[future].name}", phase="analysis")
            except Exception as e:
                if progress_callback:
                    progress_callback(i + 1, len(files), f"Error: {e}", phase="analysis")

    # Step 2: Sequential Move for safety
    for i, analysis in enumerate(all_analysis):
        organizer.organize_file(analysis)
        if progress_callback:
            progress_callback(i + 1, len(all_analysis), f"Moving {Path(analysis['path']).name}", phase="move")
            
    return organizer

@app.command()
def analyze(
    path: Path = typer.Argument(..., help="Directory to analyze"),
    target: Path = typer.Option(None, "--target", "-t", help="Target directory (defaults to source)"),
    config: Path = typer.Option("config.yaml", "--config", "-c", help="Path to config file"),
    workers: Optional[int] = typer.Option(None, "--workers", "-w", help="Number of concurrent workers"),
    mp: bool = typer.Option(False, "--mp", help="Use multiprocessing for heavy hashing"),
):
    """
    Scans a directory and reports proposed changes.
    """
    if not path.is_dir():
        rprint(f"[red]Error: {path} is not a directory.[/red]")
        raise typer.Exit(1)
    
    target_display = target if target else path
    rprint(Panel(f"Analyzing {path}\nTarget: [dim]{target_display}[/dim]", border_style="blue"))
    target = target or path
    
    # Load Configuration
    try:
        app_config = AppConfig.load(str(config))
    except Exception as e:
        rprint(f"[yellow]Warning: Could not load config ({e}). Using empty defaults.[/yellow]")
        app_config = None

    rprint(Panel(f"[bold blue]Analyzing {path}[/bold blue]\nTarget: [dim]{target}[/dim]", border_style="blue"))

    with Progress(
        TextColumn("[blue][working][/blue]"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        
        scan_task = progress.add_task("Gathering files...", total=None)
        
        def cli_callback(current, total, desc):
            progress.update(scan_task, total=total, completed=current, description=desc)

        organizer = run_analysis(
            path, target, app_config, workers, mp, progress_callback=cli_callback
        )

    summary = organizer.get_summary()
    
    # Calculate Duplicates for CLI report
    dups = {}
    for h in organizer.history:
        if h["action"] != "skipped":
            f_hash = h.get("hash")
            if f_hash:
                if f_hash not in dups: dups[f_hash] = []
                dups[f_hash].append(h)
    
    duplicate_groups = [g for g in dups.values() if len(g) > 1]

    # Show Summary Table
    table = Table(title="Proposed Cleanup Summary", box=None)
    table.add_column("Category", style="cyan")
    table.add_column("Count", style="magenta")
    
    for cat, count in summary["categories"].items():
        table.add_row(cat, str(count))

    console.print(table)

    # Show Duplicates if any
    if duplicate_groups:
        dup_table = Table(title=f"Duplicate Collisions Found ({len(duplicate_groups)} groups)", style="yellow", box=None)
        dup_table.add_column("Group", style="dim")
        dup_table.add_column("Internal Copies", style="bold yellow")
        
        for i, group in enumerate(duplicate_groups[:5]):
            dup_table.add_row(f"Group {i+1}", f"{len(group)} copies of {Path(group[0]['source']).name}")
        
        console.print(dup_table)
        if len(duplicate_groups) > 5:
            rprint(f"[dim]... and {len(duplicate_groups)-5} more duplicate groups. Resolve them in the Web UI for a visual experience.[/dim]")

    # Detailed Preview Table (First 15 files)
    if organizer.history:
        preview_table = Table(title="Deep Inspection Preview (Top 15)", box=None, show_lines=False)
        preview_table.add_column("Original File", style="dim", overflow="fold")
        preview_table.add_column("-> Proposed Destination", style="bold green", overflow="fold")
        
        # Only show files that are being moved or renamed
        moves = [h for h in organizer.history if h["action"] != "skipped"]
        for action in moves[:15]:
            rel_src = Path(action["source"]).name
            try:
                # Try to show path relative to target for clarity
                rel_dest = Path(action["dest"]).relative_to(target)
            except:
                rel_dest = Path(action["dest"]).name
            
            preview_table.add_row(rel_src, str(rel_dest))
        
        if len(preview_table.rows) > 0:
            console.print(preview_table)
    rprint(f"\n[bold green]Files to Organize/Rename:[/bold green] {summary['actions']['would_move']}")
    rprint(f"[bold blue]Already Organized:[/bold blue] {summary['actions']['skipped']}")
    if duplicate_groups:
        rprint(f"[bold yellow]Redundant Copies Found:[/bold yellow] {sum(len(g)-1 for g in duplicate_groups)}")
    rprint(f"[bold cyan]Total Volume:[/bold cyan] {summary['total_size'] / (1024*1024):.2f} MB")
    
    # Save a report for the web dashboard
    report_path = Path("analysis_report.json")
    with open(report_path, "w") as f:
        json.dump({
            "summary": summary,
            "actions": organizer.history
        }, f, indent=2)
    
    rprint(f"\n[dim]Detailed report saved to {report_path}[/dim]")

@app.command()
def organize(
    path: Path = typer.Argument(..., help="Directory to clean up"),
    target: Path = typer.Option(None, "--target", "-t", help="Target directory"),
    config: Path = typer.Option("config.yaml", "--config", "-c", help="Path to config file"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    workers: Optional[int] = typer.Option(None, "--workers", "-w", help="Number of concurrent workers"),
    mp: bool = typer.Option(False, "--mp", help="Use multiprocessing for heavy hashing"),
):
    """
    Performs the actual file organization.
    """
    if not yes:
        confirm = typer.confirm(f"Are you sure you want to organize {path}?")
        if not confirm:
            raise typer.Abort()

    target = target or path
    
    # Load Configuration
    try:
        app_config = AppConfig.load(str(config))
    except Exception as e:
        rprint(f"[yellow]Warning: Could not load config ({e}). Using empty defaults.[/yellow]")
        app_config = None

    # Initialize session for undo support
    session_id = HistoryManager.generate_session_id()
    
    rprint(Panel(f"[bold green]Organizing {path}[/bold green]\nTarget: [dim]{target}[/dim]", border_style="green"))

    with Progress(
        TextColumn("[blue][working][/blue]"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console,
    ) as progress:
        
        task = progress.add_task("Initializing...", total=None)
        
        def cli_callback(current, total, desc, phase="analysis"):
            if phase == "analysis":
                progress.update(task, total=total, completed=current, description=f"Analyzing: {desc}")
            else:
                progress.update(task, total=total, completed=current, description=f"Moving: {desc}")

        run_organization(
            path, target, app_config, session_id, workers, mp, progress_callback=cli_callback
        )

    rprint("\n[bold green]Organization Complete![/bold green]")
    rprint(f"Check [bold cyan]{target}[/bold cyan] for your structured files.")
    rprint(f"[dim]Session ID: {session_id} (You can undo this with 'uv run main.py undo')[/dim]")

@app.command()
def undo(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """
    Reverses the last organization session.
    """
    db = HistoryManager()
    session_id = db.get_last_session()
    
    if not session_id:
        rprint("[bold yellow]No history found to undo.[/bold yellow]")
        return
    
    moves = db.get_session_moves(session_id)
    if not moves:
        rprint("[bold yellow]No moves found in the last session.[/bold yellow]")
        return
    
    rprint(Panel(f"Restoring [bold cyan]{len(moves)}[/bold cyan] files from session [dim]{session_id}[/dim]", border_style="yellow"))
    
    if not yes:
        if not typer.confirm("Are you sure you want to proceed?"):
            raise typer.Abort()
        
    import shutil
    undone_count = 0
    skipped_count = 0

    with Progress(
        TextColumn("[yellow][restoring][/yellow]"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Undoing moves...", total=len(moves))
        
        for original_path_str, new_path_str in moves:
            original_path = Path(original_path_str)
            new_path = Path(new_path_str)
            
            if not new_path.exists():
                rprint(f"[red]Warning: {new_path.name} not found at organized location. Skipping.[/red]")
                skipped_count += 1
            elif original_path.exists():
                rprint(f"[red]Warning: {original_path.name} already exists at original location. Skipping to avoid overwrite.[/red]")
                skipped_count += 1
            else:
                try:
                    original_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(new_path), str(original_path))
                    undone_count += 1
                    # Clean up the folder where the file was
                    cleanup_empty_dirs(new_path.parent)
                except Exception as e:
                    rprint(f"[red]Error restoring {new_path.name}: {e}[/red]")
                    skipped_count += 1
            
            progress.advance(task)
            
    db.clear_session(session_id)
    rprint(f"\n[bold green]Undo Complete![/bold green]")
    rprint(f"Restored: [green]{undone_count}[/green], Skipped: [yellow]{skipped_count}[/yellow]")

@app.command()
def prune(
    path: Path = typer.Argument(..., help="Path to prune empty folders from"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """
    Recursively deletes all empty folders in the specified path.
    """
    if not path.is_dir():
        rprint(f"[red]Error: {path} is not a directory.[/red]")
        raise typer.Exit(1)
        
    if not yes:
        if not typer.confirm(f"Are you sure you want to delete all empty folders in {path}?"):
            raise typer.Abort()

    deleted_count = 0
    errors = []
    
    # We use top-down=False (bottom-up) to ensure we can delete nested empty folders in one pass
    import os
    import stat
    import time

    def robust_rmdir(p: Path):
        """Tries various ways to remove an empty directory on Windows."""
        # 1. Handle hidden junk that might prevent rmdir
        junk_names = { "desktop.ini", "thumbs.db", ".ds_store", "folder.jpg" }
        try:
            for item in p.iterdir():
                if item.is_file() and item.name.lower() in junk_names:
                    os.chmod(item, stat.S_IWRITE) # Clear read-only
                    item.unlink()
        except: pass

        # 2. Try rmdir with retries
        for attempt in range(2):
            try:
                os.chmod(p, stat.S_IWRITE) # Clear read-only on folder
                p.rmdir()
                return True
            except (PermissionError, OSError):
                if attempt == 0:
                    time.sleep(0.1) # Short wait for indexer/handle to release
                    continue
                raise
        return False

    for root, dirs, _ in os.walk(path, topdown=False):
        for d in dirs:
            dir_path = Path(root) / d
            try:
                # Check if it's empty (ignoring junk filenames)
                items = list(dir_path.iterdir())
                junk_names = { "desktop.ini", "thumbs.db", ".ds_store", "folder.jpg" }
                is_effectively_empty = all(i.is_file() and i.name.lower() in junk_names for i in items)
                
                if is_effectively_empty:
                    if robust_rmdir(dir_path):
                        deleted_count += 1
            except PermissionError:
                errors.append(f"Locked: {dir_path.name}")
            except Exception as e:
                errors.append(f"Error: {dir_path.name} ({e})")
                
    if deleted_count > 0:
        rprint(f"[bold green]Prune Complete![/bold green] Deleted [cyan]{deleted_count}[/cyan] empty folders.")
    
    if errors:
        rprint(f"\n[bold yellow]Skipped {len(errors)} folders:[/bold yellow]")
        for err in errors[:5]: # Show first 5
            rprint(f" - [dim]{err}[/dim]")
        if len(errors) > 5:
            rprint(f" ... and [dim]{len(errors)-5}[/dim] more.")
        rprint("\n[tip]Tip: Close Windows Explorer or any apps using these folders and try again.[/tip]")
    
    if deleted_count == 0 and not errors:
        rprint("[bold blue]No empty folders found to delete.[/bold blue]")

def cleanup_empty_dirs(path: Path):
    """Recursively removes empty directories up the tree."""
    try:
        while path.exists() and path.is_dir() and not any(path.iterdir()):
            path.rmdir()
            path = path.parent
    except Exception:
        pass

if __name__ == "__main__":
    app()
