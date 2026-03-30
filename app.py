from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from config import Config
from models import db

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)
    db.init_app(app)
    JWTManager(app)

    from routes.auth import auth_bp
    from routes.contacts import contacts_bp
    from routes.groups import groups_bp
    from routes.templates import templates_bp
    from routes.email import email_bp
    from routes.workflow import workflow_bp

    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(contacts_bp, url_prefix='/api/contacts')
    app.register_blueprint(groups_bp, url_prefix='/api/groups')
    app.register_blueprint(templates_bp, url_prefix='/api/templates')
    app.register_blueprint(email_bp, url_prefix='/api/email')
    app.register_blueprint(workflow_bp, url_prefix='/api/workflow')

    with app.app_context():
        db.create_all()

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, port=8080)
