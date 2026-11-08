import os, sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'change-this-secret-key')
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# Point this at the platform-management SQLite file to share projects and moderation data.
DATABASE = os.environ.get('PLATFORM_DATABASE', os.path.join(BASE_DIR, 'database.db'))
# Must match registered_users.user_id in the platform-management app.
DESIGNER_USER_ID = str(os.environ.get('DESIGNER_USER_ID', 'designer_demo'))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def get_db():
    db = sqlite3.connect(DATABASE, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def init_db():
    with get_db() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS categories (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
          description TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS projects (
          id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
          designer_id TEXT NOT NULL, category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
          status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published','hidden','removed')),
          featured INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
          restriction_version INTEGER NOT NULL DEFAULT 0, tags TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS photos (
          id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          filename TEXT NOT NULL, photo_type TEXT NOT NULL DEFAULT 'After', position INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS company (
          id INTEGER PRIMARY KEY AUTOINCREMENT, designer_id TEXT NOT NULL UNIQUE,
          name TEXT, description TEXT, email TEXT, phone TEXT, location TEXT
        );
        CREATE TABLE IF NOT EXISTS reviews (
          id INTEGER PRIMARY KEY AUTOINCREMENT, designer_id TEXT NOT NULL,
          customer TEXT NOT NULL, review TEXT NOT NULL, reply TEXT DEFAULT ''
        );
        ''')
        # Additive upgrades for databases created by the earlier designer-only demo.
        cols = {r['name'] for r in db.execute('PRAGMA table_info(projects)')}
        if 'designer_id' not in cols:
            db.execute("ALTER TABLE projects ADD COLUMN designer_id TEXT NOT NULL DEFAULT 'designer_demo'")
            db.execute("UPDATE projects SET designer_id=? WHERE designer_id='designer_demo'", (DESIGNER_USER_ID,))
        if 'category_id' not in cols:
            db.execute('ALTER TABLE projects ADD COLUMN category_id INTEGER REFERENCES categories(id)')
            old_rows = db.execute('SELECT id, category FROM projects').fetchall() if 'category' in cols else []
            for r in old_rows:
                name = (r['category'] or 'Other').strip() or 'Other'
                db.execute('INSERT OR IGNORE INTO categories(name) VALUES(?)', (name,))
                cat_id = db.execute('SELECT id FROM categories WHERE name=? COLLATE NOCASE', (name,)).fetchone()['id']
                db.execute('UPDATE projects SET category_id=? WHERE id=?', (cat_id, r['id']))
        if 'featured' not in cols: db.execute('ALTER TABLE projects ADD COLUMN featured INTEGER NOT NULL DEFAULT 0')
        if 'restriction_version' not in cols: db.execute('ALTER TABLE projects ADD COLUMN restriction_version INTEGER NOT NULL DEFAULT 0')
        if 'tags' not in cols: db.execute("ALTER TABLE projects ADD COLUMN tags TEXT NOT NULL DEFAULT ''")
        company_cols = {r['name'] for r in db.execute('PRAGMA table_info(company)')}
        if 'designer_id' not in company_cols:
            # The original demo constrained company.id to 1; rebuild it for per-designer profiles.
            old_company = db.execute('SELECT * FROM company WHERE id=1').fetchone()
            db.execute('ALTER TABLE company RENAME TO company_legacy')
            db.execute('''CREATE TABLE company (id INTEGER PRIMARY KEY AUTOINCREMENT, designer_id TEXT NOT NULL UNIQUE,
                name TEXT, description TEXT, email TEXT, phone TEXT, location TEXT)''')
            if old_company:
                db.execute('''INSERT INTO company(designer_id,name,description,email,phone,location)
                    VALUES(?,?,?,?,?,?)''', (DESIGNER_USER_ID, old_company['name'], old_company['description'],
                    old_company['email'], old_company['phone'], old_company['location']))
            db.execute('DROP TABLE company_legacy')
        review_cols = {r['name'] for r in db.execute('PRAGMA table_info(reviews)')}
        if 'designer_id' not in review_cols:
            db.execute("ALTER TABLE reviews ADD COLUMN designer_id TEXT NOT NULL DEFAULT 'designer_demo'")
            db.execute("UPDATE reviews SET designer_id=? WHERE designer_id='designer_demo'", (DESIGNER_USER_ID,))
        # Convert legacy title-case status values to the platform-management vocabulary.
        db.execute("UPDATE projects SET status=lower(status) WHERE lower(status) IN ('draft','published','hidden','removed')")
        # Give legacy projects a category if needed.
        fallback = db.execute("SELECT id FROM categories WHERE name='Other' COLLATE NOCASE").fetchone()
        if not fallback:
            db.execute("INSERT OR IGNORE INTO categories(name) VALUES('Other')")
            fallback = db.execute("SELECT id FROM categories WHERE name='Other' COLLATE NOCASE").fetchone()
        db.execute('UPDATE projects SET category_id=? WHERE category_id IS NULL', (fallback['id'],))
        db.execute("INSERT OR IGNORE INTO company(designer_id,name,description,email,phone,location) VALUES(?,?,?,?,?,?)",
                   (DESIGNER_USER_ID, 'Your Interior Design Studio', 'We create thoughtful spaces for modern living.', 'hello@example.com', '+65 6000 0000', 'Singapore'))
        # Seed only this designer's workspace if it has no projects.
        if not db.execute('SELECT 1 FROM projects WHERE designer_id=? LIMIT 1', (DESIGNER_USER_ID,)).fetchone():
            db.execute("INSERT OR IGNORE INTO categories(name) VALUES('Residential')")
            cat = db.execute("SELECT id FROM categories WHERE name='Residential' COLLATE NOCASE").fetchone()['id']
            db.execute('INSERT INTO projects(title,description,designer_id,category_id,status,created_at,tags) VALUES(?,?,?,?,?,?,?)',
                       ('Modern HDB Living Room', 'A warm, modern living room with natural textures and clean lines.', DESIGNER_USER_ID, cat, 'published', datetime.now().strftime('%Y-%m-%d'), 'modern, hdb, living room'))
            db.execute('INSERT INTO reviews(designer_id,customer,review) VALUES(?,?,?)',
                       (DESIGNER_USER_ID, 'Alyssa', 'The team understood our needs and transformed our home beautifully.'))


def owner_project(project_id):
    with get_db() as db:
        row = db.execute('''SELECT p.*, c.name AS category FROM projects p
                            JOIN categories c ON c.id=p.category_id
                            WHERE p.id=? AND p.designer_id=?''', (project_id, DESIGNER_USER_ID)).fetchone()
    if row is None: abort(404)
    return row


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/')
def dashboard():
    with get_db() as db:
        projects = db.execute('''SELECT p.*,c.name AS category,COUNT(ph.id) AS photo_count
            FROM projects p JOIN categories c ON c.id=p.category_id LEFT JOIN photos ph ON ph.project_id=p.id
            WHERE p.designer_id=? GROUP BY p.id ORDER BY p.id DESC''', (DESIGNER_USER_ID,)).fetchall()
        counts = {
            'total': db.execute('SELECT COUNT(*) FROM projects WHERE designer_id=? AND status!=\'removed\'', (DESIGNER_USER_ID,)).fetchone()[0],
            'published': db.execute("SELECT COUNT(*) FROM projects WHERE designer_id=? AND status='published'", (DESIGNER_USER_ID,)).fetchone()[0],
            'drafts': db.execute("SELECT COUNT(*) FROM projects WHERE designer_id=? AND status='draft'", (DESIGNER_USER_ID,)).fetchone()[0],
            'hidden': db.execute("SELECT COUNT(*) FROM projects WHERE designer_id=? AND status='hidden'", (DESIGNER_USER_ID,)).fetchone()[0],
            'reviews': db.execute('SELECT COUNT(*) FROM reviews WHERE designer_id=?', (DESIGNER_USER_ID,)).fetchone()[0]
        }
    return render_template('dashboard.html', projects=projects, counts=counts)


@app.route('/projects/new', methods=['GET', 'POST'])
def create_project():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            flash('Please enter a project title.', 'error')
            return redirect(url_for('create_project'))
        status = 'published' if request.form.get('action') == 'publish' else 'draft'
        category = request.form.get('category', 'Other').strip() or 'Other'
        with get_db() as db:
            db.execute('INSERT OR IGNORE INTO categories(name) VALUES(?)', (category,))
            category_id = db.execute('SELECT id FROM categories WHERE name=? COLLATE NOCASE', (category,)).fetchone()['id']
            cur = db.execute('''INSERT INTO projects(title,description,designer_id,category_id,status,created_at,tags)
                VALUES(?,?,?,?,?,?,?)''', (title, request.form.get('description',''), DESIGNER_USER_ID, category_id,
                status, datetime.now().strftime('%Y-%m-%d'), request.form.get('tags','')))
            pid = cur.lastrowid
        flash('Project listing created.', 'success')
        return redirect(url_for('project_detail', project_id=pid))
    return render_template('project_form.html', project=None)


@app.route('/projects/<int:project_id>/edit', methods=['GET', 'POST'])
def edit_project(project_id):
    project = owner_project(project_id)
    if project['status'] in ('hidden', 'removed'):
        flash('This project is restricted by platform management and cannot be edited or republished here.', 'error')
        return redirect(url_for('project_detail', project_id=project_id))
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title: flash('Please enter a project title.', 'error'); return redirect(url_for('edit_project', project_id=project_id))
        status = 'published' if request.form.get('action') == 'publish' else 'draft'
        category = request.form.get('category', 'Other').strip() or 'Other'
        with get_db() as db:
            db.execute('INSERT OR IGNORE INTO categories(name) VALUES(?)', (category,))
            cat_id = db.execute('SELECT id FROM categories WHERE name=? COLLATE NOCASE', (category,)).fetchone()['id']
            db.execute('''UPDATE projects SET title=?,description=?,category_id=?,tags=?,status=?
                          WHERE id=? AND designer_id=? AND status IN ('draft','published')''',
                       (title, request.form.get('description',''), cat_id, request.form.get('tags',''), status, project_id, DESIGNER_USER_ID))
        flash('Project updated.', 'success')
        return redirect(url_for('project_detail', project_id=project_id))
    return render_template('project_form.html', project=project)


@app.route('/projects/<int:project_id>')
def project_detail(project_id):
    project = owner_project(project_id)
    with get_db() as db:
        photos = db.execute('SELECT * FROM photos WHERE project_id=? ORDER BY position,id', (project_id,)).fetchall()
    return render_template('project_detail.html', project=project, photos=photos)


@app.route('/projects/<int:project_id>/delete', methods=['POST'])
def delete_project(project_id):
    project = owner_project(project_id)
    if project['status'] in ('hidden', 'removed'):
        flash('Restricted projects cannot be deleted from the designer workspace.', 'error')
        return redirect(url_for('project_detail', project_id=project_id))
    with get_db() as db:
        photos = db.execute('SELECT filename FROM photos WHERE project_id=?', (project_id,)).fetchall()
        for photo in photos:
            path = os.path.join(UPLOAD_FOLDER, photo['filename'])
            if os.path.exists(path): os.remove(path)
        db.execute('DELETE FROM projects WHERE id=? AND designer_id=?', (project_id, DESIGNER_USER_ID))
    flash('Project deleted.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/projects/<int:project_id>/photos', methods=['GET', 'POST'])
def manage_photos(project_id):
    project = owner_project(project_id)
    if project['status'] in ('hidden', 'removed'): abort(403)
    if request.method == 'POST':
        with get_db() as db:
            pos = db.execute('SELECT COALESCE(MAX(position),-1)+1 FROM photos WHERE project_id=?', (project_id,)).fetchone()[0]
            for file in request.files.getlist('photos'):
                if file and file.filename and allowed_file(file.filename):
                    safe = secure_filename(file.filename)
                    unique = f"{project_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{safe}"
                    file.save(os.path.join(UPLOAD_FOLDER, unique))
                    db.execute('INSERT INTO photos(project_id,filename,photo_type,position) VALUES(?,?,?,?)',
                               (project_id, unique, request.form.get('photo_type','After'), pos)); pos += 1
        flash('Photos uploaded.', 'success'); return redirect(url_for('manage_photos', project_id=project_id))
    with get_db() as db: photos = db.execute('SELECT * FROM photos WHERE project_id=? ORDER BY position,id', (project_id,)).fetchall()
    return render_template('photos.html', project=project, photos=photos)


@app.route('/photos/<int:photo_id>/move/<direction>', methods=['POST'])
def move_photo(photo_id, direction):
    if direction not in ('up','down'): abort(400)
    with get_db() as db:
        photo = db.execute('''SELECT ph.* FROM photos ph JOIN projects p ON p.id=ph.project_id
                              WHERE ph.id=? AND p.designer_id=? AND p.status IN ('draft','published')''', (photo_id, DESIGNER_USER_ID)).fetchone()
        if not photo: abort(404)
        rows = db.execute('SELECT * FROM photos WHERE project_id=? ORDER BY position,id', (photo['project_id'],)).fetchall()
        ids = [r['id'] for r in rows]; idx = ids.index(photo_id); other = idx-1 if direction=='up' else idx+1
        if 0 <= other < len(ids):
            a,b=rows[idx],rows[other]
            db.execute('UPDATE photos SET position=? WHERE id=?',(b['position'],a['id']))
            db.execute('UPDATE photos SET position=? WHERE id=?',(a['position'],b['id']))
        pid=photo['project_id']
    return redirect(url_for('manage_photos', project_id=pid))


@app.route('/photos/<int:photo_id>/delete', methods=['POST'])
def delete_photo(photo_id):
    with get_db() as db:
        photo = db.execute('''SELECT ph.* FROM photos ph JOIN projects p ON p.id=ph.project_id
                              WHERE ph.id=? AND p.designer_id=? AND p.status IN ('draft','published')''', (photo_id, DESIGNER_USER_ID)).fetchone()
        if not photo: abort(404)
        pid=photo['project_id']; path=os.path.join(UPLOAD_FOLDER,photo['filename'])
        if os.path.exists(path): os.remove(path)
        db.execute('DELETE FROM photos WHERE id=?',(photo_id,))
    flash('Photo deleted.','success'); return redirect(url_for('manage_photos',project_id=pid))


@app.route('/company', methods=['GET','POST'])
def company_profile():
    if request.method=='POST':
        with get_db() as db:
            db.execute('''UPDATE company SET name=?,description=?,email=?,phone=?,location=? WHERE designer_id=?''',
                (request.form.get('name',''),request.form.get('description',''),request.form.get('email',''),
                 request.form.get('phone',''),request.form.get('location',''),DESIGNER_USER_ID))
        flash('Company profile saved.','success'); return redirect(url_for('company_profile'))
    with get_db() as db: company=db.execute('SELECT * FROM company WHERE designer_id=?',(DESIGNER_USER_ID,)).fetchone()
    return render_template('company.html',company=company)


@app.route('/reviews')
def reviews():
    with get_db() as db: items=db.execute('SELECT * FROM reviews WHERE designer_id=? ORDER BY id DESC',(DESIGNER_USER_ID,)).fetchall()
    return render_template('reviews.html',reviews=items)


@app.route('/reviews/<int:review_id>/reply',methods=['POST'])
def reply_review(review_id):
    with get_db() as db:
        if not db.execute('SELECT 1 FROM reviews WHERE id=? AND designer_id=?',(review_id,DESIGNER_USER_ID)).fetchone(): abort(404)
        db.execute('UPDATE reviews SET reply=? WHERE id=? AND designer_id=?',(request.form.get('reply','').strip(),review_id,DESIGNER_USER_ID))
    flash('Your reply has been saved.','success'); return redirect(url_for('reviews'))


if __name__=='__main__':
    init_db()
    app.run(debug=True)
