"""
Single entry point for the whole site
Run from the repo root: python app.py
"""

import os
import sys

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
# HELP_PAGE_DIR = os.path.join(REPO_DIR, "314_id_help_page")

# hacky way to work around import issues
# since identifiers cannot start with digits
# when the folders dont start with digits we can remove this and import normally :]
FEATURE_DIRS = [
    "314_id_manage_active_project",
    "314_id_set_consultation_availability",
    "314_id_process_service_requests",
    "314_id_engagement_analytics",
]
for folder in [os.path.join(REPO_DIR, f) for f in FEATURE_DIRS]:
    if folder not in sys.path:
        sys.path.append(folder)

from flask import Flask

from boundaries import auth_bp, admin_bp
from renovation_boundaries import renovation_bp
from availability_boundaries import availability_bp
from service_boundaries import service_request_bp
from analytics_boundaries import discovery_bp


def create_app():
    app = Flask(__name__, template_folder=os.path.join(REPO_DIR, "templates"))
    app.secret_key = os.environ.get("SECRET_KEY", "csit314_314_interior_design_help_key_2026")
    app.config["PM_CSV_DIR"] = os.path.join(REPO_DIR, "data", "platform")

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)

    from platform_management import init_app
    init_app(app)

    from customer_features import init_app as init_customer_features
    init_customer_features(app)

    from designer_portfolio.app import bp as designer_bp
    app.register_blueprint(designer_bp, url_prefix="/designer")

    app.register_blueprint(renovation_bp)
    app.register_blueprint(availability_bp)
    app.register_blueprint(service_request_bp)
    app.register_blueprint(discovery_bp)
    return app


if __name__ == "__main__":
    app = create_app()
    print("314 Interior Design Running on http://127.0.0.1:5000")
    print("Demo Admin Login -> Email: admin@help314id.sg | Password: password123")
    print("Demo ID Login -> Email: designer@help314id.sg | Password: password123")
    print("Demo Customer Login -> Email: customer@help314id.sg | Password: 123456")
    print("Demo PM Login -> Email: pm@help314id.sg | Password: password123")
    app.run(debug=True, port=5000)
