import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "change-this-secret-key"
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "database.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            category TEXT,
            tags TEXT,
            status TEXT NOT NULL DEFAULT 'Draft',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            photo_type TEXT NOT NULL DEFAULT 'After',
            position INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS company (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            name TEXT,
            description TEXT,
            email TEXT,
            phone TEXT,
            location TEXT
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer TEXT NOT NULL,
            review TEXT NOT NULL,
            reply TEXT DEFAULT ''
        );
        """)
        if not db.execute("SELECT id FROM company WHERE id=1").fetchone():
            db.execute(
                "INSERT INTO company (id, name, description, email, phone, location) VALUES (1,?,?,?,?,?)",
                ("Your Interior Design Studio", "We create thoughtful spaces for modern living.",
                 "hello@example.com", "+65 6000 0000", "Singapore")
            )
        if not db.execute("SELECT id FROM projects LIMIT 1").fetchone():
            db.execute(
                """INSERT INTO projects (title, description, category, tags, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("Modern HDB Living Room", "A warm, modern living room with natural textures and clean lines.",
                 "Residential", "modern, hdb, living room", "Published", datetime.now().strftime("%Y-%m-%d"))
            )
            db.execute(
                "INSERT INTO reviews (customer, review) VALUES (?,?)",
                ("Alyssa", "The team understood our needs and transformed our home beautifully.")
            )


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def project_or_404(project_id):
    with get_db() as db:
        project = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if project is None:
        abort(404)
    return project


@app.route("/")
def dashboard():
    with get_db() as db:
        projects = db.execute("""
            SELECT p.*, COUNT(ph.id) AS photo_count
            FROM projects p LEFT JOIN photos ph ON p.id=ph.project_id
            GROUP BY p.id ORDER BY p.id DESC
        """).fetchall()
        counts = {
            "total": db.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
            "published": db.execute("SELECT COUNT(*) FROM projects WHERE status='Published'").fetchone()[0],
            "drafts": db.execute("SELECT COUNT(*) FROM projects WHERE status='Draft'").fetchone()[0],
            "reviews": db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        }
    return render_template("dashboard.html", projects=projects, counts=counts)


