# utils.py
from flask import jsonify

def create_response(success=True, data=None, error=None, status=200):
    """API 응답 표준화 함수"""
    response = {
        "success": success,
        "data": data,
        "error": error
    }
    return jsonify(response), status

def get_english_title(media_node):
    """AniList 데이터에서 영어/로마자 제목 추출"""
    if not media_node or 'title' not in media_node:
        return "Unknown Title"
    return media_node['title'].get('english') or media_node['title'].get('romaji')

def translate_genres_to_korean(genres):
    if not genres: return []
    genre_map = {
        "Action": "액션", "Adventure": "모험", "Comedy": "코미디", "Drama": "드라마",
        "Fantasy": "판타지", "Sci-Fi": "SF", "Romance": "로맨스", "Slice of Life": "일상",
        "Sports": "스포츠", "Thriller": "스릴러", "Horror": "호러", "Supernatural": "초능력",
        "Mystery": "미스테리", "Psychological": "심리", "Mahou Shoujo": "마법소녀", "Mecha": "메카"
    }
    return [genre_map.get(g, g) for g in genres]