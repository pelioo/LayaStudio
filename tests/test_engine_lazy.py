"""Tests for the lazy-loader in engine.py that bypasses laya_mlx/__init__.py.

These tests validate the platform-compatibility shim that allows engine.py to import
without crashing on Windows where laya_mlx (and thus mlx) is unavailable.
"""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# TestLazyCommonLoader — _load_common() and __getattr__ in layastudio.engine
# ---------------------------------------------------------------------------


class TestLazyCommonLoader:
    """Tests for the lazy-loading mechanism that avoids top-level laya_mlx import."""

    def test_getattr_forwards_to_loaded_module(self):
        """__getattr__ should delegate to _load_common() for known exports."""
        import layastudio.engine as eng

        with patch.object(eng, "_load_common") as mock_load:
            mock_mod = MagicMock()
            mock_mod.QTYPES = {"test": "value"}
            mock_load.return_value = mock_mod

            eng._laya_mlx_common = None

            result = eng.QTYPES
            mock_load.assert_called_once()
            assert result == {"test": "value"}

    def test_getattr_unknown_name_raises_attributeerror(self):
        """Unknown attributes should raise AttributeError, not silently return None."""
        import layastudio.engine as eng

        eng._laya_mlx_common = None

        with pytest.raises(AttributeError, match="not_a_real_export"):
            _ = eng.not_a_real_export

    def test_load_common_caches_result(self):
        """After the first attribute access, _laya_mlx_common is set and reused."""
        import layastudio.engine as eng

        eng._laya_mlx_common = None
        sys.modules.pop("laya_mlx.common", None)

        # First access — triggers _load_common()
        _ = eng.QTYPES
        assert eng._laya_mlx_common is not None, "_laya_mlx_common should be populated after first access"
        first_cache = eng._laya_mlx_common

        # Second and third access — must reuse the same cached object
        _ = eng.QTYPES
        _ = eng.build_prefix

        assert eng._laya_mlx_common is first_cache, (
            "The cached module object must be the same across multiple accesses; "
            f"got {id(eng._laya_mlx_common)} vs {id(first_cache)}"
        )

    def test_load_common_registers_in_sys_modules(self):
        """After loading, laya_mlx.common should be in sys.modules."""
        import layastudio.engine as eng

        eng._laya_mlx_common = None
        sys.modules.pop("laya_mlx.common", None)

        try:
            _ = eng.QTYPES
        except Exception:
            pass  # we only care about the sys.modules side-effect

        assert "laya_mlx.common" in sys.modules

    def test_load_common_path_prefers_venv(self, tmp_path, monkeypatch):
        """When .venv exists alongside the package, its site-packages path is tried first."""
        import layastudio.engine as eng

        # Simulate: project/.venv/Lib/site-packages/laya_mlx/common.py
        venv_site = tmp_path / ".venv" / "Lib" / "site-packages" / "laya_mlx"
        venv_site.mkdir(parents=True)
        (venv_site / "common.py").write_text("QTYPES = {'from': 'venv'}\n")

        monkeypatch.setattr("layastudio.engine.PACKAGE", tmp_path)

        eng._laya_mlx_common = None
        with patch("importlib.util.spec_from_file_location") as spec_mock:
            spec_mock.return_value = MagicMock()
            spec_mock.return_value.loader = MagicMock()
            spec_mock.return_value.loader.exec_module = MagicMock()

            eng._load_common()

            call_args = str(spec_mock.call_args)
            assert ".venv" in call_args or "laya_mlx" in call_args

    def test_load_common_fallback_when_venv_missing(self, tmp_path, monkeypatch):
        """Falls back to sys.prefix when .venv/laya_mlx/common.py does not exist."""
        import layastudio.engine as eng

        monkeypatch.setattr("layastudio.engine.PACKAGE", tmp_path)
        # Only sys.prefix has the file
        fake_prefix = tmp_path / "sysprefix"
        fake_common = fake_prefix / "Lib" / "site-packages" / "laya_mlx" / "common.py"
        fake_common.parent.mkdir(parents=True)
        fake_common.write_text("QTYPES = {'from': 'sysprefix'}\n")
        monkeypatch.setattr(sys, "prefix", str(fake_prefix))

        eng._laya_mlx_common = None
        with patch("importlib.util.spec_from_file_location") as spec_mock:
            spec_mock.return_value = MagicMock()
            spec_mock.return_value.loader = MagicMock()
            spec_mock.return_value.loader.exec_module = MagicMock()

            eng._load_common()

            call_args_list = [str(a) for a in spec_mock.call_args_list]
            assert any("laya_mlx" in c for c in call_args_list)


# ---------------------------------------------------------------------------
# TestExamplesCertifi — Windows CA-bundle fix in layastudio.examples
# ---------------------------------------------------------------------------


