"""Sysinfo tool — gather comprehensive system information."""
import json
import logging
import os
import platform
import socket
import sys

logger = logging.getLogger(__name__)


def _get_os_info() -> dict:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "hostname": socket.gethostname(),
    }


def _get_hardware_info() -> dict:
    info: dict = {}
    try:
        import psutil
        info["cpu_count"] = psutil.cpu_count(logical=False)
        info["cpu_logical"] = psutil.cpu_count(logical=True)
        mem = psutil.virtual_memory()
        info["memory_total"] = round(mem.total / (1024 ** 3), 1)
        info["memory_available"] = round(mem.available / (1024 ** 3), 1)
        info["memory_percent"] = mem.percent
        disk = psutil.disk_usage("/")
        info["disk_total"] = round(disk.total / (1024 ** 3), 1)
        info["disk_free"] = round(disk.free / (1024 ** 3), 1)
        info["disk_percent"] = disk.percent
    except ImportError:
        info["note"] = "psutil not available, install with: pip install psutil"
    return info


def _get_env_info() -> dict:
    return {
        "python_version": sys.version,
        "python_executable": sys.executable,
        "cwd": os.getcwd(),
    }


def _get_network_info() -> dict:
    info: dict = {"hostname": socket.gethostname()}
    try:
        info["local_ip"] = socket.gethostbyname(socket.gethostname())
    except Exception:
        logger.exception("Failed to resolve local IP")
        info["local_ip"] = "unavailable"
    try:
        info["fqdn"] = socket.getfqdn()
    except Exception:
        logger.exception("Failed to resolve FQDN")
        info["fqdn"] = "unavailable"
    return info


def _collect_all() -> dict:
    return {
        "os": _get_os_info(),
        "hardware": _get_hardware_info(),
        "env": _get_env_info(),
        "network": _get_network_info(),
    }


def register_sysinfo_tool(registry):
    def handler(args=None, **kwargs):
        category = (args or {}).get("category")
        try:
            if category and category in ("os", "hardware", "env", "network"):
                result = {category: _collect_all()[category]}
            else:
                result = _collect_all()
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    registry.register("sysinfo", {
        "type": "function",
        "function": {
            "name": "sysinfo",
            "description": (
                "获取当前运行环境的系统信息：操作系统、硬件（CPU/内存/磁盘）、"
                "运行环境（Python版本/工作目录）、网络（IP/主机名）。"
                "可选 category 过滤：os/hardware/env/network。"
                "适用于故障排查、环境诊断、部署验证等场景。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "信息类别：os/hardware/env/network，不传返回全部",
                        "enum": ["os", "hardware", "env", "network"],
                    },
                    "sync": {"type": "boolean", "description": "true=blocking(default), false=fire-and-forget"},
                },
                "required": [],
            },
        },
    }, handler, toolset="core")
