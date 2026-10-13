"""Serve uploaded files."""

import os

from flask import Blueprint, send_file

UPLOAD_DIR = "/srv/app/uploads"
bp = Blueprint("files", __name__)


@bp.get("/files/<path:name>")
def download(name: str):
    return send_file(os.path.join(UPLOAD_DIR, name), as_attachment=True)
