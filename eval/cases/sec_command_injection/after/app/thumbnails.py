"""Thumbnail generation for uploaded images."""

import subprocess

from flask import Blueprint, request

bp = Blueprint("thumbnails", __name__)


@bp.post("/thumbnails")
def create_thumbnail():
    filename = request.form["filename"]
    subprocess.run(f"convert uploads/{filename} -resize 200x200 thumbs/{filename}", shell=True, check=True)
    return {"thumbnail": f"thumbs/{filename}"}
