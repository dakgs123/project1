# models.py
from datetime import datetime
from extensions import db  # extensions에서 db 가져옴
import html

class Review(db.Model):
    __tablename__ = 'review'
    
    id = db.Column(db.Integer, primary_key=True)
    anime_id = db.Column(db.Integer, nullable=False, index=True)
    username = db.Column(db.String(80), nullable=False, default="익명")
    rating = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<Review {self.username} - {self.anime_id}>'