@app.route("/projects/new", methods=["GET", "POST"])
def create_project():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("Please enter a project title.", "error")
            return render_template("project_form.html", project=None)
        status = "Published" if request.form.get("action") == "publish" else "Draft"
        with get_db() as db:
            cursor = db.execute("""
                INSERT INTO projects (title, description, category, tags, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (title, request.form.get("description", ""),
                  request.form.get("category", ""), request.form.get("tags", ""),
                  status, datetime.now().strftime("%Y-%m-%d")))
            project_id = cursor.lastrowid
        flash("Project listing created.", "success")
        return redirect(url_for("project_detail", project_id=project_id))
    return render_template("project_form.html", project=None)


@app.route("/projects/<int:project_id>/edit", methods=["GET", "POST"])
def edit_project(project_id):
    project = project_or_404(project_id)
    if request.method == "POST":
        status = "Published" if request.form.get("action") == "publish" else "Draft"
        with get_db() as db:
            db.execute("""
                UPDATE projects SET title=?, description=?, category=?, tags=?, status=?
                WHERE id=?
            """, (request.form.get("title", "").strip(), request.form.get("description", ""),
                  request.form.get("category", ""), request.form.get("tags", ""),
                  status, project_id))
        flash("Project updated.", "success")
        return redirect(url_for("project_detail", project_id=project_id))
    return render_template("project_form.html", project=project)


@app.route("/projects/<int:project_id>")
def project_detail(project_id):
    project = project_or_404(project_id)
    with get_db() as db:
        photos = db.execute(
            "SELECT * FROM photos WHERE project_id=? ORDER BY position, id", (project_id,)
        ).fetchall()
    return render_template("project_detail.html", project=project, photos=photos)


@app.route("/projects/<int:project_id>/delete", methods=["POST"])
def delete_project(project_id):
    project_or_404(project_id)
    with get_db() as db:
        photos = db.execute("SELECT filename FROM photos WHERE project_id=?", (project_id,)).fetchall()
        for photo in photos:
            path = os.path.join(UPLOAD_FOLDER, photo["filename"])
            if os.path.exists(path):
                os.remove(path)
        db.execute("DELETE FROM projects WHERE id=?", (project_id,))
    flash("Project deleted.", "success")
    return redirect(url_for("dashboard"))


@app.route("/projects/<int:project_id>/photos", methods=["GET", "POST"])
def manage_photos(project_id):
    project = project_or_404(project_id)
    if request.method == "POST":
        uploaded = request.files.getlist("photos")
        photo_type = request.form.get("photo_type", "After")
        with get_db() as db:
            next_position = db.execute(
                "SELECT COALESCE(MAX(position), -1)+1 FROM photos WHERE project_id=?", (project_id,)
            ).fetchone()[0]
            for file in uploaded:
                if file and file.filename and allowed_file(file.filename):
                    safe_name = secure_filename(file.filename)
                    unique_name = f"{project_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
                    file.save(os.path.join(UPLOAD_FOLDER, unique_name))
                    db.execute(
                        "INSERT INTO photos (project_id, filename, photo_type, position) VALUES (?,?,?,?)",
                        (project_id, unique_name, photo_type, next_position)
                    )
                    next_position += 1
        flash("Photos uploaded. You can change their order below.", "success")
        return redirect(url_for("manage_photos", project_id=project_id))
    with get_db() as db:
        photos = db.execute(
            "SELECT * FROM photos WHERE project_id=? ORDER BY position, id", (project_id,)
        ).fetchall()
    return render_template("photos.html", project=project, photos=photos)


@app.route("/photos/<int:photo_id>/move/<direction>", methods=["POST"])
def move_photo(photo_id, direction):
    if direction not in ("up", "down"):
        abort(400)
    with get_db() as db:
        photo = db.execute("SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()
        if not photo:
            abort(404)
        photos = db.execute(
            "SELECT * FROM photos WHERE project_id=? ORDER BY position, id", (photo["project_id"],)
        ).fetchall()
        ids = [p["id"] for p in photos]
        index = ids.index(photo_id)
        other_index = index - 1 if direction == "up" else index + 1
        if 0 <= other_index < len(ids):
            first, second = photos[index], photos[other_index]
            db.execute("UPDATE photos SET position=? WHERE id=?", (second["position"], first["id"]))
            db.execute("UPDATE photos SET position=? WHERE id=?", (first["position"], second["id"]))
        project_id = photo["project_id"]
    return redirect(url_for("manage_photos", project_id=project_id))


@app.route("/photos/<int:photo_id>/delete", methods=["POST"])
def delete_photo(photo_id):
    with get_db() as db:
        photo = db.execute("SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()
        if not photo:
            abort(404)
        project_id = photo["project_id"]
        path = os.path.join(UPLOAD_FOLDER, photo["filename"])
        if os.path.exists(path):
            os.remove(path)
        db.execute("DELETE FROM photos WHERE id=?", (photo_id,))
    flash("Photo deleted.", "success")
    return redirect(url_for("manage_photos", project_id=project_id))


@app.route("/company", methods=["GET", "POST"])
def company_profile():
    if request.method == "POST":
        with get_db() as db:
            db.execute("""
                UPDATE company SET name=?, description=?, email=?, phone=?, location=? WHERE id=1
            """, (request.form.get("name", ""), request.form.get("description", ""),
                  request.form.get("email", ""), request.form.get("phone", ""),
                  request.form.get("location", "")))
        flash("Company profile saved.", "success")
        return redirect(url_for("company_profile"))
    with get_db() as db:
        company = db.execute("SELECT * FROM company WHERE id=1").fetchone()
    return render_template("company.html", company=company)


@app.route("/reviews")
def reviews():
    with get_db() as db:
        items = db.execute("SELECT * FROM reviews ORDER BY id DESC").fetchall()
    return render_template("reviews.html", reviews=items)


@app.route("/reviews/<int:review_id>/reply", methods=["POST"])
def reply_review(review_id):
    with get_db() as db:
        review = db.execute("SELECT id FROM reviews WHERE id=?", (review_id,)).fetchone()
        if not review:
            abort(404)
        db.execute("UPDATE reviews SET reply=? WHERE id=?",
                   (request.form.get("reply", "").strip(), review_id))
    flash("Your reply has been saved.", "success")
    return redirect(url_for("reviews"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
