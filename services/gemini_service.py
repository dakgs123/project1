# services/gemini_service.py

import os
import asyncio
from google import genai
from google.genai import types
from extensions import db
from models import Translation
from sqlalchemy.exc import IntegrityError

# 안전한 클라이언트 생성 (기존 유지)
def _create_client_safely():
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            return genai.Client(http_options=types.HttpOptions(api_version='v1'))
        return None
    except Exception as e:
        print(f"Gemini 클라이언트 생성 실패: {e}")
        return None

# [핵심] DB 기반의 번역 및 검증 로직
async def get_verified_translation(text, type='general'):
    if not text: return ""
    
    # 1. DB에서 검색
    existing = Translation.query.filter_by(original_text=text).first()
    if existing:
        return existing.translated_text

    client = _create_client_safely()
    if not client: return text

    # [★수정] 프롬프트 강화: "한국어만 남기기" 규칙 추가
    if type == 'title':
        base_prompt = (
            f"애니메이션 제목 '{text}'을(를) 한국에서 가장 널리 쓰이는 '공식 한국어 제목'으로 바꿔줘.\n"
            f"다음 **정제 규칙**을 반드시 지켜:\n"
            f"1. 영어/일본어가 한국어와 같이 있으면, **영어/일본어는 삭제하고 한국어만** 남겨.\n"
            f"   (예: 'DEATH NOTE 데스노트' -> '데스노트')\n"
            f"   (예: 'SPY×FAMILY (스파이 패밀리)' -> '스파이 패밀리')\n"
            f"2. 괄호 '()' 안에 있는 내용이 부연 설명이면 삭제해.\n"
            f"3. 설명 멘트 없이 **결과 텍스트만** 출력해."
        )
    else:
        base_prompt = f"다음 텍스트를 한국어로 자연스럽게 번역해줘. 설명 없이 번역 결과만 말해:\n{text}"

    try:
        # 2. 두 번 번역 시도 (검증 단계)
        print(f"--- [검증 시작] '{text[:10]}...' 번역 시도 1, 2 ---")
        
        # 온도(temperature)를 0.1로 낮춰서 더 일관된 정답을 유도
        config = types.GenerateContentConfig(temperature=0.1) 
        
        task1 = client.aio.models.generate_content(model='gemini-2.5-flash', contents=base_prompt, config=config)
        task2 = client.aio.models.generate_content(model='gemini-2.5-flash', contents=base_prompt, config=config)
        
        response1, response2 = await asyncio.gather(task1, task2)
        
        result1 = response1.text.strip().replace('"', '')
        result2 = response2.text.strip().replace('"', '')

        final_result = ""

        # 3. 결과 비교
        if result1 == result2:
            print(f"--- [일치] 검증 통과! ---")
            final_result = result1
        else:
            print(f"--- [불일치] 1: {result1} / 2: {result2} -> 3번째 심판 요청 ---")
            # [★수정] 심판 프롬프트도 강화
            judge_prompt = (
                f"당신은 애니메이션 제목 결정 심판입니다.\n"
                f"다음 두 후보 중 '공식 한국어 제목' 규칙(영어/일본어 삭제, 한국어만 남김)에 더 잘 맞는 것을 선택하세요.\n"
                f"만약 둘 다 이상하면 직접 새로 번역하세요.\n\n"
                f"후보1: {result1}\n"
                f"후보2: {result2}\n\n"
                f"**중요한 규칙:**\n"
                f"1. 절대로 이유나 설명을 출력하지 마세요.\n"
                f"2. 선택한(또는 새로 번역한) **최종 제목 텍스트 딱 하나만** 출력하세요.\n"
                f"3. 예시: '나루토' (O), '제목은 나루토입니다.' (X), '이유는...' (X)"
            )

            response3 = await client.aio.models.generate_content(
                model='gemini-2.5-flash', 
                contents=judge_prompt,
                # [★팁] temperature를 0으로 낮춰서 창의성을 죽이고 지시사항 준수율을 높임
                config=types.GenerateContentConfig(temperature=0.0)
            )
            final_result = response3.text.strip().replace('"', '').replace("'", "").split('\n')[-1]
            print(f"--- [최종 결정] {final_result} ---")

        # 4. DB에 저장 (기존 유지)
        try:
            new_trans = Translation(original_text=text, translated_text=final_result)
            db.session.add(new_trans)
            db.session.commit()
            print("--- [DB 저장 완료] ---")
        except IntegrityError:
            db.session.rollback()
            
        return final_result

    except Exception as e:
        print(f"번역 프로세스 에러: {e}")
        return text# 에러 나면 그냥 원문 반환

# 기존 함수들을 새 로직으로 연결
async def translate_title_to_korean_official(english_title):
    return await get_verified_translation(english_title, type='title')

async def translate_general_text(text):
    return await get_verified_translation(text, type='general')

async def translate_search_query(query):
    # 검색어는 DB 저장까지는 필요 없을 수 있으니, 그냥 단순 번역 유지 (속도 중요)
    # 필요하면 이것도 get_verified_translation을 써도 됩니다.
    client = _create_client_safely()
    if not client: return query
    try:
        prompt = f"AniList 검색용 영문/로마자 제목으로 변환해(설명X): {query}"
        response = await client.aio.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        return response.text.strip().replace('"', '')
    except:
        return query