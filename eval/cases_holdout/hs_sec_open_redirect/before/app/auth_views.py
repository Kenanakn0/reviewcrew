"""Login views."""

from flask import Blueprint, redirect, render_template, request, session, url_for

from app.users import check_credentials

bp = Blueprint("auth", __name__)


@bp.post("/login")
def login():
    user = check_credentials(request.form["username"], request.form["password"])
    if user is None:
        return render_template("login.html", error="Invalid credentials"), 401
    session["user_id"] = user.id
    return redirect(url_for("dashboard.index"))
