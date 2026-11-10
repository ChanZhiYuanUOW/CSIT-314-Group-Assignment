"""
Single entry point for the whole site
Run from the repo root: python app.py
"""

import os

from flask import Flask

from boundaries import auth_bp, admin_bp
from manage_active_project.renovation_boundaries import renovation_bp
from set_consultation_availability.availability_boundaries import availability_bp
from process_service_requests.service_boundaries import service_request_bp
from engagement_analytics.analytics_boundaries import discovery_bp

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
# HELP_PAGE_DIR = os.path.join(REPO_DIR, "314_id_help_page")


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
