"""Register alongside Zhiyuan's auth/admin blueprints. Never creates user accounts."""
from pathlib import Path
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()


def init_app(app):
    app.config.setdefault('PM_CSV_DIR', str(Path(app.root_path) / 'data' / 'platform'))
    # Protect this module only: Zhiyuan's original forms do not yet emit CSRF tokens.
    app.config.setdefault('WTF_CSRF_CHECK_DEFAULT', False)
    if 'csrf' not in app.extensions:
        csrf.init_app(app)
    from . import db, cli
    from .boundaries import bp
    db.init_app(app)
    from . import workflow_boundaries  # register before attaching the blueprint
    app.register_blueprint(bp, url_prefix='/management')
    cli.init_app(app)
    from . import workflow_seed
    workflow_seed.init_app(app)
