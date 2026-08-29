from __future__ import annotations

import json
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import tomllib
from src.docker import setup
from src.docker.extension import Docker


class TestDockerExtension:
    def test_setup_and_registration(self, mock_api) -> None:
        ext = setup(mock_api)
        assert "docker" in mock_api.registered_extensions
        assert isinstance(ext, Docker)
        assert "docker.list_containers" in mock_api.commands.commands
        assert "docker.start_container" in mock_api.commands.commands
        assert "docker.stop_container" in mock_api.commands.commands

    def test_extension_manifest_contract(self) -> None:
        manifest_path = Path(__file__).parent.parent / "extension.toml"
        assert manifest_path.exists()
        with open(manifest_path, "rb") as f:
            data = tomllib.load(f)
        assert data["extension"]["id"] == "docker"
        assert data["extension"]["author"] == "tomlin7"
        assert data["extension"]["version"] == "0.2.0"
        assert "docker" in data["dependencies"]["tools"]
        assert any("pyyaml" in dep.lower() for dep in data["dependencies"]["python"])

    def test_list_containers_json_stream(self, mock_api) -> None:
        ext = Docker(mock_api)
        sample_output = (
            json.dumps({
                "ID": "c1a2b3c4d5e6",
                "Image": "nginx:alpine",
                "Status": "Up 2 hours",
                "State": "running",
                "Names": "web_server,nginx_proxy",
                "Ports": "0.0.0.0:80->80/tcp",
                "CreatedAt": "2026-10-18 20:00:00",
            })
            + "\n"
            + json.dumps({
                "ID": "f7e8d9c0b1a2",
                "Image": "postgres:15",
                "Status": "Exited (0) 5 minutes ago",
                "State": "exited",
                "Names": "db_primary",
                "Ports": "5432/tcp",
                "CreatedAt": "2026-10-18 19:00:00",
            })
        )

        with patch.object(ext, "run_cli", return_value=(0, sample_output, "")):
            containers = ext.list_containers(all_containers=True)
            assert len(containers) == 2
            assert containers[0]["id"] == "c1a2b3c4d5e6"
            assert containers[0]["state"] == "running"
            assert "web_server" in containers[0]["names"]
            assert containers[1]["id"] == "f7e8d9c0b1a2"
            assert containers[1]["state"] == "exited"
            assert ext.statusbar_button.text == "Docker: 1 running"

    def test_container_lifecycle(self, mock_api) -> None:
        ext = Docker(mock_api)
        with patch.object(ext, "run_cli", return_value=(0, "c1a2b3c4d5e6\n", "")) as mock_run:
            assert ext.start_container("c1a2b3c4d5e6") is True
            mock_run.assert_any_call(["start", "c1a2b3c4d5e6"])

            assert ext.stop_container("c1a2b3c4d5e6", timeout=5) is True
            mock_run.assert_any_call(["stop", "-t", "5", "c1a2b3c4d5e6"])

            assert ext.restart_container("c1a2b3c4d5e6", timeout=5) is True
            mock_run.assert_any_call(["restart", "-t", "5", "c1a2b3c4d5e6"])

            assert ext.pause_container("c1a2b3c4d5e6") is True
            mock_run.assert_any_call(["pause", "c1a2b3c4d5e6"])

            assert ext.unpause_container("c1a2b3c4d5e6") is True
            mock_run.assert_any_call(["unpause", "c1a2b3c4d5e6"])

            assert ext.remove_container("c1a2b3c4d5e6", force=True) is True
            mock_run.assert_any_call(["rm", "-f", "c1a2b3c4d5e6"])

    def test_container_logs(self, mock_api) -> None:
        ext = Docker(mock_api)
        log_content = "2026-10-18T20:01:00Z Server started on port 80\n2026-10-18T20:02:00Z GET /index.html 200\n"
        with patch.object(ext, "run_cli", return_value=(0, log_content, "")):
            logs = ext.get_container_logs("c1a2b3c4d5e6", tail=50, timestamps=True)
            assert "Server started on port 80" in logs

    def test_list_and_inspect_images(self, mock_api) -> None:
        ext = Docker(mock_api)
        img_output = json.dumps({
            "ID": "sha256:1234567890",
            "Repository": "nginx",
            "Tag": "alpine",
            "Size": "23.5MB",
            "CreatedAt": "2026-10-01",
        })
        with patch.object(ext, "run_cli", return_value=(0, img_output, "")):
            images = ext.list_images()
            assert len(images) == 1
            assert images[0]["repository"] == "nginx"
            assert images[0]["tag"] == "alpine"

        inspect_output = json.dumps([{
            "Id": "sha256:1234567890",
            "Architecture": "amd64",
            "Os": "linux",
            "Size": 24641536,
            "Config": {
                "Cmd": ["nginx", "-g", "daemon off;"],
                "ExposedPorts": {"80/tcp": {}},
                "Env": ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"],
            },
            "RootFS": {"Layers": ["sha256:layer1", "sha256:layer2"]},
        }])
        with patch.object(ext, "run_cli", return_value=(0, inspect_output, "")):
            meta = ext.inspect_image("sha256:1234567890")
            assert meta["architecture"] == "amd64"
            assert meta["os"] == "linux"
            assert "80/tcp" in meta["exposed_ports"]
            assert len(meta["layers"]) == 2

    def test_parse_compose_file(self, mock_api) -> None:
        ext = Docker(mock_api)
        compose_yaml = """
version: '3.8'
services:
  web:
    image: nginx:alpine
    ports:
      - "80:80"
  database:
    image: postgres:15
    environment:
      POSTGRES_PASSWORD: secret
"""
        parsed = ext.parse_compose_file(compose_yaml)
        assert "web" in parsed
        assert "database" in parsed
        services = ext.get_compose_services(compose_yaml)
        assert "web" in services
        assert "database" in services

    def test_compose_cli_lifecycle(self, mock_api) -> None:
        ext = Docker(mock_api)
        with patch.object(ext, "run_cli", return_value=(0, "", "")) as mock_run:
            assert ext.compose_up("docker-compose.yml") is True
            mock_run.assert_called_with(["compose", "-f", "docker-compose.yml", "up", "-d"], timeout=120)

            assert ext.compose_down("docker-compose.yml") is True
            mock_run.assert_called_with(["compose", "-f", "docker-compose.yml", "down"], timeout=60)

    def test_cli_error_handling(self, mock_api) -> None:
        ext = Docker(mock_api)
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            code, stdout, stderr = ext.run_cli(["ps"])
            assert code == -1
            assert "not found" in stderr

    def test_app_instance_compatibility(self, app_instance) -> None:
        ext = setup(app_instance.api)
        assert ext is not None
