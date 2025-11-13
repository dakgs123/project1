# test.py (수정본)

from flask import Flask, request, jsonify, render_template
import httpx
import json
import os
import asyncio
from flask_caching import Cache
from datetime import datetime # [★추가]

from flask_sqlalchemy import SQLAlchemy


from google import genai
# [★추가★] API 버전을 지정하기 위해 types 모듈을 임포트합니다.
from google.genai import types
from google.genai.errors import APIError

# Flask 앱 및 캐시 초기화
app = Flask(__name__)
app.config['CACHE_TYPE'] = 'SimpleCache'
app.config['CACHE_DEFAULT_TIMEOUT'] = 3600

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///reviews.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

cache = Cache(app)

ANILIST_API_URL = 'https://graphql.anilist.co'

# --- [★코드 수정★] ---
# 'google-genai' (최신) 라이브러리에 맞는 클라이언트 초기화
try:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY 환경 변수가 설정되지 않았습니다.")
    
    # [수정] Client() 초기화 시 http_options를 통해 API 버전을 'v1'로 고정합니다.
    gemini_client = genai.Client(
        http_options=types.HttpOptions(api_version='v1')
    )
    print("Gemini 클라이언트 (google-genai, v1) 초기화 성공.")
except Exception as e:
    print(f"Gemini 클라이언트 초기화 실패: {e}")
    gemini_client = None
# -------------------------

# --- [★코드 수정★] ---
async def translate_title_to_korean_official(english_title):
    if not gemini_client or not english_title:
        return english_title
        
    cache_key = f"title_trans:{english_title}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return cached_result

    prompt = (
        f"당신은 일본 애니메이션의 **공식 한국어 제목 전문가**입니다. 다음 영어 제목을 한국에서 통용되는 공식적인 정발 제목(가장 흔하게 사용되는 한국어 제목)으로 번역해 주세요. "
        f"다음 지시 사항을 엄격하게 따르세요: "
        f"1. 번역 결과만 응답하고, 다른 설명이나 부연 설명은 일절 추가하지 마세요. "
        f"2. 만약 부제나 괄호 안의 내용이 한국에서 주로 사용되지 않는다면, **본편 제목만 남기고** 부제는 생략하는 것을 고려하세요. "
        f"3. 반드시 **한국어**로만 대답해야 합니다. "
        f"\n\n영어 제목: {english_title}"
    )
    
    try:
        # [수정] .aio 속성 사용 및 모델 이름 변경
        response = await gemini_client.aio.models.generate_content(
            model='gemini-2.5-flash', # <-- 1.5를 2.5로 변경
            contents=prompt
        )
        korean_title = response.text.strip().replace('"', '')
        final_title = korean_title if korean_title else english_title
        
        cache.set(cache_key, final_title, timeout=60)
        return final_title
            
    except Exception as e:
        print(f"Gemini API (제목) 호출 실패: {e}") # <-- 이제 여기에 다른 에러가 뜨는지 확인하세요.
        return english_title
# -------------------------

def translate_genres_to_korean(genres):
    genre_map = {
        "Action": "액션", "Adventure": "모험", "Comedy": "코미디", "Drama": "드라마",
        "Fantasy": "판타지", "Sci-Fi": "SF", "Romance": "로맨스", "Slice of Life": "일상",
        "Sports": "스포츠", "Thriller": "스릴러", "Horror": "호러", "Supernatural": "초능력",
        "Mystery": "미스테리", "Psychological": "심리"
    }
    return [genre_map.get(g, g) for g in genres]

# --- [★코드 수정★] ---
async def translate_general_text_with_gemini(text):
    if not gemini_client or not text:
        return text

    cache_key = f"general_trans:{hash(text)}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return cached_result

    prompt = (
        f"다음 텍스트를 한국어로 자연스럽게 번역해줘. 번역 결과만 응답하고, 다른 설명이나 부연 설명은 일절 추가하지 마."
        f"텍스트의 내용: {text}"
    )
    
    try:
        # [수정] .aio 속성 사용 및 모델 이름 변경
        response = await gemini_client.aio.models.generate_content(
            model='gemini-2.5-flash', # <-- 1.5를 2.5로 변경
            contents=prompt
        )
        translated_text = response.text.strip()
        
        cache.set(cache_key, translated_text, timeout=60)
        return translated_text
            
    except Exception as e:
        print(f"Gemini API (일반) 호출 실패: {e}")
        return text
# -------------------------

# --- [★코드 수정★] ---
async def translate_search_query_to_english(query):
    if not gemini_client or not query:
        return query

    prompt = (
        f"다음 애니메이션 제목을 AniList에서 가장 정확하게 검색될 수 있는 **짧은 영문 제목** 또는 **로마자 표기**로 번역해줘. "
        f"다른 설명 없이 번역 결과인 영문 텍스트만 응답해. 입력 텍스트: {query}"
    )
    
    try:
        # [수정] .aio 속성을 사용하고, 메서드 이름에서 _async를 제거합니다.
        response = await gemini_client.aio.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        english_query = response.text.strip().replace('"', '')
        return english_query if english_query and len(english_query) > 1 else query

    except Exception as e:
        print(f"Gemini API (검색어) 호출 오류: {e}")
        return query
