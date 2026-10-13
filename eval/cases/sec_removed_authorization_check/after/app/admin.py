"""Admin endpoints."""

from flask import Blueprint
from flask_login import login_required

from app.models import User, db

bp = Blueprint("admin", __name__)


@bp.delete("/admin/users/<int:user_id>")
@login_required
def delete_user(user_id: int):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    return {"deleted": user_id}
