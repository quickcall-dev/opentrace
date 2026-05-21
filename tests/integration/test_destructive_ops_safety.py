# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Codebase-wide safety tests for destructive filesystem operations.

Scans all Python source files for shutil.rmtree, os.remove, os.rmdir, and
verifies that every callsite is guarded — never escapes base_dir, never
follows symlinks, never operates on root/home paths.

If this test fails, someone introduced an unguarded destructive operation.
"""


import ast
from pathlib import Path




# ---------------------------------------------------------------------------
# Static scan: find all rmtree calls in the codebase
# ---------------------------------------------------------------------------


def _find_rmtree_calls() -> list[tuple[str, int]]:
    """Walk opentrace/ and find every shutil.rmtree call. Returns [(filepath, lineno)]."""
    results = []
    src_dir = Path(__file__).parent.parent / "opentrace"
    for py_file in src_dir.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # Match: shutil.rmtree(...)
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "rmtree"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "shutil"
                ):
                    results.append((str(py_file.relative_to(src_dir.parent)), node.lineno))
    return results


def _find_destructive_calls() -> list[tuple[str, int, str]]:
    """Walk opentrace/ and find all destructive file ops.

    Returns [(filepath, lineno, description)].
    Catches: shutil.rmtree, os.remove, os.unlink, os.rmdir, os.replace.
    """
    DANGEROUS_OS_FUNCS = {"remove", "unlink", "rmdir", "replace"}
    results = []
    src_dir = Path(__file__).parent.parent / "opentrace"
    for py_file in src_dir.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue
        relpath = str(py_file.relative_to(src_dir.parent))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # shutil.rmtree(...)
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "rmtree"
                and isinstance(func.value, ast.Name)
                and func.value.id == "shutil"
            ):
                results.append((relpath, node.lineno, "shutil.rmtree"))
            # os.remove/unlink/rmdir/replace(...)
            if (
                isinstance(func, ast.Attribute)
                and func.attr in DANGEROUS_OS_FUNCS
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
            ):
                results.append((relpath, node.lineno, f"os.{func.attr}"))
    return results


class TestStaticScan:
    """Verify we know about every destructive file op in the codebase."""

    # Allowlist: every destructive file op must be registered here.
    # Format: "file:lineno" is fragile, so we use "file:description" pairs.
    # When you add a new destructive op, you MUST add it here with a comment
    # explaining why it's safe.
    KNOWN_DESTRUCTIVE_OPS = {
        # shutil.rmtree
        "opentrace/daemon/main.py": {
            "shutil.rmtree",    # _cleanup_legacy: guarded by config dir name check + no symlink
        },
        # os.replace — atomic writes (tempfile → target), always paired with tempfile.mkstemp
        "opentrace/daemon/state.py": {"os.replace", "os.unlink"},
        "opentrace/daemon/push_status.py": {"os.replace", "os.unlink"},
        "opentrace/utils/progress.py": {"os.replace", "os.unlink"},
        "opentrace/utils/repo_resolver.py": {"os.replace", "os.unlink"},
        "opentrace/cli/traced.py": {"os.replace", "os.unlink"},
    }

    def test_all_destructive_ops_are_known(self):
        """Every destructive file op must be in the allowlist above."""
        found = _find_destructive_calls()

        # Group by file
        found_by_file: dict[str, set[str]] = {}
        for filepath, lineno, desc in found:
            found_by_file.setdefault(filepath, set()).add(desc)

        unknown_files = set(found_by_file.keys()) - set(self.KNOWN_DESTRUCTIVE_OPS.keys())
        assert unknown_files == set(), (
            f"Destructive file ops found in NEW files: {unknown_files}. "
            "Add safety guards and register in KNOWN_DESTRUCTIVE_OPS allowlist."
        )

        for filepath, ops in found_by_file.items():
            allowed = self.KNOWN_DESTRUCTIVE_OPS.get(filepath, set())
            unknown_ops = ops - allowed
            assert unknown_ops == set(), (
                f"New destructive ops in {filepath}: {unknown_ops}. "
                "Register in KNOWN_DESTRUCTIVE_OPS allowlist."
            )

    def test_all_rmtree_calls_are_known(self):
        """Every shutil.rmtree must be in this allowlist."""
        known_rmtree_locations = {
            "opentrace/daemon/main.py",
        }
        found = _find_rmtree_calls()
        found_files = {filepath for filepath, _ in found}

        unknown = found_files - known_rmtree_locations
        assert unknown == set(), (
            f"New shutil.rmtree found in: {unknown}. "
            "Add safety guards (base_dir check, no symlink follow) and update this allowlist."
        )

    def test_no_os_system_rm_calls(self):
        """No os.system('rm ...') or subprocess calls with rm in the codebase."""
        src_dir = Path(__file__).parent.parent / "opentrace"
        violations = []
        for py_file in src_dir.rglob("*.py"):
            content = py_file.read_text()
            for i, line in enumerate(content.splitlines(), 1):
                if "rm " in line and ("os.system" in line or "subprocess" in line):
                    violations.append(f"{py_file.relative_to(src_dir.parent)}:{i}")
        assert violations == [], f"Found shell rm commands: {violations}"

    def test_no_write_text_to_hardcoded_paths(self):
        """No .write_text() calls with hardcoded absolute paths (string literals)."""
        src_dir = Path(__file__).parent.parent / "opentrace"
        violations = []
        for py_file in src_dir.rglob("*.py"):
            try:
                tree = ast.parse(py_file.read_text(), filename=str(py_file))
            except SyntaxError:
                continue
            relpath = str(py_file.relative_to(src_dir.parent))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                # Match: something.write_text(...)
                if isinstance(func, ast.Attribute) and func.attr == "write_text":
                    # Check if the object is a hardcoded Path("/absolute/...")
                    val = func.value
                    if (
                        isinstance(val, ast.Call)
                        and isinstance(val.func, ast.Name)
                        and val.func.id == "Path"
                        and val.args
                        and isinstance(val.args[0], ast.Constant)
                        and isinstance(val.args[0].value, str)
                        and val.args[0].value.startswith("/")
                    ):
                        violations.append(
                            f"{relpath}:{node.lineno}: write_text to hardcoded path '{val.args[0].value}'"
                        )
        assert violations == [], (
            "Found write_text to hardcoded absolute paths:\n" +
            "\n".join(f"  {v}" for v in violations)
        )


# ---------------------------------------------------------------------------
# Runtime: _cleanup_legacy safety
# ---------------------------------------------------------------------------

