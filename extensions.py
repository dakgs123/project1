# extensions.py
from flask_sqlalchemy import SQLAlchemy
from flask_caching import Cache

# 앱과 연결되지 않은 상태로 객체만 먼저 생성
db = SQLAlchemy()
cache = Cache()