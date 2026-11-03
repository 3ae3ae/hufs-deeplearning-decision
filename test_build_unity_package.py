import json
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory

from build_unity_package import build


with TemporaryDirectory() as temporary:
    root = Path(temporary)
    package = root / "unity/com.robotvoice.commands"
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"name": "com.robotvoice.commands", "version": "0.1.0"}))
    (package / "README.md").write_text("example")
    for name in ("server.py", "pipeline.py", "pyproject.toml", "uv.lock", "unrelated.txt"):
        (root / name).write_text(name)
    model = root / "models/laya-commands"
    (model / "tokenizer").mkdir(parents=True)
    (model / "model.safetensors").write_bytes(b"model")
    (model / "tokenizer/config.json").write_text("{}")
    output = build(root)
    with tarfile.open(output) as archive:
        names = set(archive.getnames())
        assert "package/package.json" in names and "package/README.md" in names
        assert "package/AI~/uv.lock" in names and "package/AI~/server.py" in names
        assert "package/AI~/models/laya-commands/tokenizer/config.json" in names
        assert all(name == "package" or name.startswith("package/") for name in names)
        assert not any("unrelated.txt" in name for name in names)
        assert archive.extractfile("package/AI~/models/laya-commands/model.safetensors").read() == b"model"
    (model / "model.safetensors").unlink()
    previous = output.read_bytes()
    try:
        build(root)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("missing model accepted")
    assert output.read_bytes() == previous

print("Unity package tests passed")
