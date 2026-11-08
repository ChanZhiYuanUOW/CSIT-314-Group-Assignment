from pathlib import Path
import os
import sqlite3
from datetime import datetime
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename
from platform_management.access import current_manager
from platform_management.db import get_db

bp = Blueprint('designer', __name__, template_folder='templates', static_folder='static')
UPLOAD_FOLDER = Path(__file__).parent / 'static' / 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

@bp.before_request
def require_designer():
    user = current_manager()
    if user is None:
        return redirect(url_for('auth.authenticateLogin'))
    if user['role'] != 'Interior Designer':
        abort(403)
    g.designer_id = str(user['user_id'])
    if request.method == 'POST':
        current_app.extensions['csrf'].protect()

@bp.context_processor
def available_categories():
    return {'category_names': [r['name'] for r in get_db().execute('SELECT name FROM categories ORDER BY name')]}

def owner_project(project_id):
    with get_db() as db:
        row = db.execute('''SELECT p.*, c.name AS category FROM projects p
                            JOIN categories c ON c.id=p.category_id
                            WHERE p.id=? AND p.designer_id=?''', (project_id, g.designer_id)).fetchone()
    if row is None: abort(404)
    return row


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@bp.route('/')
def dashboard():
    with get_db() as db:
        projects = db.execute('''SELECT p.*,c.name AS category,COUNT(ph.id) AS photo_count
            FROM projects p JOIN categories c ON c.id=p.category_id LEFT JOIN photos ph ON ph.project_id=p.id
            WHERE p.designer_id=? GROUP BY p.id ORDER BY p.id DESC''', (g.designer_id,)).fetchall()
        counts = {
            'total': db.execute('SELECT COUNT(*) FROM projects WHERE designer_id=? AND status!=\'removed\'', (g.designer_id,)).fetchone()[0],
            'published': db.execute("SELECT COUNT(*) FROM projects WHERE designer_id=? AND status='published'", (g.designer_id,)).fetchone()[0],
            'drafts': db.execute("SELECT COUNT(*) FROM projects WHERE designer_id=? AND status='draft'", (g.designer_id,)).fetchone()[0],
            'hidden': db.execute("SELECT COUNT(*) FROM projects WHERE designer_id=? AND status='hidden'", (g.designer_id,)).fetchone()[0],
            'reviews': db.execute('SELECT COUNT(*) FROM reviews WHERE designer_id=?', (g.designer_id,)).fetchone()[0]
        }
    return render_template('designer/dashboard.html', projects=projects, counts=counts)


@bp.route('/projects/new', methods=['GET', 'POST'])
def create_project():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            flash('Please enter a project title.', 'error')
            return redirect(url_for('designer.create_project'))
        status = 'published' if request.form.get('action') == 'publish' else 'draft'
        category = request.form.get('category', 'Other').strip() or 'Other'
        with get_db() as db:
            if not db.execute('SELECT 1 FROM categories WHERE name=? COLLATE NOCASE', (category,)).fetchone():
                abort(400, 'Select an existing project category.')
            category_id = db.execute('SELECT id FROM categories WHERE name=? COLLATE NOCASE', (category,)).fetchone()['id']
            cur = db.execute('''INSERT INTO projects(title,description,designer_id,category_id,status,created_at,tags)
                VALUES(?,?,?,?,?,?,?)''', (title, request.form.get('description',''), g.designer_id, category_id,
                status, datetime.now().strftime('%Y-%m-%d'), request.form.get('tags','')))
            pid = cur.lastrowid
        flash('Project listing created.', 'success')
        return redirect(url_for('designer.project_detail', project_id=pid))
    return render_template('designer/project_form.html', project=None)


@bp.route('/projects/<int:project_id>/edit', methods=['GET', 'POST'])
def edit_project(project_id):
    project = owner_project(project_id)
    if project['status'] in ('hidden', 'removed'):
        flash('This project is restricted by platform management and cannot be edited or republished here.', 'error')
        return redirect(url_for('designer.project_detail', project_id=project_id))
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title: flash('Please enter a project title.', 'error'); return redirect(url_for('designer.edit_project', project_id=project_id))
        status = 'published' if request.form.get('action') == 'publish' else 'draft'
        category = request.form.get('category', 'Other').strip() or 'Other'
        with get_db() as db:
            if not db.execute('SELECT 1 FROM categories WHERE name=? COLLATE NOCASE', (category,)).fetchone():
                abort(400, 'Select an existing project category.')
            cat_id = db.execute('SELECT id FROM categories WHERE name=? COLLATE NOCASE', (category,)).fetchone()['id']
            db.execute('''UPDATE projects SET title=?,description=?,category_id=?,tags=?,status=?
                          WHERE id=? AND designer_id=? AND status IN ('draft','published')''',
                       (title, request.form.get('description',''), cat_id, request.form.get('tags',''), status, project_id, g.designer_id))
        flash('Project updated.', 'success')
        return redirect(url_for('designer.project_detail', project_id=project_id))
    return render_template('designer/project_form.html', project=project)


@bp.route('/projects/<int:project_id>')
def project_detail(project_id):
    project = owner_project(project_id)
    with get_db() as db:
        photos = db.execute('SELECT * FROM photos WHERE project_id=? ORDER BY position,id', (project_id,)).fetchall()
    return render_template('designer/project_detail.html', project=project, photos=photos)


