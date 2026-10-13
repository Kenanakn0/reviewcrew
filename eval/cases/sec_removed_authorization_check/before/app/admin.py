"""Admin endpoints."""

from flask import Blueprint, abort
from flask_login import current_user, login_required

from app.models import User, db

bp = Blueprint("admin", __name__)


@bp.delete("/admin/users/<int:user_id>")
@login_required
def delete_user(user_id: int):
    if not current_user.is_admin:
        abort(403)
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    return {"deleted": user_id}
