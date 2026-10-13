"""Create a new ARM64 Lambda ZIP under ignored data/, without deleting prior builds."""

import shutil
import subprocess
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(__file__).resolve().parents[2]
target = root / "data" / ("alexa-package-" + uuid4().hex[:8])
target.mkdir(parents=True)
subprocess.run(
    [
        "uv",
        "pip",
        "install",
        "--python-platform",
        "aarch64-manylinux2014",
        "--python-version",
        "3.12",
        "--only-binary",
        ":all:",
        "--target",
        str(target),
        "-r",
        str(Path(__file__).with_name("requirements.txt")),
    ],
    check=True,
)
shutil.copy2(Path(__file__).with_name("lambda_function.py"), target / "lambda_function.py")
output = target.with_suffix(".zip")
with ZipFile(output, "w", ZIP_DEFLATED) as archive:
    for path in target.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            archive.write(path, path.relative_to(target).as_posix())
print(output)
