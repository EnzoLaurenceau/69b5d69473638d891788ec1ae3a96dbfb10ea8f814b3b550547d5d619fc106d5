"""
stirling_pdf.py — Wrapper Stirling-PDF (github.com/Stirling-Tools/stirling-pdf)
================================================================================
PDF self-host : merge, split, OCR, sign, convert, compress, rotate…
Docker stateless MIT. Règle #5 : jamais coder la manip PDF à la main.

Usage :
    from tools.product_bricks.documents import stirling_pdf
    stirling_pdf.deploy(project_path)           # écrit docker-compose
    stirling_pdf.up(project_path)               # lance le service
    ok = stirling_pdf.status()                  # True si service répond
    out = stirling_pdf.merge(["a.pdf","b.pdf"]) # bytes du PDF fusionné
    out = stirling_pdf.split("doc.pdf", pages="1,3-5")
    out = stirling_pdf.ocr("scan.pdf", lang="fra")
    out = stirling_pdf.convert("doc.docx", to="pdf")
    out = stirling_pdf.compress("big.pdf", level=3)
"""

from __future__ import annotations
import os, subprocess, urllib.request
from pathlib import Path

DEFAULT_PORT = int(os.environ.get("STIRLING_PORT", 8080))
DEFAULT_HOST = os.environ.get("STIRLING_HOST", f"http://localhost:{DEFAULT_PORT}")
DOCKER_IMAGE = "frooodle/s-pdf:latest"

_COMPOSE = """\
services:
  stirling-pdf:
    image: {image}
    ports:
      - "{port}:8080"
    volumes:
      - ./trainingData:/usr/share/tessdata
      - ./logs:/logs
    environment:
      - LANGS=fra,eng
    restart: unless-stopped
"""


def deploy(project_path: str | Path) -> Path:
    """Écrit le docker-compose Stirling-PDF dans project_path/stirling_pdf/."""
    out_dir = Path(project_path) / "stirling_pdf"
    out_dir.mkdir(parents=True, exist_ok=True)
    cf = out_dir / "docker-compose.yml"
    cf.write_text(_COMPOSE.format(image=DOCKER_IMAGE, port=DEFAULT_PORT), encoding="utf-8")
    print(f"stirling_pdf: compose → {cf}")
    return cf


def up(project_path: str | Path) -> None:
    """docker compose up -d."""
    cf = Path(project_path) / "stirling_pdf" / "docker-compose.yml"
    if not cf.exists():
        deploy(project_path)
    subprocess.run(["docker", "compose", "-f", str(cf), "up", "-d"], check=True)
    print(f"stirling_pdf: UP → {DEFAULT_HOST}")


def status(host: str = DEFAULT_HOST) -> bool:
    """True si le service répond."""
    try:
        urllib.request.urlopen(f"{host}/api/v1/info", timeout=3)
        return True
    except Exception:
        try:
            urllib.request.urlopen(host, timeout=3)
            return True
        except Exception:
            return False


def _api_upload(endpoint: str, files: list[str | bytes], params: dict | None = None,
                host: str = DEFAULT_HOST) -> bytes:
    """POST multipart vers l'API Stirling-PDF, retourne les bytes du PDF résultat."""
    import urllib.parse, mimetypes, uuid, io
    boundary = uuid.uuid4().hex
    body = io.BytesIO()

    def _add_file(name: str, data: bytes, filename: str = "file.pdf") -> None:
        body.write(f'--{boundary}\r\n'.encode())
        body.write(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode())
        body.write(b'Content-Type: application/octet-stream\r\n\r\n')
        body.write(data)
        body.write(b'\r\n')

    for i, f in enumerate(files):
        data = Path(f).read_bytes() if isinstance(f, str) else f
        fname = Path(f).name if isinstance(f, str) else f"file{i}.pdf"
        _add_file(f"fileInput", data, fname)

    if params:
        for k, v in params.items():
            body.write(f'--{boundary}\r\n'.encode())
            body.write(f'Content-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())

    body.write(f'--{boundary}--\r\n'.encode())
    payload = body.getvalue()

    req = urllib.request.Request(
        f"{host}/api/v1/{endpoint}",
        data=payload,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def merge(pdf_paths: list[str], host: str = DEFAULT_HOST) -> bytes:
    """Fusionne plusieurs PDFs → bytes du résultat."""
    return _api_upload("merge-pdfs", pdf_paths, host=host)


def split(pdf_path: str, pages: str = "1", host: str = DEFAULT_HOST) -> bytes:
    """Extrait des pages (ex: '1,3-5') → bytes ZIP des pages extraites."""
    return _api_upload("split-pdf-by-sections", [pdf_path], {"pageNumbers": pages}, host=host)


def ocr(pdf_path: str, lang: str = "eng", host: str = DEFAULT_HOST) -> bytes:
    """OCR sur un PDF scanné → PDF interrogeable."""
    return _api_upload("add-ocr-pdf", [pdf_path], {"languages": lang}, host=host)


def convert(file_path: str, to: str = "pdf", host: str = DEFAULT_HOST) -> bytes:
    """Convertit un fichier (docx, pptx, html…) vers PDF ou inversement."""
    endpoint = "convert-to-pdf" if to == "pdf" else f"pdf-to-{to}"
    return _api_upload(endpoint, [file_path], host=host)


def compress(pdf_path: str, level: int = 3, host: str = DEFAULT_HOST) -> bytes:
    """Compresse un PDF (level 1-9). Level 3 = équilibre taille/qualité."""
    return _api_upload("compress-pdf", [pdf_path], {"optimizeLevel": str(level)}, host=host)


# ponytail: wrapper HTTP stateless. Pas de state côté Python — Stirling gère tout.
if __name__ == "__main__":
    up_status = status()
    print(f"stirling_pdf: service {'UP' if up_status else 'DOWN'} @ {DEFAULT_HOST}")
    print("ops: merge() split() ocr() convert() compress()")
    print(f"deploy: docker run -p {DEFAULT_PORT}:8080 {DOCKER_IMAGE}")
