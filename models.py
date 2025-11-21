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
    
class Translation(db.Model):
    __tablename__ = 'translation'
    
    id = db.Column(db.Integer, primary_key=True)
    # 원문 텍스트 (검색 속도를 위해 인덱스 설정, 유니크)
    original_text = db.Column(db.Text, unique=True, nullable=False, index=True)
    # 번역된 텍스트
    translated_text = db.Column(db.Text, nullable=False)
    # 언제 저장되었는지 (나중에 오래된 번역 갱신용)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Translation {self.original_text[:20]}...>'