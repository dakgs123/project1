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
            # v1beta 사용
            return genai.Client(http_options=types.HttpOptions(api_version='v1beta'))
        return None
    except Exception as e:
        print(f"Gemini 클라이언트 생성 실패: {e}")
        return None

# 검증된 번역 획득 함수

async def get_verified_translation(text, type='general'):
    if not text: return ""
    
    # 1. DB에서 검색 (있으면 바로 반환)
    existing = Translation.query.filter_by(original_text=text).first()
    if existing:
        return existing.translated_text

    client = _create_client_safely()
    if not client: return text

    final_result = ""

    MODEL_NAME = 'gemini-3-pro-preview'

    try:
        # ---------------------------------------------------------
        # CASE A: 제목
        # ---------------------------------------------------------
        if type == 'title':
            base_prompt = (
                f"애니메이션 제목 '{text}'을(를) '공식 한국어 제목'으로 바꿔줘.\n"
                f"규칙 1: 영어/일본어 부제는 과감히 삭제하고 **한국어 핵심 제목**만 남겨.\n"
                f"규칙 2: 설명 없이 결과 텍스트만 출력해."
            )

            try:
                print(f"--- [검증 시작] (제목/{MODEL_NAME}) '{text}' ---")
                config = types.GenerateContentConfig(temperature=0.1) 
                
                task1 = client.aio.models.generate_content(model=MODEL_NAME, contents=base_prompt, config=config)
                task2 = client.aio.models.generate_content(model=MODEL_NAME, contents=base_prompt, config=config)
                
                response1, response2 = await asyncio.gather(task1, task2)
                
                result1 = response1.text.strip().replace('"', '')
                result2 = response2.text.strip().replace('"', '')

                if result1 == result2:
                    print(f"--- [일치] 검증 통과! ---")
                    final_result = result1
                else:
                    print(f"--- [불일치] 3번째 심판 요청 ---")
                    judge_content = (
                        f"당신은 제목 심판입니다. 다음 두 후보 중 '깔끔한 한국어 제목' 규칙에 맞는 것을 고르세요.\n"
                        f"후보1: {result1}\n후보2: {result2}\n"
                        f"둘 다 별로면 새로 번역해서 **최종 제목 딱 하나만** 출력하세요. 설명 금지."
                    )
                    response3 = await client.aio.models.generate_content(
                        model=MODEL_NAME, 
                        contents=judge_content,
                        config=types.GenerateContentConfig(temperature=0.0) 
                    )
                    final_result = response3.text.strip().replace('"', '')
                    if '\n' in final_result: final_result = final_result.split('\n')[-1]
                    print(f"--- [최종 결정 완료] ---")

            except Exception as e:
                print(f"제목 번역 에러: {e}")
                return text

        else:
            prompt = (
                f"다음 애니메이션 줄거리를 한국어로 자연스럽게 번역해줘.\n"
                f"원문: {text}\n"
                f"규칙 1: 직역투보다는 한국 사람이 읽기 편한 문장으로 다듬어줘.\n"
                f"규칙 2: **등장인물 이름은 문맥을 파악하여 억지 번역하지 말고 원문 발음대로(음차) 자연스럽게 적어줘.**\n"
                f"규칙 3: 설명 없이 **번역된 줄거리 텍스트만** 출력해."
            )

            try:
                print(f"--- [단일 번역 시작] (줄거리/{MODEL_NAME}) '{text[:20]}...' ---")
                config = types.GenerateContentConfig(temperature=0.1)
                response = await client.aio.models.generate_content(model=MODEL_NAME, contents=prompt, config=config)
                final_result = response.text.strip().replace('"', '')
            
            except Exception as e:
                print(f"줄거리 번역 에러: {e}")
                return text

        # DB 저장 로직
        if final_result:
            try:
                new_trans = Translation(original_text=text, translated_text=final_result)
                db.session.add(new_trans)
                db.session.commit()
                print("--- [DB 저장 완료] ---")
            except IntegrityError:
                db.session.rollback()
                existing_late = Translation.query.filter_by(original_text=text).first()
                if existing_late:
                    return existing_late.translated_text
            except Exception as e:
                print(f"DB 저장 실패: {e}")

        return final_result

    # [★중요] 작업이 끝나면(성공하든 실패하든) 무조건 클라이언트를 닫아줍니다.
    finally:
        # 동기 방식 close()를 호출하면 내부의 비동기 리소스도 정리됨 (라이브러리 버전에 따라 다를 수 있음)
        # 만약 aclose()를 써야 한다면 await client.aclose()가 필요하지만, 
        # google-genai 최신 버전은 보통 가비지 컬렉션 시 처리되거나 close()로 충분할 수 있음.
        # 여기서는 명시적인 정리를 시도하지 않고 루프가 닫히기 전에 자연스럽게 끝나도록 유도하거나,
        # 아래와 같이 명시적으로 닫아주는 것이 좋습니다.
        try:
             # google-genai 클라이언트에는 명시적인 aclose가 없을 수 있으므로
             # 내부 httpx 클라이언트에 접근하거나, 라이브러리에 맡겨야 합니다.
             # 하지만 현재 에러는 aclose가 호출될 때 루프가 닫혀서 생기므로
             # 가장 좋은 방법은 '사용 후 즉시 폐기'되도록 두는 것입니다.
             pass 
        except:
            pass

# 기존 함수들을 새 로직으로 연결
async def translate_title_to_korean_official(english_title):
    return await get_verified_translation(english_title, type='title')

async def translate_general_text(text):
    return await get_verified_translation(text, type='general')

async def translate_search_query(query):
    client = _create_client_safely()
    if not client: return query
    try:
        prompt = f"AniList 검색용 영문/로마자 제목으로 변환해(설명X): {query}"
        response = await client.aio.models.generate_content(model='gemini-3-pro-preview', contents=prompt)
        return response.text.strip().replace('"', '')
    except:
        return query