import os


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'hard-to-guess-string-change-in-production'

    # MySQL
    SQLALCHEMY_DATABASE_URI = 'mysql+pymysql://root:4(LeClu#O-hd@localhost:3306/video_factory'
    # SQLite fallback
    # SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(os.path.abspath(os.path.dirname(__file__)), 'data-dev.sqlite')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload/log folders
    UPLOAD_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'app', 'uploads')
    LOG_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'logs')

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(LOG_FOLDER, exist_ok=True)

    # Redis
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'

    # Default free quota for new users
    DEFAULT_USER_QUOTA = int(os.environ.get('DEFAULT_USER_QUOTA', '5'))
