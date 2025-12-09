# routes/anime_routes.py
from flask import Blueprint, request, render_template
import httpx
import asyncio
import html
import random 
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

# routes/anime_routes.py

@anime_bp.route('/api/search_anime', methods=['GET'])
async def search_anime():
    search_query = request.args.get('query')
    include_movies = request.args.get('includeMovies', 'false') == 'true'
    genre = request.args.get('genre')
    sort_option = request.args.get('sort', 'POPULARITY_DESC')

    # 1. 검색어와 장르 둘 다 없으면 에러
    if not search_query and not genre:
        return create_response(success=False, error='검색어를 입력하거나 장르를 선택해주세요.', status=400)
    
    final_query = search_query
    # 검색어가 있을 때만 번역 (DB 저장은 안 함)
    if search_query:
        try:
            final_query = await translate_search_query(search_query) 
        except Exception:
            final_query = search_query

    # --- [★핵심 수정] 쿼리 조건을 리스트로 관리 (쉼표 오류 방지) ---
    # 1. 기본 조건들
    args_list = [
        'type: ANIME',
        'countryOfOrigin: "JP"',
        'averageScore_greater: 60',
        'genre_not_in: ["Ecchi", "Hentai"]',
        f'sort: [{sort_option}]'
    ]

    # 2. 동적 조건 추가
    if search_query:
        args_list.append('search: $search')
    
    if not include_movies:
        args_list.append('episodes_greater: 1')
        
    if genre:
        args_list.append(f'genre: "{genre}"')

    # 3. 리스트를 쉼표로 예쁘게 연결
    args_str = ', '.join(args_list)

    # 4. 쿼리 헤더 결정 (검색어 변수가 있을 때만 괄호 사용)
    query_header = 'query ($search: String)' if search_query else 'query'

    # 5. 최종 쿼리 조립
    query = f"""
    {query_header} {{
        Page (page: 1, perPage: 10) {{
            media ({args_str}) {{
                id title {{ romaji english }} genres episodes
                coverImage {{ extraLarge }} averageScore
            }}
        }}
    }}
    """

    variables = {}
    if search_query:
        variables['search'] = final_query
    
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'My-Personal-Anime-App (github.com/dakgs123)',
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(ANILIST_API_URL, headers=headers, json={'query': query, 'variables': variables})
            response.raise_for_status()
            data = response.json()
        
        anime_list = data.get('data', {}).get('Page', {}).get('media', [])
    
        # 검색어가 있을 때만 정확도 필터링 수행
        final_list = anime_list
        if search_query:
            exact_match_list = [
                anime for anime in anime_list
                if final_query.lower() in (anime['title'].get('english') or '').lower() or
                   final_query.lower() in (anime['title'].get('romaji') or '').lower()
            ]
            final_list = exact_match_list if exact_match_list else anime_list
    
        translation_tasks = []
        for anime in final_list:
            english_title = get_english_title(anime)
            # 검색 리스트이므로 검증 끄기 (속도 최적화)
            translation_tasks.append(translate_title_to_korean_official(english_title, use_verification=False))
        
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
            
        return create_response(data=simplified_list)
            
    except httpx.RequestError as e:
        print(f"AniList API 요청 에러: {e}")
        return create_response(success=False, error='애니메이션 정보를 가져오는 데 실패했습니다.', status=502)
    except Exception as e:
        print(f"서버 내부 에러: {e}")
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
    headers = { 'Content-Type': 'application/json', 'Accept': 'application/json', 'User-Agent': 'My-Personal-Anime-App (github.com/dakgs123)', }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(ANILIST_API_URL, headers=headers, json={'query': query})
            response.raise_for_status()
            data = response.json()
            
        anime_list = data.get('data', {}).get('Page', {}).get('media', [])
    
        translation_tasks = []
        for anime in anime_list:
            english_title = get_english_title(anime) # utils 헬퍼 사용
            translation_tasks.append(translate_title_to_korean_official(english_title, use_verification=False))

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
    headers = { 'Content-Type': 'application/json', 'Accept': 'application/json', 'User-Agent': 'My-Personal-Anime-App (github.com/dakgs123)', }
    
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
        original_staff_edges = anime_detail.get('staff', {}).get('edges', []) # [★] 모든 스태프 원본 가져오기

        # [★수정] 제목과 줄거리 번역만 요청 (API 호출 2회)
        tasks_to_run = [
            translate_title_to_korean_official(english_title_candidate),
            translate_general_text(original_description)
        ]
        
        all_translated_results = await asyncio.gather(*tasks_to_run)

        # [★수정] 결과도 2개만 받음
        korean_title = all_translated_results[0]
        korean_description = all_translated_results[1]
        # [★삭제] korean_roles = all_translated_results[2:] 삭제

        staff_list = []
        # [★수정] 번역된 역할(korean_roles) 대신, 원본(edge['role'])을 그대로 사용
        for edge in original_staff_edges:
            staff_list.append({
                'name': edge['node']['name']['full'],
                'role': edge['role'] # <-- 원본(영어) 역할 사용
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
        # [★수정] 아까 추가했던 에러 로그를 여기서도 확인
        print(f"상세 정보 로딩 에러 (API 키 문제일 수 있음): {e}") 
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
    
# routes/anime_routes.py

# routes/anime_routes.py

@anime_bp.route('/api/recommendations', methods=['GET'])
@cache.cached(timeout=5)
async def get_recommendations():
    genre = request.args.get('genre')
    sort_option = request.args.get('sort', 'POPULARITY_DESC') # [★추가] 정렬 옵션 받기

    try:
        # [★수정] 장르나 정렬 기준이 변경되면 유효 데이터 범위를 고려해 페이지 랜덤 범위 축소
        # (예: 평점순 정렬 시 200페이지로 가면 평점 낮은 게 나올 수 있으므로 앞쪽에서 랜덤 추출)
        if genre or sort_option != 'POPULARITY_DESC':
            random_page = random.randint(1, 50) 
        else:
            random_page = random.randint(1, 200) # 기본 인기순일 때는 넓게 탐색
        
        # 필터 조건 조립
        filters = 'episodes_greater: 1,'
        if genre:
            filters += f' genre: "{genre}",'

        # [★수정] 쿼리에 sort 변수 적용
        query = """
        query ($page: Int) {
            Page (page: $page, perPage: 5) {
                media ( type: ANIME, countryOfOrigin: "JP", 
                    genre_not_in: ["Ecchi", "Hentai"], 
                    %s 
                    sort: [%s] 
                ) {
                    id title { romaji english } genres episodes coverImage { extraLarge }
                    averageScore
                }
            }
        }
        """ % (filters, sort_option) # 여기에 필터와 정렬 옵션 삽입

        variables = { 'page': random_page }
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'My-Personal-Anime-App (github.com/dakgs123)',
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(ANILIST_API_URL, headers=headers, json={'query': query, 'variables': variables})
            response.raise_for_status()
            data = response.json()
            
        anime_list = data.get('data', {}).get('Page', {}).get('media', [])
        
        # [안전장치] 빈 페이지일 경우 1페이지 재요청
        if not anime_list:
            variables['page'] = 1
            async with httpx.AsyncClient() as client:
                response = await client.post(ANILIST_API_URL, headers=headers, json={'query': query, 'variables': variables})
                data = response.json()
            anime_list = data.get('data', {}).get('Page', {}).get('media', [])

        # 번역 로직 (빠른 속도 위해 검증 끔)
        korean_titles = []
        for anime in anime_list:
            english_title = get_english_title(anime)
            translated_title = await translate_title_to_korean_official(english_title, use_verification=False)
            korean_titles.append(translated_title)

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
            
        return create_response(data=simplified_list)
            
    except Exception as e:
        print(f"추천 애니 에러: {e}")
        return create_response(success=False, error='추천 리스트 로딩 실패', status=500)