# -------------------------

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # AniList의 애니 ID를 저장합니다. (인덱스 설정으로 검색 속도 향상)
    anime_id = db.Column(db.Integer, nullable=False, index=True)
    # 간단한 닉네임 방식
    username = db.Column(db.String(80), nullable=False, default="익명")
    # 평점 (0~100점)
    rating = db.Column(db.Integer, nullable=False)
    # 리뷰 텍스트
    text = db.Column(db.Text, nullable=True)
    # 작성 시간
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<Review {self.username} - {self.anime_id}>'

# --- [★추가] 앱 컨텍스트 내에서 DB 테이블 생성 ---
with app.app_context():
    db.create_all()
# -------------------------------------------

@app.route('/')
def home():
    return render_template('index_test.html')

@app.route('/api/search_anime', methods=['GET'])
async def search_anime():
    search_query = request.args.get('query')
    include_movies = request.args.get('includeMovies', 'false') == 'true'

    if not search_query:
        return jsonify({'error': '검색어를 입력해주세요.'}), 400
    
    try:
        final_query = await translate_search_query_to_english(search_query)
    except Exception:
        final_query = search_query

    episodes_greater_filter = ''
    if not include_movies:
        episodes_greater_filter = 'episodes_greater: 1,'

    query = """
    query ($search: String) {
        Page (page: 1, perPage: 10) {
            media ( search: $search, type: ANIME, countryOfOrigin: "JP", %s
                averageScore_greater: 60, genre_not_in: ["Ecchi", "Hentai"],
                sort: [SCORE_DESC, POPULARITY_DESC]
            ) {
                id title { romaji english } genres episodes
                coverImage { extraLarge } averageScore
            }
        }
    }
    """ % episodes_greater_filter

    variables = { 'search': final_query }
    headers = { 'Content-Type': 'application/json', 'Accept': 'application/json', 'User-Agent': 'My-Personal-Anime-App (github.com/dakgs123)', }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(ANILIST_API_URL, headers=headers, json={'query': query, 'variables': variables})
            response.raise_for_status()
            data = response.json()
        
        anime_list = data.get('data', {}).get('Page', {}).get('media', [])
    
        exact_match_list = [
            anime for anime in anime_list
            if final_query.lower() in (anime['title'].get('english') or '').lower() or
               final_query.lower() in (anime['title'].get('romaji') or '').lower()
        ]
        final_list = exact_match_list if exact_match_list else anime_list
    
        translation_tasks = []
        for anime in final_list:
            english_title = anime['title'].get('english') or anime['title'].get('romaji')
            translation_tasks.append(translate_title_to_korean_official(english_title))
        
        korean_titles = await asyncio.gather(*translation_tasks)

        simplified_list = []
        for i, anime in enumerate(final_list):
            simplified_list.append({
                'id': anime.get('id'),
                'title': korean_titles[i],
                'genres': translate_genres_to_korean(anime.get('genres', [])),
                'episodes': anime.get('episodes'),
                'coverImage': anime.get('coverImage', {}).get('extraLarge'),
                'averageScore': anime.get('averageScore')
            })
            
        return jsonify(simplified_list)
            
    except httpx.RequestError as e:
        return jsonify({'error': f'AniList API 요청 실패: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'서버 내부 오류: {str(e)}'}), 500

@app.route('/api/anime_detail/<int:anime_id>', methods=['GET'])
async def get_anime_detail(anime_id):
    query = """
    query ($id: Int) {
        Media (id: $id) {
            id title { romaji english native } genres episodes description(asHtml: false) coverImage { extraLarge }
            startDate { year month day } endDate { year month day }
            characters { edges { node { name { full } } } }
            staff { edges { node { name { full } } role } }
            studios(isMain: true) { nodes { name } }
        }
    }
    """
    variables = { 'id': anime_id }
    headers = { 'Content-Type': 'application/json', 'Accept': 'application/json', 'User-Agent': 'My-Personal-Anime-App (github.com/dakgs123)', }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(ANILIST_API_URL, headers=headers, json={'query': query, 'variables': variables})
            response.raise_for_status()
            data = response.json()
        
        anime_detail = data.get('data', {}).get('Media', {})
        if not anime_detail:
             return jsonify({'error': '해당 ID의 애니메이션을 찾을 수 없습니다.'}), 404

        english_title_candidate = anime_detail.get('title', {}).get('english') or anime_detail.get('title', {}).get('romaji')
        original_description = anime_detail.get('description')
        original_staff_edges = anime_detail.get('staff', {}).get('edges', [])

        tasks_to_run = [
            translate_title_to_korean_official(english_title_candidate),
            translate_general_text_with_gemini(original_description)
        ]
        
        role_tasks = [translate_general_text_with_gemini(edge['role']) for edge in original_staff_edges]
        tasks_to_run.extend(role_tasks)

        all_translated_results = await asyncio.gather(*tasks_to_run)

        korean_title = all_translated_results[0]
        korean_description = all_translated_results[1]
        korean_roles = all_translated_results[2:]

        staff_list = []
        for i, edge in enumerate(original_staff_edges):
            staff_list.append({
                'name': edge['node']['name']['full'],
                'role': korean_roles[i]
            })

        simplified_detail = {
            'id': anime_detail.get('id'),
            'title': korean_title,
            'genres': translate_genres_to_korean(anime_detail.get('genres', [])),
            'episodes': anime_detail.get('episodes'),
            'description': korean_description,
            'coverImage': anime_detail.get('coverImage', {}).get('extraLarge'),
            'startDate': anime_detail.get('startDate'),
            'endDate': anime_detail.get('endDate'),
            'characters': [edge['node']['name']['full'] for edge in anime_detail.get('characters', {}).get('edges', [])],
            'staff': staff_list,
            'studios': [node['name'] for node in anime_detail.get('studios', {}).get('nodes', [])]
        }
        
        return jsonify(simplified_detail)
            
    except httpx.RequestError as e:
        return jsonify({'error': f'상세 정보 API 요청 실패: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'서버 내부 오류: {str(e)}'}), 500
        
@app.route('/api/popular_anime', methods=['GET'])
async def get_popular_anime():
    query = """
    query {
        Page (page: 1, perPage: 5) {
            media ( type: ANIME, countryOfOrigin: "JP", episodes_greater: 1,
                genre_not_in: ["Ecchi", "Hentai"], sort: [POPULARITY_DESC]
            ) {
                id title { romaji english } genres episodes coverImage { extraLarge }
                averageScore
            }
        }
    }
    """
    headers = { 'Content-Type': 'application/json', 'Accept': 'application/json', 'User-Agent': 'My-Personal-Anime-App (github.com/dakgs123)', }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(ANILIST_API_URL, headers=headers, json={'query': query})
            response.raise_for_status()
            data = response.json()
            
        anime_list = data.get('data', {}).get('Page', {}).get('media', [])
    
        translation_tasks = []
        for anime in anime_list:
            english_title = anime['title'].get('english') or anime['title'].get('romaji')
            translation_tasks.append(translate_title_to_korean_official(english_title))

        korean_titles = await asyncio.gather(*translation_tasks)

        simplified_list = []
        for i, anime in enumerate(anime_list):
            simplified_list.append({
                'id': anime.get('id'),
                'title': korean_titles[i],
                'genres': translate_genres_to_korean(anime.get('genres', [])),
                'episodes': anime.get('episodes'),
                'coverImage': anime.get('coverImage', {}).get('extraLarge'),
                'averageScore': anime.get('averageScore')
            })
            
        return jsonify(simplified_list)
            
    except httpx.RequestError as e:
        return jsonify({'error': f'인기 애니메이션 API 요청 실패: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'서버 내부 오류: {str(e)}'}), 500
        
# --- [★추가] 새 리뷰 작성 API (Sync) ---
@app.route('/api/review', methods=['POST'])
def add_review():
    try:
        data = request.get_json()
        if not data or 'animeId' not in data or 'rating' not in data:
            return jsonify({'error': '필수 데이터가 없습니다 (animeId, rating).'}), 400
        
        username = data.get('username', '익명').strip()
        if not username:
            username = "익명"

        new_review = Review(
            anime_id=data['animeId'],
            rating=data['rating'],
            text=data.get('text'),
            username=username
        )
        
        db.session.add(new_review)
        db.session.commit()
        
        return jsonify({'message': '리뷰가 성공적으로 등록되었습니다.'}), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'리뷰 저장 실패: {str(e)}'}), 500

# --- [★추가] 특정 애니메이션 리뷰 목록 API (Sync) ---
@app.route('/api/reviews/<int:anime_id>', methods=['GET'])
def get_reviews(anime_id):
    try:
        # 최신순으로 정렬
        reviews = Review.query.filter_by(anime_id=anime_id).order_by(Review.created_at.desc()).all()
        
        review_list = [
            {
                'id': r.id,
                'username': r.username,
                'rating': r.rating,
                'text': r.text,
                'created_at': r.created_at.strftime('%Y-%m-%d %H:%M') # 날짜 포맷팅
            } for r in reviews
        ]
        return jsonify(review_list)
        
    except Exception as e:
        return jsonify({'error': f'리뷰 로딩 실패: {str(e)}'}), 500

if __name__ == '__main__':
    # 'python test.py'로 직접 실행할 경우
    app.run(debug=True, port=5000)
