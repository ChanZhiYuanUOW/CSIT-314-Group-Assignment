from pathlib import Path
import os
from platform_management.entities import PlatformData, utc_now
from contextlib import ExitStack
from uuid import uuid4
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename
from platform_management.access import current_manager
from platform_management.db import get_db
from platform_management.project_cost import parse_amount

bp = Blueprint('designer', __name__, template_folder='templates', static_folder='static')
UPLOAD_FOLDER = Path(__file__).parent / 'static' / 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

@bp.before_request
def require_designer():
    if request.endpoint == 'designer.static':
        asset = request.view_args['filename']
        if asset.startswith('uploads/'):
            db = get_db()
            photo = db.first('photos', filename=asset.removeprefix('uploads/'))
            project = db.first('projects', id=photo['project_id']) if photo else None
            if project is None:
                abort(404)
            if project['status'] == 'published':
                return
            owner = current_manager()
            if not owner or owner['role'] != 'Interior Designer' or str(owner['user_id']) != project['designer_id']:
                abort(404)
            return

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
    return {'category_names': [r['name'] for r in PlatformData.listCategories()]}

def owner_project(project_id):
    row = PlatformData.getProject(project_id)
    if row and row['designer_id'] != g.designer_id:
        abort(404)
    if row is None: abort(404)
    return row


def category_id(name):
    for row in get_db().all('categories'):
        if row['name'].casefold() == name.casefold():
            return row['id']
    abort(400, 'Select an existing project category.')


def project_photos(project_id):
    return sorted(get_db().all('photos', project_id=project_id), key=lambda p:(p['position'],p['id']))


def editable_photo(db, photo_id):
    photo = db.first('photos', id=photo_id)
    if not photo:
        abort(404)
    project = owner_project(photo['project_id'])
    if project['status'] not in ('draft','published'):
        abort(404)
    return photo


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_gallery_files(db, project_id, files, cleanup):
    position = max((p['position'] for p in project_photos(project_id)), default=-1) + 1
    for upload, photo_type in files:
        filename = f"{project_id}_{uuid4().hex}_{secure_filename(upload.filename)}"
        path = UPLOAD_FOLDER / filename
        UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
        cleanup.callback(path.unlink, missing_ok=True)
        upload.save(path)
        db.add('photos', project_id=project_id, filename=filename,
               photo_type=photo_type, position=position)
        position += 1


@bp.route('/')
def dashboard():
    db = get_db()
    projects = [p for p in PlatformData.listProjects() if p['designer_id'] == g.designer_id]
    projects.sort(key=lambda p:-p['id'])
    for p in projects:
        p['photo_count'] = len(project_photos(p['id']))
    counts = {'total':sum(p['status']!='removed' for p in projects),
              'reviews':len(db.all('reviews',designer_id=g.designer_id))}
    for label,status in [('published','published'),('drafts','draft'),('hidden','hidden')]:
        counts[label] = sum(p['status']==status for p in projects)
    return render_template('designer/dashboard.html', projects=projects, counts=counts)


@bp.route('/projects/new', methods=['GET', 'POST'])
def create_project():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            flash('Please enter a project title.', 'error')
            return redirect(url_for('designer.create_project'))
        try:
            amount = parse_amount(request.form.get('estimated_cost_sgd'))
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template('designer/project_form.html', project=None), 400
        estimate = format(amount, '.2f') if amount is not None else ''
        status = 'published' if request.form.get('action') == 'publish' else 'draft'
        category = request.form.get('category', 'Other').strip() or 'Other'
        files = [(upload, kind) for field, kind in
                 [('before_photos', 'Before'), ('after_photos', 'After')]
                 for upload in request.files.getlist(field) if upload.filename]
        if any(not allowed_file(upload.filename) for upload, _ in files):
            flash('Choose JPG, PNG, GIF or WebP images and select your photos again.', 'error')
            return render_template('designer/project_form.html', project=None), 400
        with ExitStack() as cleanup:
            with get_db() as db:
                project = db.add('projects', title=title, description=request.form.get('description', ''),
                                 designer_id=g.designer_id, category_id=category_id(category),
                                 estimated_cost_sgd=estimate, status=status, created_at=utc_now(), tags=request.form.get('tags', ''))
                pid = project['id']
                save_gallery_files(db, pid, files, cleanup)
            cleanup.pop_all()
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
        try:
            amount = parse_amount(request.form.get('estimated_cost_sgd', project['estimated_cost_sgd']))
        except ValueError as exc:
            flash(str(exc), 'error')
            return render_template('designer/project_form.html', project=project), 400
        estimate = format(amount, '.2f') if amount is not None else ''
        status = 'published' if request.form.get('action') == 'publish' else 'draft'
        category = request.form.get('category', 'Other').strip() or 'Other'
        with get_db() as db:
            db.update('projects', db.first('projects', id=project_id), title=title,
                      description=request.form.get('description',''), category_id=category_id(category),
                      estimated_cost_sgd=estimate, tags=request.form.get('tags',''), status=status, featured=project['featured'] if status=='published' else 0)
        flash('Project updated.', 'success')
        return redirect(url_for('designer.project_detail', project_id=project_id))
    return render_template('designer/project_form.html', project=project)


