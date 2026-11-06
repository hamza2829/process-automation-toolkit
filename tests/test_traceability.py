import ast
from pathlib import Path
import re


def test_every_requirement_has_an_existing_automated_test():
    requirements = set(re.findall(r"\bR-\d{2}\b", Path("docs/requirements.md").read_text()))
    table = Path("docs/test-cases.md").read_text()
    assert requirements == {f"R-{index:02}" for index in range(1, 16)}
    assert requirements <= set(re.findall(r"\bR-\d{2}\b", table))
    names = {node.name for path in Path("tests").glob("test_*.py") for node in ast.walk(ast.parse(path.read_text())) if isinstance(node, ast.FunctionDef)}
    referenced = set(re.findall(r"`(test_[a-z0-9_]+)`", table))
    assert referenced and referenced <= names
    for requirement in requirements:
        row = next(line for line in table.splitlines() if f"| {requirement} |" in line)
        assert "`test_" in row
