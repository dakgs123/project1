# config.py
import os

class Config:
    # 보안 키 등은 실제 배포 시 환경 변수로 관리하는 것이 좋습니다.
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev_secret_key'
    
    # DB 설정
    SQLALCHEMY_DATABASE_URI = 'sqlite:///reviews.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # 캐시 설정
    CACHE_TYPE = 'SimpleCache'
    CACHE_DEFAULT_TIMEOUT = 3600
    
    # Gemini API 키
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")