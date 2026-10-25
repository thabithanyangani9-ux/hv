
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import (
    Flask, render_template, render_template_string,
    request, redirect, url_for, flash
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user,
    login_required, logout_user, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)

# Set these environment variables in Render.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-for-local-testing")

database_url = os.environ.get("DATABASE_URL", "sqlite:///schoolhub.db")

# Render PostgreSQL URLs sometimes use postgres://.
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


# -------------------- DATABASE MODELS --------------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default="teacher")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Record(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    department = db.Column(db.String(40), nullable=False)
    record_type = db.Column(db.String(40), nullable=False)
    details = db.Column(db.Text, nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=True)
    currency = db.Column(db.String(10), nullable=True)
    created_by = db.Column(db.String(80), nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow
    )


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# -------------------- DEPARTMENT ACCESS --------------------

DEPARTMENTS = {
    "reception": {
        "title": "School Reception",
        "role": "receptionist",
        "types": ["Fee record", "Visitor", "School event", "Other"],
    },
    "teachers": {
        "title": "Teacher Department",
        "role": "teacher",
        "types": ["Learner information", "Teacher information", "Attendance", "Absence"],
    },
    "heads": {
        "title": "Heads Department",
        "role": "head",
        "types": ["General report", "Announcement", "Other"],
    },
    "finance": {
        "title": "Finance Department",
        "role": "finance",
        "types": ["School expense", "Payment", "Budget"],
    },
    "elab": {
        "title": "E-Lab",
        "role": "elab",
        "types": ["Book resource", "Learning resource", "Other"],
    },
}


def can_access(department):
    return current_user.role in (
        "admin", "head"
    ) or current_user.role == DEPARTMENTS[department]["role"]


# -------------------- LOGIN --------------------

@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("dashboard"))

        error = "Incorrect username or password."

    return render_template("login.html", error=error)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# -------------------- DASHBOARD --------------------

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")


# -------------------- DEPARTMENT PAGES --------------------

DEPARTMENT_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ department.title }} - SchoolHub</title>
    <link rel="stylesheet"
          href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
<main class="container">
    <p><a href="{{ url_for('dashboard') }}">← Dashboard</a></p>
    <h1>{{ department.title }}</h1>
    <p>Signed in as {{ current_user.username }} ({{ current_user.role }})</p>

    {% with messages = get_flashed_messages() %}
      {% for message in messages %}
        <p>{{ message }}</p>
      {% endfor %}
    {% endwith %}

    {% if can_write %}
    <h2>Add a record</h2>
    <form method="POST">
        <label for="record_type">Record type</label>
        <select name="record_type" id="record_type" required>
          {% for item in department.types %}
            <option value="{{ item }}">{{ item }}</option>
          {% endfor %}
        </select>

        <label for="details">Details</label>
        <textarea name="details" id="details" rows="4"
                  required maxlength="5000"></textarea>

        {% if department.role == "finance" or department.role == "receptionist" %}
        <label for="amount">Amount (optional)</label>
        <input name="amount" id="amount" type="number"
               min="0" step="0.01">

        <label for="currency">Currency</label>
        <select name="currency" id="currency">
            <option value="USD">USD</option>
            <option value="ZWG">ZWG</option>
        </select>
        {% endif %}

        <button type="submit">Save Record</button>
    </form>
    {% endif %}

    <h2>Records</h2>
    {% if records %}
      {% for record in records %}
        <section class="record">
          <strong>{{ record.record_type }}</strong>
          <p>{{ record.details }}</p>
          {% if record.amount is not none %}
            <p>Amount: {{ record.currency }} {{ "%.2f"|format(record.amount) }}</p>
          {% endif %}
          <small>
            Added by {{ record.created_by }} —
            {{ record.created_at.strftime("%Y-%m-%d %H:%M") }} UTC
          </small>
        </section>
      {% endfor %}
    {% else %}
      <p>No records have been added yet.</p>
    {% endif %}

    <p><a href="{{ url_for('logout') }}">Log out</a></p>
</main>
</body>
</html>
"""


def department_page(department_key):
    department = DEPARTMENTS[department_key]

    if not can_access(department_key):
        flash("You do not have permission to access that department.")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        record_type = request.form.get("record_type", "").strip()
        details = request.form.get("details", "").strip()

        if record_type not in department["types"]:
            flash("Please select a valid record type.")
            return redirect(request.path)

        if not details:
            flash("Please enter the record details.")
            return redirect(request.path)

        amount = None
        currency = None

        if department_key in ("finance", "reception"):
            raw_amount = request.form.get("amount", "").strip()
            currency = request.form.get("currency", "USD")

            if currency not in ("USD", "ZWG"):
                flash("Please select USD or ZWG.")
                return redirect(request.path)

            if raw_amount:
                try:
                    amount = Decimal(raw_amount)
                    if not amount.is_finite() or amount < 0:
                        raise InvalidOperation
                except InvalidOperation:
                    flash("Enter a valid non-negative amount.")
                    return redirect(request.path)

        record = Record(
            department=department_key,
            record_type=record_type,
            details=details,
            amount=amount,
            currency=currency,
            created_by=current_user.username,
        )

        db.session.add(record)
        db.session.commit()
        flash("Record saved successfully.")
        return redirect(request.path)

    # Heads and administrators can review records from all departments.
    if current_user.role in ("admin", "head"):
        records = Record.query.order_by(Record.created_at.desc()).limit(200).all()
    else:
        records = (
            Record.query.filter_by(department=department_key)
            .order_by(Record.created_at.desc())
            .limit(200)
            .all()
        )

    return render_template_string(
        DEPARTMENT_TEMPLATE,
        department=department,
        records=records,
        can_write=(
            current_user.role == "admin"
            or current_user.role == department["role"]
        ),
    )


@app.route("/reception", methods=["GET", "POST"])
@login_required
def reception():
    return department_page("reception")


@app.route("/teachers", methods=["GET", "POST"])
@login_required
def teachers():
    return department_page("teachers")


@app.route("/heads", methods=["GET", "POST"])
@login_required
def heads():
    return department_page("heads")


@app.route("/finance", methods=["GET", "POST"])
@login_required
def finance():
    return department_page("finance")


@app.route("/elab", methods=["GET", "POST"])
@login_required
def elab():
    return department_page("elab")


# -------------------- INITIAL ADMIN ACCOUNT --------------------

with app.app_context():
    db.create_all()

    # Create the first administrator only when Render environment variables
    # are set. Never hard-code a real password in this file.
    admin_username = os.environ.get("ADMIN_USERNAME")
    admin_password = os.environ.get("ADMIN_PASSWORD")

    if admin_username and admin_password:
        existing_admin = User.query.filter_by(
            username=admin_username
        ).first()

        if not existing_admin:
            admin = User(
                username=admin_username,
                role="admin",
            )
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
