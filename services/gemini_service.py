# services/gemini_service.py
import os
from google import genai
from google.genai import types
from extensions import cache

# 클라이언트 초기화
gemini_client = None
try:
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        gemini_client = genai.Client(http_options=types.HttpOptions(api_version='v1'))
        print("Gemini Service 초기화 성공")
    else:
        print("Gemini API Key 없음")
except Exception as e:
    print(f"Gemini 초기화 실패: {e}")

async def translate_title_to_korean_official(english_title):
    if not gemini_client or not english_title:
        return english_title
        
    cache_key = f"title_trans:{english_title}"
    cached = cache.get(cache_key)
    if cached: return cached

    prompt = f"다음 애니메이션 제목을 한국 공식 정발 제목으로 번역해(설명X, 제목만): {english_title}"
    try:
        response = await gemini_client.aio.models.generate_content(
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
    if not gemini_client or not text: return text
    
    cache_key = f"general_trans:{hash(text)}"
    cached = cache.get(cache_key)
    if cached: return cached

    try:
        response = await gemini_client.aio.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"다음 텍스트를 한국어로 자연스럽게 번역해(설명X): {text}"
        )
        result = response.text.strip()
        cache.set(cache_key, result, timeout=300)
        return result
    except Exception:
        return text

async def translate_search_query(query):
    if not gemini_client or not query: return query
    try:
        response = await gemini_client.aio.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"AniList 검색용 영문/로마자 제목으로 변환해(설명X): {query}"
        )
        result = response.text.strip().replace('"', '')
        return result if len(result) > 1 else query
    except Exception:
        return query