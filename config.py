import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


def _csv_env(name, default=''):
    value = os.environ.get(name, default)
    return [item.strip() for item in value.split(',') if item.strip()]


class Config:
    """Flask configuration."""

    _db_url = os.environ.get('DATABASE_URL', 'sqlite:///sp_products.db')
    if _db_url.startswith('postgres://'):
        _db_url = _db_url.replace('postgres://', 'postgresql+psycopg://', 1)
    elif _db_url.startswith('postgresql://'):
        _db_url = _db_url.replace('postgresql://', 'postgresql+psycopg://', 1)

    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True}

    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'dev-jwt-secret-change-in-production')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=12)

    CORS_ORIGINS = _csv_env('CORS_ORIGINS', '*')

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    @classmethod
    def validate(cls):
        return None


class DevelopmentConfig(Config):
    """Development configuration."""

    DEBUG = True


class ProductionConfig(Config):
    """Production configuration."""

    DEBUG = False
    CORS_ORIGINS = _csv_env('CORS_ORIGINS')

    @classmethod
    def validate(cls):
        missing = []
        if not os.environ.get('SECRET_KEY'):
            missing.append('SECRET_KEY')
        if not os.environ.get('JWT_SECRET_KEY'):
            missing.append('JWT_SECRET_KEY')
        if not os.environ.get('DATABASE_URL'):
            missing.append('DATABASE_URL')
        if not cls.CORS_ORIGINS:
            missing.append('CORS_ORIGINS')

        if missing:
            raise RuntimeError(f"Missing required production env vars: {', '.join(missing)}")


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}
