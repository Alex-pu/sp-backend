import os
from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from config import config
from models import db
from routes import api
from auth_routes import auth_bp
from shift_routes import shifts_bp
from transaction_routes import transactions_bp
from expense_routes import expenses_bp
from report_routes import reports_bp
from etims_routes import etims_bp
from shop_routes import shops_bp
from stock_routes import stock_bp
from sync_routes import sync_bp
from device_invite_routes import device_invites_bp
from payment_routes import payments_bp

migrate = Migrate()

def create_app(env='development'):
    """Create and configure Flask application"""
    app = Flask(__name__)

    # Load configuration
    app_config = config.get(env, config['default'])
    app_config.validate()
    app.config.from_object(app_config)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    JWTManager(app)

    # Enable CORS — allow Authorization header for JWT
    CORS(app, resources={
        r"/api/*": {
            "origins": app.config['CORS_ORIGINS'],
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
        }
    })

    # Register blueprints
    app.register_blueprint(api)
    app.register_blueprint(auth_bp)
    app.register_blueprint(shifts_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(expenses_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(etims_bp)
    app.register_blueprint(shops_bp)
    app.register_blueprint(stock_bp)
    app.register_blueprint(sync_bp)
    app.register_blueprint(device_invites_bp)
    app.register_blueprint(payments_bp)

    # Serve admin dashboard
    @app.route('/', methods=['GET'])
    def admin_dashboard():
        """Serve admin dashboard"""
        admin_file = os.path.join(os.path.dirname(__file__), 'admin.html')
        with open(admin_file, 'r', encoding='utf-8') as f:
            return f.read()

    return app

# Create app instance for Gunicorn/production
app = create_app(os.getenv('FLASK_ENV', 'development'))

if __name__ == '__main__':
    print("\n" + "="*50)
    print("SP Backend Server Starting...")
    print("="*50)
    print("\nAdmin Dashboard: http://localhost:5000")
    print("API Base: http://localhost:5000/api")
    print("\nAuth:")
    print("  GET  /api/auth/setup/status")
    print("  POST /api/auth/setup")
    print("  POST /api/auth/login")
    print("  GET  /api/auth/me")
    print("  GET  /api/auth/users")
    print("  POST /api/auth/users")
    print("\nProducts:")
    print("  GET  /api/products")
    print("  POST /api/products/upload")
    print("  GET  /api/categories")
    print("  GET  /api/stats")
    print("\nShops:")
    print("  GET  /api/shops")
    print("  POST /api/shops")
    print("  PUT  /api/shops/<id>")
    print("\nStock:")
    print("  GET  /api/stock/inventory")
    print("  POST /api/stock/receive")
    print("  POST /api/stock/adjust")
    print("  GET  /api/stock/movements")
    print("\nSync:")
    print("  GET  /api/sync/bootstrap")
    print("\nDevice pairing:")
    print("  POST /api/device-invites")
    print("  GET  /api/device-invites/<token>")
    print("  POST /api/device-invites/<token>/accept")
    print("\nShifts:")
    print("  POST /api/shifts")
    print("  GET  /api/shifts/current")
    print("  PUT  /api/shifts/<id>/close")
    print("  GET  /api/shifts/<id>/summary")
    print("\nTransactions:")
    print("  POST /api/transactions")
    print("  POST /api/transactions/batch")
    print("  GET  /api/transactions")
    print("\nExpenses:")
    print("  POST /api/expenses")
    print("  GET  /api/expenses")
    print("  PUT  /api/expenses/<id>/approve")
    print("  PUT  /api/expenses/<id>/reject")
    print("\nReports:")
    print("  GET  /api/reports/daily")
    print("  GET  /api/reports/range")
    print("  GET  /api/reports/cashier/<id>")
    print("\neTIMS / KRA:")
    print("  GET  /api/owner/etims/settings")
    print("  POST /api/owner/etims/settings")
    print("  POST /api/owner/etims/devices/register")
    print("  POST /api/etims/invoices/submit")
    print("  GET  /api/owner/etims/invoices")
    print("  POST /api/owner/etims/invoices/retry")
    print("\nPress Ctrl+C to stop the server\n")

    app.run(
        host='0.0.0.0',  # Listen on all interfaces
        port=5000,
        debug=True
    )
