import json
import tarfile
from pathlib import Path


def build(root):
    package = root / "unity/com.robotvoice.commands"
    manifest = json.loads((package / "package.json").read_text(encoding="utf-8"))
    files = [root / name for name in ("server.py", "pipeline.py", "pyproject.toml", "uv.lock")]
    model = root / "models/laya-commands"
    for file in [*files, model / "model.safetensors"]:
        if not file.is_file():
            raise FileNotFoundError(file)

    output = root / "dist" / f"{manifest['name']}-{manifest['version']}.tgz"
    output.parent.mkdir(exist_ok=True)
    temporary = output.with_suffix(".tgz.tmp")
    try:
        with tarfile.open(temporary, "w:gz") as archive:
            # AI 파일은 작업 폴더에 복사하지 않고 tarball에만 담는다 (모델 647MB)
            archive.add(package, arcname="package", filter=lambda info: None if "/AI~" in info.name else info)
            for file in files:
                archive.add(file, arcname=f"package/AI~/{file.name}")
            archive.add(model, arcname="package/AI~/models/laya-commands")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


if __name__ == "__main__":
    output = build(Path(__file__).resolve().parent)
    print(f"{output} ({output.stat().st_size:,} bytes)")
