import ast
from pathlib import Path


def test_domain_has_no_external_dependencies() -> None:
    """Verifies that src/vmc_twin/domain imports ONLY standard library modules."""
    domain_dir = Path(__file__).parent.parent.parent / "src" / "vmc_twin" / "domain"
    assert domain_dir.exists(), f"Domain dir {domain_dir} does not exist"

    allowed_stdlib_roots = {
        "__future__",
        "dataclasses",
        "enum",
        "typing",
        "collections",
        "math",
        "abc",
        "vmc_twin",  # local domain intra-imports
    }

    for py_file in domain_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        with open(py_file, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root in allowed_stdlib_roots, (
                        f"Domain file {py_file.name} imports forbidden root '{root}' (must be stdlib/pure)"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                assert root in allowed_stdlib_roots, (
                    f"Domain file {py_file.name} imports forbidden module '{root}'"
                )
