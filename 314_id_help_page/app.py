from flask import Flask
from boundaries import auth_bp, admin_bp

def create_app():
    app = Flask(__name__)
    app.secret_key = "csit314_314_interior_design_help_key_2026"
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)

    from platform_management import init_app
    init_app(app)

    from designer_portfolio.app import bp as designer_bp
    app.register_blueprint(designer_bp, url_prefix='/designer')

    from customer_features import init_app as init_customer_features
    init_customer_features(app)
    return app
    

if __name__ == "__main__":
    app = create_app()
    print("314 Interior Design Help Running on http://127.0.0.1:5000")
    print("Demo User Admin Login -> Email: admin@help314id.sg | Password: password123")
    app.run(debug=True, port=5000)
