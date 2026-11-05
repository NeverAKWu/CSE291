"""Install the pinned official Linux x86_64 Tectonic release into a user cache.

The archive is verified against the SHA-256 published by GitHub's release API.
Other platforms can install Tectonic using the official instructions in report/README.md.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import platform
import subprocess
import tarfile
import urllib.request

VERSION = "0.17.0"
URL = (
    "https://github.com/tectonic-typesetting/tectonic/releases/download/"
    "tectonic%400.17.0/tectonic-0.17.0-x86_64-unknown-linux-musl.tar.gz"
)
SHA256 = "8533d07f9ccbd7a65824b9e0459041bca34af1eb33daba48f59215593753a3b7"


def main():
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"):
        raise SystemExit("Use the official platform installer linked in report/README.md")
    target = Path.home() / ".cache/cse291-tools/tectonic" / VERSION / "tectonic"
    if target.exists():
        version = subprocess.run([str(target), "--version"], check=True,
                                 capture_output=True, text=True).stdout.strip()
        if version != "Tectonic " + VERSION:
            raise SystemExit("Cached executable has a different version; refusing to overwrite")
        print(target)
        return
    request = urllib.request.Request(URL, headers={"User-Agent": "CSE291-report-build"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise SystemExit("Release checksum mismatch; nothing installed")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = [member for member in archive.getmembers()
                   if Path(member.name).name == "tectonic" and member.isfile()]
        if len(members) != 1:
            raise SystemExit("Unexpected release archive layout")
        executable = archive.extractfile(members[0]).read()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(executable)
    target.chmod(0o755)
    subprocess.run([str(target), "--version"], check=True)
    print(target)


if __name__ == "__main__":
    main()