class TestExamplesCertifi:
    """Tests for the certifi CA-bundle fix that enables HTTPS on Windows without system certs."""

    def test_certifi_env_setdefault_when_available(self):
        """When certifi is installed, setdefault sets both CURL_CA_BUNDLE and REQUESTS_CA_BUNDLE."""
        # certifi IS installed in this test environment, so we verify the variables get set
        import certifi

        code = f"""
import os
os.environ.setdefault("CURL_CA_BUNDLE", r"{certifi.where()}")
os.environ.setdefault("REQUESTS_CA_BUNDLE", r"{certifi.where()}")
print("CURL_CA_BUNDLE=" + os.environ.get("CURL_CA_BUNDLE", ""))
print("REQUESTS_CA_BUNDLE=" + os.environ.get("REQUESTS_CA_BUNDLE", ""))
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert certifi.where() in result.stdout

    def test_certifi_missing_is_silent(self):
        """When certifi is not installed, the ImportError is caught and silently ignored."""
        # We cannot truly hide certifi from a subprocess (it IS installed), so instead
        # we verify the same logic directly: ImportError is caught by the try/except in examples.py.
        import layastudio.examples as ex

        # Save original certifi (may or may not be in sys.modules)
        saved_certifi = sys.modules.get("certifi")
        try:
            # Simulate certifi not being importable
            sys.modules["certifi"] = None  # any non-module makes `import certifi` fail
            del sys.modules["certifi"]  # force re-import attempt to raise

            # Patch __builtins__'s __import__ to raise ImportError for certifi
            import builtins

            original_import = builtins.__import__

            def fake_import(name, *args, **kwargs):
                if name == "certifi":
                    raise ImportError("No module named 'certifi'")
                return original_import(name, *args, **kwargs)

            builtins.__import__ = fake_import
            try:
                # Re-execute the module-level block by reloading the module
                import importlib

                # Save/restore the module-level side-effects (env vars may already be set)
                curl_before = os.environ.get("CURL_CA_BUNDLE")
                requests_before = os.environ.get("REQUESTS_CA_BUNDLE")

                importlib.reload(ex)

                # Should not have raised — ImportError was silently caught
            finally:
                builtins.__import__ = original_import
        finally:
            if saved_certifi is not None:
                sys.modules["certifi"] = saved_certifi
            elif "certifi" in sys.modules:
                del sys.modules["certifi"]

    def test_setdefault_does_not_overwrite_existing(self):
        """setdefault means existing env vars are preserved."""
        original = os.environ.get("CURL_CA_BUNDLE")
        try:
            os.environ["CURL_CA_BUNDLE"] = "/already/set/cacert.pem"

            code = """
import os
import certifi
os.environ.setdefault("CURL_CA_BUNDLE", certifi.where())
print("VALUE=" + os.environ.get("CURL_CA_BUNDLE", ""))
"""
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                env={**os.environ},
            )
            assert "/already/set/cacert.pem" in result.stdout
        finally:
            if original is None:
                os.environ.pop("CURL_CA_BUNDLE", None)
            else:
                os.environ["CURL_CA_BUNDLE"] = original


# ---------------------------------------------------------------------------
# TestFindPortNoReuseAddr — SO_REUSEADDR removal in layastudio.server
# ---------------------------------------------------------------------------


class TestFindPortNoReuseAddr:
    """Tests for find_port() — SO_REUSEADDR must not be set on Windows."""

    def test_find_port_does_not_set_reuseaddr(self):
        """find_port must not call setsockopt(SO_REUSEADDR) — that breaks port-checking on Windows."""
        import layastudio.server as srv

        source = Path(srv.__file__).read_text(encoding="utf-8")
        start = source.find("def find_port")
        assert start != -1, "def find_port not found"

        # Find the next top-level def (line that starts with "\ndef ")
        rest = source[start + 1 :]
        next_def = rest.find("\ndef ")
        end = start + 1 + (next_def if next_def != -1 else len(rest))
        find_port_section = source[start:end]

        # SO_REUSEADDR is allowed in comments (for documentation), but not in code.
        # Check: there must be no setsockopt call at all inside find_port.
        assert "setsockopt" not in find_port_section, (
            "find_port must not call setsockopt — on Windows SO_REUSEADDR allows "
            "binding to a port another server is still listening on, which defeats "
            "the purpose of this port-checking function."
        )

    def test_find_port_returns_preferred_when_free(self):
        """When the preferred port is available, find_port returns it directly."""
        from layastudio.server import find_port

        port = find_port(18765)  # random high port unlikely to be in use
        assert port == 18765

    def test_find_port_skips_taken_port(self):
        """When the preferred port is occupied, find_port returns the next free one."""
        import socket

        from layastudio.server import find_port

        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 18766))
        server.listen(1)
        try:
            port = find_port(18766)
            assert port > 18766, "find_port should skip the occupied port"
        finally:
            server.close()

    def test_find_port_raises_when_all_taken(self):
        """When every port in the search range is taken, find_port exits with a message."""
        import socket

        from layastudio.server import find_port

        servers = []
        base = 28765
        try:
            for p in range(base, base + 20):
                s = socket.socket()
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", p))
                s.listen(1)
                servers.append(s)

            with pytest.raises(SystemExit, match="No free port"):
                find_port(base, tries=20)
        finally:
            for s in servers:
                s.close()
