import os
from google import genai
from google.genai import types
from extensions import cache

def _create_client_safely():
    """
    [★새 함수] 클라이언트가 필요할 때마다 호출되어 생성합니다.
    API 키가 없으면 None을 반환합니다.
    """
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            # Flask의 비동기 컨텍스트 내에서 클라이언트를 생성
            # genai.Client() 자체는 동기 함수이므로 여기서 생성해도 안전합니다.
            return genai.Client(http_options=types.HttpOptions(api_version='v1'))
        else:
            print("Gemini API Key 없음 (in _create_client_safely)")
            return None
    except Exception as e:
        print(f"Gemini 클라이언트 생성 실패: {e}")
        return None

async def translate_title_to_korean_official(english_title):
    # [★수정] 함수가 호출될 때마다 새 클라이언트를 생성합니다.
    client = _create_client_safely() 
    
    if not client or not english_title:
        return english_title
        
    cache_key = f"title_trans:{english_title}"
    cached = cache.get(cache_key)
    if cached: return cached

    prompt = (
        f"당신은 요청받은 애니메이션의 '공식 한국어 제목' 1개만 반환하는 번역 API입니다.\n"
        f"절대로 당신의 생각, [THOUGHT] 태그, 또는 다른 부연 설명을 출력하지 마세요.\n"
        f"오직 제목만 응답해야 합니다.\n\n"
        f"영어 제목: {english_title}\n"
        f"한국어 제목:"
    )
    try:
        response = await client.aio.models.generate_content(
            model='gemini-2.5-flash', contents=prompt
        )
        result = response.text.strip().replace('"', '')
        final = result if result else english_title
        cache.set(cache_key, final, timeout=86400)
        return final
    except Exception as e:
        print(f"제목 번역 실패: {e}")
        return english_title

async def translate_general_text(text):
    # [★수정] 매번 새 클라이언트를 생성합니다.
    client = _create_client_safely()

    if not client or not text: return text
    
    cache_key = f"general_trans:{hash(text)}"
    cached = cache.get(cache_key)
    if cached: return cached

    try:
        response = await client.aio.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"다음 텍스트를 한국어로 자연스럽게 번역해(설명X): {text}"
        )
        result = response.text.strip()
        cache.set(cache_key, result, timeout=300)
        return result
    except Exception as e:
        print(f"--- 줄거리/일반 번역 실패 ---: {e}")
        return text

async def translate_search_query(query):
    # [★수정] 매번 새 클라이언트를 생성합니다.
    client = _create_client_safely()

    if not client or not query: return query
    try:
        response = await client.aio.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"AniList 검색용 영문/로마자 제목으로 변환해(설명X, 제목만 말해): {query}"
        )
        result = response.text.strip().replace('"', '')
        return result if len(result) > 1 else query
    except Exception as e:
        print(f"--- 검색어 번역 실패 ---: {e}")
        return query