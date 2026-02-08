"""
WebGUI Server for ERM-CE Bot
Provides real-time system monitoring and bot statistics
"""

import asyncio
import json
import logging
import os
import platform
import time
from datetime import datetime
from typing import Dict, List

import psutil
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState

# Try to import uvicorn, handle if not available
try:
    import uvicorn
except ImportError:
    uvicorn = None

app = FastAPI(title="ERM-CE Bot Dashboard", version="1.0.0")

# Store reference to the bot instance
bot_instance = None

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logging.info(f"WebSocket client connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logging.info(f"WebSocket client disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Send message to all connected clients"""
        disconnected = []
        for connection in self.active_connections:
            try:
                if connection.client_state == WebSocketState.CONNECTED:
                    await connection.send_json(message)
                else:
                    disconnected.append(connection)
            except Exception as e:
                logging.error(f"Error broadcasting to client: {e}")
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()


def get_system_info() -> Dict:
    """Get comprehensive system information"""
    try:
        # CPU Information
        cpu_percent = psutil.cpu_percent(interval=0.1, percpu=False)
        cpu_count = psutil.cpu_count(logical=True)
        cpu_count_physical = psutil.cpu_count(logical=False)
        cpu_freq = psutil.cpu_freq()
        
        # Memory Information
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        # Disk Information
        disk = psutil.disk_usage('/')
        
        # Network Information
        net_io = psutil.net_io_counters()
        
        # Process Information
        process = psutil.Process(os.getpid())
        process_memory = process.memory_info()
        process_cpu = process.cpu_percent(interval=0.1)
        
        # System Information
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        
        return {
            "timestamp": datetime.now().isoformat(),
            "cpu": {
                "percent": round(cpu_percent, 2),
                "count_logical": cpu_count,
                "count_physical": cpu_count_physical,
                "frequency_mhz": round(cpu_freq.current, 2) if cpu_freq else 0,
                "frequency_max_mhz": round(cpu_freq.max, 2) if cpu_freq else 0,
            },
            "memory": {
                "total_gb": round(memory.total / (1024**3), 2),
                "available_gb": round(memory.available / (1024**3), 2),
                "used_gb": round(memory.used / (1024**3), 2),
                "percent": round(memory.percent, 2),
                "swap_total_gb": round(swap.total / (1024**3), 2),
                "swap_used_gb": round(swap.used / (1024**3), 2),
                "swap_percent": round(swap.percent, 2),
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent": round(disk.percent, 2),
            },
            "network": {
                "bytes_sent_mb": round(net_io.bytes_sent / (1024**2), 2),
                "bytes_recv_mb": round(net_io.bytes_recv / (1024**2), 2),
                "packets_sent": net_io.packets_sent,
                "packets_recv": net_io.packets_recv,
            },
            "process": {
                "memory_mb": round(process_memory.rss / (1024**2), 2),
                "cpu_percent": round(process_cpu, 2),
                "threads": process.num_threads(),
            },
            "system": {
                "platform": platform.system(),
                "platform_release": platform.release(),
                "platform_version": platform.version(),
                "architecture": platform.machine(),
                "hostname": platform.node(),
                "python_version": platform.python_version(),
                "boot_time": boot_time.isoformat(),
                "uptime_seconds": int(uptime.total_seconds()),
                "uptime_human": str(uptime).split('.')[0],  # Remove microseconds
            }
        }
    except Exception as e:
        logging.error(f"Error getting system info: {e}")
        return {
            "error": "Internal error while collecting system information",
            "timestamp": datetime.now().isoformat()
        }


def get_bot_info() -> Dict:
    """Get bot-specific information"""
    if bot_instance is None:
        return {
            "status": "not_connected",
            "message": "Bot instance not initialized"
        }
    
    try:
        bot_uptime = time.time() - bot_instance.start_time if hasattr(bot_instance, 'start_time') else 0
        
        return {
            "status": "online" if bot_instance.is_ready() else "starting",
            "bot_name": str(bot_instance.user) if bot_instance.user else "Unknown",
            "bot_id": bot_instance.user.id if bot_instance.user else 0,
            "guild_count": len(bot_instance.guilds),
            "user_count": sum(guild.member_count for guild in bot_instance.guilds),
            "uptime_seconds": int(bot_uptime),
            "uptime_human": f"{int(bot_uptime // 3600)}h {int((bot_uptime % 3600) // 60)}m {int(bot_uptime % 60)}s",
            "latency_ms": round(bot_instance.latency * 1000, 2) if bot_instance.latency else 0,
            "shard_count": bot_instance.shard_count or 1,
            "commands_count": len(bot_instance.tree.get_commands()) if hasattr(bot_instance, 'tree') else 0,
        }
    except Exception as e:
        logging.error(f"Error getting bot info: {e}")
        return {
            "status": "error",
            "error": "Internal error while collecting bot information"
        }


@app.get("/")
async def get_dashboard():
    """Serve the dashboard HTML"""
    html_file = os.path.join(os.path.dirname(__file__), "dashboard.html")
    try:
        with open(html_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Dashboard not found</h1><p>Please ensure dashboard.html is in the webgui directory.</p>",
            status_code=404
        )


@app.get("/api/system")
async def get_system_stats():
    """Get current system statistics"""
    return get_system_info()


@app.get("/api/bot")
async def get_bot_stats():
    """Get current bot statistics"""
    return get_bot_info()


@app.get("/api/combined")
async def get_combined_stats():
    """Get both system and bot statistics"""
    return {
        "system": get_system_info(),
        "bot": get_bot_info()
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await manager.connect(websocket)
    
    try:
        # Send initial data immediately
        await websocket.send_json({
            "type": "initial",
            "system": get_system_info(),
            "bot": get_bot_info()
        })
        
        # Keep connection alive and wait for client messages
        while True:
            try:
                # Wait for client messages (can be used for commands later)
                data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                # Process client commands here if needed
            except asyncio.TimeoutError:
                # No message received, continue
                pass
            
            await asyncio.sleep(0.1)  # Small delay to prevent tight loop
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logging.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)


async def broadcast_stats():
    """Background task to broadcast system stats to all connected clients"""
    while True:
        try:
            if manager.active_connections:
                stats = {
                    "type": "update",
                    "system": get_system_info(),
                    "bot": get_bot_info()
                }
                await manager.broadcast(stats)
        except Exception as e:
            logging.error(f"Error broadcasting stats: {e}")
        
        await asyncio.sleep(1)  # Update every second


def start_webgui(bot, host: str = "0.0.0.0", port: int = 8080):
    """
    Start the web GUI server
    
    Args:
        bot: The Discord bot instance
        host: Host to bind to (default: 0.0.0.0 for all interfaces)
        port: Port to listen on (default: 8080)
    """
    global bot_instance
    bot_instance = bot
    
    if uvicorn is None:
        logging.error("uvicorn not installed. Cannot start WebGUI. Install with: pip install uvicorn")
        return
    
    logging.info(f"Starting WebGUI on http://{host}:{port}")
    
    # Start the background task for broadcasting stats
    asyncio.create_task(broadcast_stats())
    
    # Run the server (this should be called from an async context)
    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="info",
        access_log=True
    )
    server = uvicorn.Server(config)
    
    return server


async def start_webgui_async(bot, host: str = "0.0.0.0", port: int = 8080):
    """
    Start the web GUI server asynchronously
    """
    global bot_instance
    bot_instance = bot
    
    if uvicorn is None:
        logging.error("uvicorn not installed. Cannot start WebGUI.")
        return
    
    logging.info(f"Starting WebGUI on http://{host}:{port}")
    
    # Start the background task
    asyncio.create_task(broadcast_stats())
    
    # Run the server
    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="info",
        access_log=True
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    # For testing without bot
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8080)
