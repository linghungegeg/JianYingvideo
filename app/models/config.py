from app.extensions import db

class Config(db.Model):
    __tablename__ = 'config'

    key = db.Column(db.String(255), primary_key=True)
    value = db.Column(db.Text)

    def __repr__(self):
        return f'<Config {self.key}>'