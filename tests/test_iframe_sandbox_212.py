"""Agent HTML / Plotly frames run in an opaque origin (gh #212).

``allow-scripts`` together with ``allow-same-origin`` lets a srcdoc frame share the
app's origin: its script could call the workspace REST API (past the #206 guard) and
reach the parent page. Every frame keeps ``allow-scripts`` only, like the Files viewer.
"""
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"


@pytest.mark.skipif(not SRC.is_dir(), reason="frontend sources not present")
def test_no_iframe_is_both_scripted_and_same_origin():
    sandboxes = []
    for f in SRC.rglob("*.tsx"):
        for m in re.finditer(r'sandbox=\{?["\']([^"\']*)["\']', f.read_text(encoding="utf-8")):
            sandboxes.append((f.name, m.group(1)))
    assert sandboxes, "expected sandboxed frames in the frontend"
    bad = [(name, s) for name, s in sandboxes if "allow-same-origin" in s.split() and "allow-scripts" in s.split()]
    assert bad == []
    names = {name for name, _ in sandboxes}
    assert {"CanvasItem.tsx", "ToolCallCard.tsx", "FileViewer.tsx"} <= names
