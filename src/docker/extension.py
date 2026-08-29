from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import typing
from typing import Any

from biscuit.extensions import Extension

if typing.TYPE_CHECKING:
    from biscuit.api import ExtensionsAPI

try:
    import yaml
except ImportError:
    yaml = None


class Docker(Extension):
    """Production Docker extension for Biscuit IDE.

    Manages container lifecycles, image inspection, compose services, and status indicators.
    """

    def __init__(self, api: ExtensionsAPI) -> None:
        super().__init__(api)
        self.api = api
        self.docker_path = shutil.which("docker") or "docker"
        self._containers_cache: list[dict[str, Any]] = []
        self._images_cache: list[dict[str, Any]] = []
        self.statusbar_button = None

        if hasattr(self.api, "statusbar") and hasattr(self.api.statusbar, "add_button"):
            try:
                self.statusbar_button = self.api.statusbar.add_button(
                    text="Docker: 0 running",
                    icon="server",
                    callback=self.refresh,
                    description="Docker container status",
                )
                if self.statusbar_button:
                    self.statusbar_button.show()
            except Exception as e:
                self.api.logger.warning(f"Docker statusbar button registration: {e}")

        self._register_commands()
        self.api.logger.info("Docker extension loaded successfully.")

    def _register_commands(self) -> None:
        if not hasattr(self.api, "commands"):
            return
        cmds = {
            "docker.list_containers": self.list_containers,
            "docker.start_container": self.start_container,
            "docker.stop_container": self.stop_container,
            "docker.restart_container": self.restart_container,
            "docker.view_logs": self.get_container_logs,
            "docker.compose_up": self.compose_up,
            "docker.compose_down": self.compose_down,
            "docker.refresh": self.refresh,
        }
        for name, callback in cmds.items():
            self.api.commands.register_command(name, callback)

    def run_cli(self, args: list[str], timeout: int = 30) -> tuple[int, str, str]:
        """Execute docker CLI command and return (returncode, stdout, stderr)."""
        cmd = [self.docker_path] + args
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return res.returncode, res.stdout, res.stderr
        except FileNotFoundError:
            self.api.logger.error("Docker executable not found on system PATH.")
            return -1, "", "Docker executable not found on system PATH."
        except subprocess.TimeoutExpired:
            self.api.logger.error(f"Docker command timed out after {timeout}s: {' '.join(cmd)}")
            return -2, "", "Command timed out."
        except Exception as e:
            self.api.logger.error(f"Docker execution error: {e}")
            return -3, "", str(e)

    def parse_json_stream(self, output: str) -> list[dict[str, Any]]:
        """Parse stream of JSON objects output by docker --format '{{json .}}'."""
        results = []
        for line in output.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return results

    def list_containers(self, all_containers: bool = True) -> list[dict[str, Any]]:
        """Query Docker containers via docker ps --format '{{json .}}'."""
        args = ["ps", "--format", "{{json .}}"]
        if all_containers:
            args.append("-a")

        code, stdout, stderr = self.run_cli(args)
        if code == 0:
            raw_list = self.parse_json_stream(stdout)
            containers = []
            running_count = 0
            for item in raw_list:
                status_str = item.get("Status", "").lower()
                state_str = item.get("State", "").lower()
                is_running = state_str == "running" or "up" in status_str
                if is_running:
                    running_count += 1
                containers.append({
                    "id": item.get("ID", ""),
                    "image": item.get("Image", ""),
                    "status": item.get("Status", ""),
                    "state": item.get("State", "running" if is_running else "exited"),
                    "names": [n.strip() for n in item.get("Names", "").split(",") if n.strip()],
                    "ports": [p.strip() for p in item.get("Ports", "").split(",") if p.strip()],
                    "created": item.get("CreatedAt", ""),
                })
            self._containers_cache = containers
            self.update_statusbar(running_count)
            return containers

        self.api.logger.warning(f"Failed to list containers: {stderr.strip()}")
        return self._containers_cache

    def start_container(self, container_id: str) -> bool:
        """Start a stopped container."""
        code, _, stderr = self.run_cli(["start", container_id])
        if code == 0:
            self.api.logger.info(f"Container {container_id} started.")
            self.refresh()
            return True
        self.api.logger.error(f"Failed to start container {container_id}: {stderr.strip()}")
        return False

    def stop_container(self, container_id: str, timeout: int = 10) -> bool:
        """Stop a running container."""
        code, _, stderr = self.run_cli(["stop", "-t", str(timeout), container_id])
        if code == 0:
            self.api.logger.info(f"Container {container_id} stopped.")
            self.refresh()
            return True
        self.api.logger.error(f"Failed to stop container {container_id}: {stderr.strip()}")
        return False

    def restart_container(self, container_id: str, timeout: int = 10) -> bool:
        """Restart a container."""
        code, _, stderr = self.run_cli(["restart", "-t", str(timeout), container_id])
        if code == 0:
            self.api.logger.info(f"Container {container_id} restarted.")
            self.refresh()
            return True
        self.api.logger.error(f"Failed to restart container {container_id}: {stderr.strip()}")
        return False

    def remove_container(self, container_id: str, force: bool = False) -> bool:
        """Remove a container."""
        args = ["rm"]
        if force:
            args.append("-f")
        args.append(container_id)
        code, _, stderr = self.run_cli(args)
        if code == 0:
            self.api.logger.info(f"Container {container_id} removed.")
            self.refresh()
            return True
        self.api.logger.error(f"Failed to remove container {container_id}: {stderr.strip()}")
        return False

    def pause_container(self, container_id: str) -> bool:
        """Pause processes within a container."""
        code, _, stderr = self.run_cli(["pause", container_id])
        return code == 0

    def unpause_container(self, container_id: str) -> bool:
        """Unpause processes within a container."""
        code, _, stderr = self.run_cli(["unpause", container_id])
        return code == 0

    def get_container_logs(self, container_id: str, tail: int = 100, timestamps: bool = False) -> str:
        """Fetch stdout and stderr logs for a container."""
        args = ["logs", "--tail", str(tail)]
        if timestamps:
            args.append("--timestamps")
        args.append(container_id)
        code, stdout, stderr = self.run_cli(args)
        if code == 0:
            return stdout
        return stderr

    def list_images(self) -> list[dict[str, Any]]:
        """List local Docker images."""
        code, stdout, stderr = self.run_cli(["images", "--format", "{{json .}}"])
        if code == 0:
            raw_list = self.parse_json_stream(stdout)
            images = []
            for item in raw_list:
                images.append({
                    "id": item.get("ID", ""),
                    "repository": item.get("Repository", ""),
                    "tag": item.get("Tag", ""),
                    "size": item.get("Size", ""),
                    "created": item.get("CreatedAt", ""),
                })
            self._images_cache = images
            return images

        self.api.logger.warning(f"Failed to list images: {stderr.strip()}")
        return self._images_cache

    def inspect_image(self, image_id: str) -> dict[str, Any]:
        """Inspect a local Docker image and extract metadata."""
        code, stdout, stderr = self.run_cli(["inspect", image_id])
        if code == 0 and stdout.strip():
            try:
                data = json.loads(stdout)
                if isinstance(data, list) and data:
                    item = data[0]
                    config = item.get("Config", {})
                    return {
                        "id": item.get("Id", image_id),
                        "architecture": item.get("Architecture", ""),
                        "os": item.get("Os", ""),
                        "size": item.get("Size", 0),
                        "entrypoint": config.get("Entrypoint", []),
                        "cmd": config.get("Cmd", []),
                        "env": config.get("Env", []),
                        "exposed_ports": list(config.get("ExposedPorts", {}).keys()),
                        "layers": item.get("RootFS", {}).get("Layers", []),
                    }
            except json.JSONDecodeError:
                pass
        self.api.logger.warning(f"Failed to inspect image {image_id}: {stderr.strip()}")
        return {}

    def parse_compose_file(self, content: str) -> dict[str, dict[str, Any]]:
        """Parse docker-compose yaml content into structured service definitions."""
        if yaml is not None:
            try:
                data = yaml.safe_load(content)
                if isinstance(data, dict):
                    services = data.get("services", {})
                    if isinstance(services, dict):
                        return services
            except Exception as e:
                self.api.logger.warning(f"PyYAML compose parse error: {e}")

        # Native fallback parser for compose files
        services: dict[str, dict[str, Any]] = {}
        in_services = False
        current_service: str | None = None

        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            indent = len(line) - len(line.lstrip(" "))

            if stripped.startswith("services:"):
                in_services = True
                continue

            if in_services:
                if indent == 0 and not stripped.startswith("services:"):
                    in_services = False
                    current_service = None
                    continue

                if indent in (2, 4) and stripped.endswith(":"):
                    name = stripped[:-1].strip()
                    current_service = name
                    services[current_service] = {}
                    continue

                if current_service and ":" in stripped:
                    parts = stripped.split(":", 1)
                    key = parts[0].strip()
                    val = parts[1].strip()
                    if val:
                        services[current_service][key] = val

        return services

    def get_compose_services(self, content: str) -> list[str]:
        """Convenience method returning list of service names."""
        return list(self.parse_compose_file(content).keys())

    def compose_up(self, compose_file: str | None = None, detach: bool = True) -> bool:
        """Run docker compose up."""
        args = ["compose"]
        if compose_file:
            args.extend(["-f", compose_file])
        args.append("up")
        if detach:
            args.append("-d")
        code, stdout, stderr = self.run_cli(args, timeout=120)
        return code == 0

    def compose_down(self, compose_file: str | None = None) -> bool:
        """Run docker compose down."""
        args = ["compose"]
        if compose_file:
            args.extend(["-f", compose_file])
        args.append("down")
        code, stdout, stderr = self.run_cli(args, timeout=60)
        return code == 0

    def compose_ps(self, compose_file: str | None = None) -> list[dict[str, Any]]:
        """Query compose services status."""
        args = ["compose"]
        if compose_file:
            args.extend(["-f", compose_file])
        args.extend(["ps", "--format", "json"])
        code, stdout, _ = self.run_cli(args)
        if code == 0:
            return self.parse_json_stream(stdout)
        return []

    def update_statusbar(self, count: int) -> None:
        """Update the statusbar indicator."""
        if self.statusbar_button:
            self.statusbar_button.change_text(f"Docker: {count} running")

    def refresh(self) -> None:
        """Refresh container and image states."""
        self.list_containers(all_containers=True)
        self.list_images()

    def install(self) -> None:
        """Called upon extension installation."""
        self.refresh()
        self.api.logger.info("Docker extension installed and refreshed.")
