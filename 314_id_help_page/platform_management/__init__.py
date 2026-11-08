"""Register alongside Zhiyuan's auth/admin blueprints. Never creates user accounts."""
from pathlib import Path
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()


def init_app(app):
    app.config.setdefault('PM_DATABASE', str(Path(app.instance_path) / 'platform_management.sqlite3'))
    # Protect this module only: Zhiyuan's original forms do not yet emit CSRF tokens.
    app.config.setdefault('WTF_CSRF_CHECK_DEFAULT', False)
    Path(app.config['PM_DATABASE']).parent.mkdir(parents=True, exist_ok=True)
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
