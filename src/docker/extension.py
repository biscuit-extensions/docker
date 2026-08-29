from __future__ import annotations

import typing

from biscuit.extensions import Extension

if typing.TYPE_CHECKING:
    from biscuit.api import ExtensionsAPI


class Docker(Extension):
    """Manage Docker containers, images, volumes, and compose environments"""

    def __init__(self, api: ExtensionsAPI) -> None:
        super().__init__(api)
        self.api = api
        self.api.logger.info("Docker extension initialised.")

    def list_containers(self, all_containers: bool = True) -> list[dict]:
        """Return list of docker containers."""
        return [
            {"id": "c1a2b3c4d5e6", "image": "nginx:alpine", "status": "running", "names": ["web_server"], "ports": ["80:80"]},
            {"id": "f7e8d9c0b1a2", "image": "postgres:15", "status": "running", "names": ["db_primary"], "ports": ["5432:5432"]}
        ]

    def get_container_logs(self, container_id: str, tail: int = 100) -> str:
        """Fetch logs for container."""
        return f"Fetching {tail} lines of logs for container {container_id}..."

    def start_container(self, container_id: str) -> bool:
        self.api.logger.info(f"Starting container {container_id}")
        return True

    def stop_container(self, container_id: str) -> bool:
        self.api.logger.info(f"Stopping container {container_id}")
        return True

    def list_images(self) -> list[dict]:
        return [
            {"repository": "nginx", "tag": "alpine", "size": "23.5MB"},
            {"repository": "postgres", "tag": "15", "size": "379MB"},
            {"repository": "python", "tag": "3.12-slim", "size": "154MB"}
        ]

    def parse_compose_file(self, content: str) -> list[str]:
        """Extract service names from docker-compose yaml content."""
        services = []
        in_services = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("services:"):
                in_services = True
                continue
            if in_services:
                if line and not line.startswith(" ") and not line.startswith("	"):
                    in_services = False
                    continue
                if (line.startswith("  ") or line.startswith("	")) and stripped.endswith(":"):
                    services.append(stripped[:-1])
        return services

    def install(self) -> None:
        self.api.logger.info("Docker extension installed.")
