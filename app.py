# app.py
from flask import Flask
from dotenv import load_dotenv  
from config import Config
from extensions import db, cache
from models import Review, Translation
from routes.anime_routes import anime_bp

load_dotenv()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # 확장 기능 초기화 (Init)
    db.init_app(app)
    cache.init_app(app)

    # DB 테이블 생성
    with app.app_context():
        #db.drop_all()
        db.create_all()

    # 블루프린트(라우트) 등록
    app.register_blueprint(anime_bp)

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, port=5000)