@bp.route('/projects/<int:project_id>/delete', methods=['POST'])
def delete_project(project_id):
    project = owner_project(project_id)
    if project['status'] in ('hidden', 'removed'):
        flash('Restricted projects cannot be deleted from the designer workspace.', 'error')
        return redirect(url_for('designer.project_detail', project_id=project_id))
    with get_db() as db:
        photos = db.execute('SELECT filename FROM photos WHERE project_id=?', (project_id,)).fetchall()
        try:
            deleted = db.execute("DELETE FROM projects WHERE id=? AND designer_id=? AND status IN ('draft','published')", (project_id, g.designer_id))
            if deleted.rowcount != 1:
                abort(409)
        except sqlite3.IntegrityError:
            flash('This project has platform activity and must be retained.', 'error')
            return redirect(url_for('designer.project_detail', project_id=project_id))
    for photo in photos:
        (UPLOAD_FOLDER / photo['filename']).unlink(missing_ok=True)
    flash('Project deleted.', 'success')
    return redirect(url_for('designer.dashboard'))


@bp.route('/projects/<int:project_id>/photos', methods=['GET', 'POST'])
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
                    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
                    file.save(os.path.join(UPLOAD_FOLDER, unique))
                    db.execute('INSERT INTO photos(project_id,filename,photo_type,position) VALUES(?,?,?,?)',
                               (project_id, unique, request.form.get('photo_type','After'), pos)); pos += 1
        flash('Photos uploaded.', 'success'); return redirect(url_for('designer.manage_photos', project_id=project_id))
    with get_db() as db: photos = db.execute('SELECT * FROM photos WHERE project_id=? ORDER BY position,id', (project_id,)).fetchall()
    return render_template('designer/photos.html', project=project, photos=photos)


@bp.route('/photos/<int:photo_id>/move/<direction>', methods=['POST'])
def move_photo(photo_id, direction):
    if direction not in ('up','down'): abort(400)
    with get_db() as db:
        photo = db.execute('''SELECT ph.* FROM photos ph JOIN projects p ON p.id=ph.project_id
                              WHERE ph.id=? AND p.designer_id=? AND p.status IN ('draft','published')''', (photo_id, g.designer_id)).fetchone()
        if not photo: abort(404)
        rows = db.execute('SELECT * FROM photos WHERE project_id=? ORDER BY position,id', (photo['project_id'],)).fetchall()
        ids = [r['id'] for r in rows]; idx = ids.index(photo_id); other = idx-1 if direction=='up' else idx+1
        if 0 <= other < len(ids):
            a,b=rows[idx],rows[other]
            db.execute('UPDATE photos SET position=? WHERE id=?',(b['position'],a['id']))
            db.execute('UPDATE photos SET position=? WHERE id=?',(a['position'],b['id']))
        pid=photo['project_id']
    return redirect(url_for('designer.manage_photos', project_id=pid))


@bp.route('/photos/<int:photo_id>/delete', methods=['POST'])
def delete_photo(photo_id):
    with get_db() as db:
        photo = db.execute('''SELECT ph.* FROM photos ph JOIN projects p ON p.id=ph.project_id
                              WHERE ph.id=? AND p.designer_id=? AND p.status IN ('draft','published')''', (photo_id, g.designer_id)).fetchone()
        if not photo: abort(404)
        pid=photo['project_id']; path=os.path.join(UPLOAD_FOLDER,photo['filename'])
        if os.path.exists(path): os.remove(path)
        db.execute('DELETE FROM photos WHERE id=?',(photo_id,))
    flash('Photo deleted.','success'); return redirect(url_for('designer.manage_photos',project_id=pid))


@bp.route('/company', methods=['GET','POST'])
def company_profile():
    with get_db() as db:
        db.execute('INSERT OR IGNORE INTO company(designer_id) VALUES(?)', (g.designer_id,))
    if request.method=='POST':
        with get_db() as db:
            db.execute('''UPDATE company SET name=?,description=?,email=?,phone=?,location=? WHERE designer_id=?''',
                (request.form.get('name',''),request.form.get('description',''),request.form.get('email',''),
                 request.form.get('phone',''),request.form.get('location',''),g.designer_id))
        flash('Company profile saved.','success'); return redirect(url_for('designer.company_profile'))
    with get_db() as db: company=db.execute('SELECT * FROM company WHERE designer_id=?',(g.designer_id,)).fetchone()
    return render_template('designer/company.html',company=company)


@bp.route('/reviews')
def reviews():
    with get_db() as db: items=db.execute('SELECT * FROM reviews WHERE designer_id=? ORDER BY id DESC',(g.designer_id,)).fetchall()
    return render_template('designer/reviews.html',reviews=items)


@bp.route('/reviews/<int:review_id>/reply',methods=['POST'])
def reply_review(review_id):
    with get_db() as db:
        if not db.execute('SELECT 1 FROM reviews WHERE id=? AND designer_id=?',(review_id,g.designer_id)).fetchone(): abort(404)
        db.execute('UPDATE reviews SET reply=? WHERE id=? AND designer_id=?',(request.form.get('reply','').strip(),review_id,g.designer_id))
    flash('Your reply has been saved.','success'); return redirect(url_for('designer.reviews'))


