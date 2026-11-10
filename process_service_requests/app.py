"""
Run this feature on its own from the repo root: python -m process_service_requests.app
"""
from flask import Flask
from .help_page_bridge import HELP_PAGE_TEMPLATES_DIR
from boundaries import auth_bp, admin_bp  # the help page's login and admin pages, used unmodified
from .service_boundaries import service_request_bp

def create_app():
    # The help page's templates (base.html, login) are the app templates; this feature's own
    # templates are found through service_request_bp's template_folder.
    app = Flask(__name__, template_folder=HELP_PAGE_TEMPLATES_DIR)
    app.secret_key = "csit314_314_interior_design_help_key_2026"
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(service_request_bp)
    return app

if __name__ == "__main__":
    app = create_app()
    print("314 Interior Design Help - Service Requests Running on http://127.0.0.1:5002")
    print("Demo Interior Designer Login -> Email: designer@help314id.sg | Password: password123")
    print("Then open http://127.0.0.1:5002/designer/requests")
    app.run(debug=True, port=5002)