@bp.route('/projects/<int:project_id>')
def project_detail(project_id):
    project = owner_project(project_id)
    with get_db() as db:
        photos = project_photos(project_id)
    return render_template('designer/project_detail.html', project=project, photos=photos)


@bp.route('/projects/<int:project_id>/delete', methods=['POST'])
def delete_project(project_id):
    project = owner_project(project_id)
    if project['status'] in ('hidden', 'removed'):
        flash('Restricted projects cannot be deleted from the designer workspace.', 'error')
        return redirect(url_for('designer.project_detail', project_id=project_id))
    with get_db() as db:
        photos = project_photos(project_id)
        if any(db.first(table, project_id=project_id) for table in
               ('content_reports','engagement_events','moderation_cases','feature_schedules')):
            flash('This project has platform activity and must be retained.', 'error')
            return redirect(url_for('designer.project_detail', project_id=project_id))
        for photo in photos:
            db.remove('photos', photo)
        db.remove('projects', db.first('projects', id=project_id))
    for photo in photos:
        (UPLOAD_FOLDER / photo['filename']).unlink(missing_ok=True)
    flash('Project deleted.', 'success')
    return redirect(url_for('designer.dashboard'))


@bp.route('/projects/<int:project_id>/photos', methods=['GET', 'POST'])
def manage_photos(project_id):
    project = owner_project(project_id)
    if project['status'] in ('hidden', 'removed'): abort(403)
    if request.method == 'POST':
        files = [(upload, request.form.get('photo_type', 'After'))
                 for upload in request.files.getlist('photos')
                 if upload.filename and allowed_file(upload.filename)]
        with ExitStack() as cleanup:
            with get_db() as db:
                save_gallery_files(db, project_id, files, cleanup)
            cleanup.pop_all()
        flash('Photos uploaded.', 'success'); return redirect(url_for('designer.manage_photos', project_id=project_id))
    with get_db() as db: photos = project_photos(project_id)
    return render_template('designer/photos.html', project=project, photos=photos)


@bp.route('/photos/<int:photo_id>/move/<direction>', methods=['POST'])
def move_photo(photo_id, direction):
    if direction not in ('up','down'): abort(400)
    with get_db() as db:
        photo = editable_photo(db, photo_id)
        if not photo: abort(404)
        rows = project_photos(photo['project_id'])
        ids = [r['id'] for r in rows]; idx = ids.index(photo_id); other = idx-1 if direction=='up' else idx+1
        if 0 <= other < len(ids):
            a,b=rows[idx],rows[other]
            original_position = a['position']
            db.update('photos', db.first('photos', id=a['id']), position=b['position'])
            db.update('photos', db.first('photos', id=b['id']), position=original_position)
        pid=photo['project_id']
    return redirect(url_for('designer.manage_photos', project_id=pid))


@bp.route('/photos/<int:photo_id>/delete', methods=['POST'])
def delete_photo(photo_id):
    with get_db() as db:
        photo = editable_photo(db, photo_id)
        if not photo: abort(404)
        pid=photo['project_id']; path=os.path.join(UPLOAD_FOLDER,photo['filename'])
        db.remove('photos',photo)
    Path(path).unlink(missing_ok=True)
    flash('Photo deleted.','success'); return redirect(url_for('designer.manage_photos',project_id=pid))


@bp.route('/company', methods=['GET','POST'])
def company_profile():
    with get_db() as db:
        company = db.first('company', designer_id=g.designer_id)
        if company is None:
            company = db.add('company', designer_id=g.designer_id)
        if request.method=='POST':
            db.update('company', company, **{key:request.form.get(key,'') for key in
                                            ('name','description','email','phone','location')})
    if request.method == 'POST':
        flash('Company profile saved.','success')
        return redirect(url_for('designer.company_profile'))
    return render_template('designer/company.html',company=company)


@bp.route('/reviews')
def reviews():
    items = sorted(get_db().all('reviews', designer_id=g.designer_id), key=lambda r:-r['id'])
    return render_template('designer/reviews.html',reviews=items)


@bp.route('/reviews/<int:review_id>/reply',methods=['POST'])
def reply_review(review_id):
    with get_db() as db:
        review = db.first('reviews', id=review_id, designer_id=g.designer_id)
        if not review:
            abort(404)
        db.update('reviews', review, reply=request.form.get('reply','').strip())
    flash('Your reply has been saved.','success'); return redirect(url_for('designer.reviews'))


