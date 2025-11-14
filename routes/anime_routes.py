# routes/anime_routes.py
from flask import Blueprint, request, render_template
import httpx
import asyncio
import html
from extensions import db, cache
from models import Review
from utils import create_response, get_english_title, translate_genres_to_korean
from services.gemini_service import translate_title_to_korean_official, translate_general_text, translate_search_query

# Blueprint 생성
anime_bp = Blueprint('anime', __name__)
ANILIST_API_URL = 'https://graphql.anilist.co'

@anime_bp.route('/')
def home():
    return render_template('index.html')

@anime_bp.route('/api/search_anime', methods=['GET'])
async def search_anime():
    search_query = request.args.get('query')
    include_movies = request.args.get('includeMovies', 'false') == 'true'

    if not search_query:
        # ★ 수정: jsonify -> create_response
        return create_response(success=False, error='검색어를 입력해주세요.', status=400)
    
    try:
        # ★ 수정: gemini_service 함수 사용
        final_query = await translate_search_query(search_query) 
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
            # ★ 수정: utils 헬퍼 함수 사용
            english_title = get_english_title(anime) 
            # ★ 수정: gemini_service 함수 사용
            translation_tasks.append(translate_title_to_korean_official(english_title))
        
        korean_titles = await asyncio.gather(*translation_tasks)

        simplified_list = []
        for i, anime in enumerate(final_list):
            simplified_list.append({
                'id': anime.get('id'),
                'title': korean_titles[i],
                # ★ 수정: utils 헬퍼 함수 사용
                'genres': translate_genres_to_korean(anime.get('genres', [])), 
                'episodes': anime.get('episodes'),
                'coverImage': anime.get('coverImage', {}).get('extraLarge'),
                'averageScore': anime.get('averageScore')
            })
            
        # ★ 수정: jsonify(list) -> create_response(data=list)
        return create_response(data=simplified_list)
            
    except httpx.RequestError as e:
        print(f"AniList API 요청 에러: {e}")
        # ★ 수정: jsonify -> create_response
        return create_response(success=False, error='애니메이션 정보를 가져오는 데 실패했습니다.', status=502)
    except Exception as e:
        print(f"서버 내부 에러: {e}")
        # ★ 수정: jsonify -> create_response
        return create_response(success=False, error=f'서버 내부 오류: {str(e)}', status=500)

# [리뷰 작성 API 예시]
@anime_bp.route('/api/review', methods=['POST'])
def add_review():
    try:
        data = request.get_json()
        # ... (유효성 검사) ...
        
        new_review = Review(
            anime_id=data['animeId'],
            rating=data['rating'],
            text=html.escape(data.get('text', '')),
            username=html.escape(data.get('username', '익명'))
        )
        db.session.add(new_review)
        db.session.commit()
        return create_response(data={'message': '성공'}, status=201)
    except Exception as e:
        db.session.rollback()
        return create_response(success=False, error=str(e), status=500)
    
#
# (파일 맨 아래, add_review 함수가 끝난 다음 줄에 붙여넣기)
#

@anime_bp.route('/api/popular_anime', methods=['GET'])
@cache.cached(timeout=600) # 10분간 캐싱
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
    headers = { 'Content-Type': 'application/json', 'Accept': 'application/json', 'User-Agent': 'My-Personal-Anime-App', }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(ANILIST_API_URL, headers=headers, json={'query': query})
            response.raise_for_status()
            data = response.json()
            
        anime_list = data.get('data', {}).get('Page', {}).get('media', [])
    
        translation_tasks = []
        for anime in anime_list:
            english_title = get_english_title(anime) # utils 헬퍼 사용
            translation_tasks.append(translate_title_to_korean_official(english_title))

        korean_titles = await asyncio.gather(*translation_tasks)

        simplified_list = []
        for i, anime in enumerate(anime_list):
            simplified_list.append({
                'id': anime.get('id'),
                'title': korean_titles[i],
                'genres': translate_genres_to_korean(anime.get('genres')), # utils 헬퍼
                'episodes': anime.get('episodes'),
                'coverImage': anime.get('coverImage', {}).get('extraLarge'),
                'averageScore': anime.get('averageScore')
            })
            
        return create_response(data=simplified_list)
            
    except Exception as e:
        print(f"인기 애니 에러: {e}")
        return create_response(success=False, error='인기 리스트 로딩 실패', status=500)


@anime_bp.route('/api/anime_detail/<int:anime_id>', methods=['GET'])
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
    headers = { 'Content-Type': 'application/json', 'Accept': 'application/json', 'User-Agent': 'My-Personal-Anime-App', }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(ANILIST_API_URL, headers=headers, json={'query': query, 'variables': variables})
            response.raise_for_status()
            data = response.json()
        
        anime_detail = data.get('data', {}).get('Media', {})
        if not anime_detail:
             return create_response(success=False, error='애니메이션을 찾을 수 없습니다.', status=404)

        english_title_candidate = get_english_title(anime_detail) # utils 헬퍼
        original_description = anime_detail.get('description')
        original_staff_edges = anime_detail.get('staff', {}).get('edges', [])

        # ★ 서비스 함수 사용 (제목, 설명 번역)
        tasks_to_run = [
            translate_title_to_korean_official(english_title_candidate),
            translate_general_text(original_description)
        ]
        
        # ★ 서비스 함수 사용 (스태프 역할 번역)
        role_tasks = [translate_general_text(edge['role']) for edge in original_staff_edges]
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
            'genres': translate_genres_to_korean(anime_detail.get('genres')), # utils
            'episodes': anime_detail.get('episodes'),
            'description': korean_description,
            'coverImage': anime_detail.get('coverImage', {}).get('extraLarge'),
            'startDate': anime_detail.get('startDate'),
            'endDate': anime_detail.get('endDate'),
            'characters': [edge['node']['name']['full'] for edge in anime_detail.get('characters', {}).get('edges', [])],
            'staff': staff_list,
            'studios': [node['name'] for node in anime_detail.get('studios', {}).get('nodes', [])]
        }
        
        return create_response(data=simplified_detail)
            
    except Exception as e:
        print(f"상세 정보 로딩 에러: {e}")
        return create_response(success=False, error='상세 정보를 불러오지 못했습니다.', status=500)


@anime_bp.route('/api/reviews/<int:anime_id>', methods=['GET'])
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
                'created_at': r.created_at.strftime('%Y-%m-%d %H:%M')
            } for r in reviews
        ]
        return create_response(data=review_list)
        
    except Exception as e:
        return create_response(success=False, error=f'리뷰 로딩 실패: {str(e)}', status=500)