# services/gemini_service.py

import os
import asyncio
from google import genai
from google.genai import types
from extensions import db
from models import Translation
from sqlalchemy.exc import IntegrityError

# 안전한 클라이언트 생성
def _create_client_safely():
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            # v1beta 사용 (Gemini 3 Pro용)
            return genai.Client(http_options=types.HttpOptions(api_version='v1beta'))
        return None
    except Exception as e:
        print(f"Gemini 클라이언트 생성 실패: {e}")
        return None

# [★수정] use_verification=True (기본값: 검증 켬)
async def get_verified_translation(text, type='general', use_verification=True):
    if not text: return ""
    
    # 1. DB에서 검색
    existing = Translation.query.filter_by(original_text=text).first()
    if existing:
        return existing.translated_text

    client = _create_client_safely()
    if not client: return text

    final_result = ""
    
    
    MODEL_NAME = 'gemini-3-pro-preview'


    try:
        # ---------------------------------------------------------
        # CASE A: 제목 번역
        # ---------------------------------------------------------
        if type == 'title':
            base_prompt = (
                f"애니메이션 제목 '{text}'을(를) '공식 한국어 제목'으로 바꿔줘.\n"
                f"규칙 1: 영어/일본어 부제는 과감히 삭제하고 **한국어 핵심 제목**만 남겨.\n"
                f"규칙 2: 설명 없이 결과 텍스트만 출력해."
            )

            # [★분기 1] 정밀 검증 모드 (상세 페이지용 - 느리지만 정확함)
            if use_verification:
                print(f"--- [정밀 검증] (제목/{MODEL_NAME}) '{text}' ---")
                config = types.GenerateContentConfig(temperature=0.1) 
                
                task1 = client.aio.models.generate_content(model=MODEL_NAME, contents=base_prompt, config=config)
                task2 = client.aio.models.generate_content(model=MODEL_NAME, contents=base_prompt, config=config)
                
                response1, response2 = await asyncio.gather(task1, task2)
                
                result1 = response1.text.strip().replace('"', '')
                result2 = response2.text.strip().replace('"', '')

                if result1 == result2:
                    # print(f"--- [일치] 검증 통과! ---")
                    final_result = result1
                else:
                    # print(f"--- [불일치] 3번째 심판 요청 ---")
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
                    # print(f"--- [최종 결정 완료] ---")
            
            # [★분기 2] 고속 모드 (검색 리스트용 - 1번만 번역)
            else:
                # print(f"--- [빠른 번역] (제목) '{text}' ---")
                config = types.GenerateContentConfig(temperature=0.1)
                response = await client.aio.models.generate_content(model=MODEL_NAME, contents=base_prompt, config=config)
                final_result = response.text.strip().replace('"', '')

        # ---------------------------------------------------------
        # CASE B: 줄거리/일반 (항상 1번만 번역)
        # ---------------------------------------------------------
        else:
            prompt = (
                f"다음 애니메이션 줄거리를 한국어로 자연스럽게 번역해줘.\n"
                f"원문: {text}\n"
                f"규칙 1: 직역투보다는 한국 사람이 읽기 편한 문장으로 다듬어줘.\n"
                f"규칙 2: **등장인물 이름은 문맥을 파악하여 억지 번역하지 말고 원문 발음대로(음차) 자연스럽게 적어줘.**\n"
                f"규칙 3: 설명 없이 **번역된 줄거리 텍스트만** 출력해."
            )
            # print(f"--- [단일 번역] (줄거리) '{text[:10]}...' ---")
            config = types.GenerateContentConfig(temperature=0.1)
            response = await client.aio.models.generate_content(model=MODEL_NAME, contents=prompt, config=config)
            final_result = response.text.strip().replace('"', '')

        # DB 저장 (공통)
        if final_result:
            try:
                new_trans = Translation(original_text=text, translated_text=final_result)
                db.session.add(new_trans)
                db.session.commit()
                # print("--- [DB 저장 완료] ---")
            except IntegrityError:
                db.session.rollback()
                existing_late = Translation.query.filter_by(original_text=text).first()
                if existing_late: return existing_late.translated_text
            except Exception:
                pass 

        return final_result

    except Exception as e:
        print(f"번역 에러: {e}")
        return text

    # [★핵심 수정] Event loop is closed 에러 방지
    finally:
        if client:
            try:
                # 클라이언트를 명시적으로 닫아서 리소스 정리
                client.close()
            except:
                pass

# [★수정] 래퍼 함수에도 옵션 전달
async def translate_title_to_korean_official(english_title, use_verification=True):
    return await get_verified_translation(english_title, type='title', use_verification=use_verification)

async def translate_general_text(text):
    return await get_verified_translation(text, type='general', use_verification=False) 

async def translate_search_query(query):
    # 검색어 번역은 클라이언트 별도 생성/종료
    client = _create_client_safely()
    if not client: return query
    try:
        MODEL_NAME = 'gemini-3-pro-preview'
        prompt = f"AniList 검색용 영문/로마자 제목으로 변환해(설명X): {query}"
        response = await client.aio.models.generate_content(model=MODEL_NAME, contents=prompt)
        return response.text.strip().replace('"', '')
    except:
        return query
    finally:
        if client:
            try: client.close()
            except: pass