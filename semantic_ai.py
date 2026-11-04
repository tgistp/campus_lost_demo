"""Local multilingual sentence embeddings with explicit contradiction safeguards."""
import hashlib
import re
import threading
import unicodedata
from pathlib import Path

import numpy as np

MODEL_DIR=Path(__file__).resolve().parent/"models/answer-minilm"
MODEL_HASH="66fc00f5f29afcaff34092e1bdd20008ca3918265a82fb9695a551e510cc4ebc"
TOKENIZER_HASH="b60b6b43406a48bf3638526314f3d232d97058bc93472ff2de930d43686fa441"
THRESHOLD=.80
_MODEL=None
_LOCK=threading.RLock()


class ModelUnavailable(RuntimeError):
    pass


def get_model():
    global _MODEL
    with _LOCK:
        if _MODEL is not None:return _MODEL
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
            weights=MODEL_DIR/"model_quantized.onnx"
            with weights.open("rb") as f:
                if hashlib.file_digest(f,"sha256").hexdigest()!=MODEL_HASH:
                    raise ModelUnavailable("AI 모델 파일의 무결성을 확인할 수 없습니다.")
            with (MODEL_DIR/"tokenizer.json").open("rb") as f:
                if hashlib.file_digest(f,"sha256").hexdigest()!=TOKENIZER_HASH:
                    raise ModelUnavailable("AI 토크나이저 파일의 무결성을 확인할 수 없습니다.")
            tokenizer=Tokenizer.from_file(str(MODEL_DIR/"tokenizer.json"))
            tokenizer.enable_truncation(max_length=128)
            tokenizer.enable_padding(pad_id=1,pad_token="<pad>")
            options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
            session=ort.InferenceSession(str(weights),sess_options=options,providers=["CPUExecutionProvider"])
            _MODEL=(tokenizer,session)
        except ModelUnavailable:raise
        except (ImportError,OSError,ValueError,RuntimeError) as exc:
            raise ModelUnavailable("로컬 AI 모델을 준비하지 못했습니다. 라이브러리와 모델 파일을 확인해 주세요.") from exc
        return _MODEL


def embeddings(texts):
    tokenizer,session=get_model()
    with _LOCK:
        encoded=tokenizer.encode_batch(texts)
        values={"input_ids":np.asarray([x.ids for x in encoded],dtype=np.int64),
                "attention_mask":np.asarray([x.attention_mask for x in encoded],dtype=np.int64),
                "token_type_ids":np.asarray([x.type_ids for x in encoded],dtype=np.int64)}
        output=session.run(None,{x.name:values[x.name] for x in session.get_inputs()})[0]
    if output.ndim==3:
        mask=values["attention_mask"][...,None].astype(np.float32)
        output=(output*mask).sum(axis=1)/np.maximum(mask.sum(axis=1),1)
    output=output.astype(np.float32)
    return output/np.maximum(np.linalg.norm(output,axis=1,keepdims=True),1e-9)


def judge_answer(expected,supplied,question=""):
    from verification import compact,facts,contradicts,UNCERTAIN,MODIFIERS,FILLERS,IDENTITY,NUMERIC
    result={"passed":False,"score":None,"threshold":THRESHOLD,"engine":"local-minilm-onnx","reason":"답변을 확인해 주세요."}
    if not expected.strip() or not supplied.strip() or len(supplied)>1000:return result
    if UNCERTAIN.search(compact(supplied)):
        result["reason"]="확실한 답변 한 가지를 입력해 주세요.";return result
    alternatives=[v.strip() for v in re.split(r"[|;\n]",expected) if v.strip()][:5]
    eligible=[]
    got,got_rest=facts(supplied,question)
    for answer in alternatives:
        want,want_rest=facts(answer,question)
        if contradicts(answer,supplied,question):continue
        if any(required and got[g] and required!=got[g] for g,required in want.items()):continue
        if any(len(got[g])>1 and len(want[g])<=1 for g in want):continue
        # Similar spellings must not authenticate a different number or person.
        if IDENTITY.search(question) and want_rest!=got_rest:continue
        eligible.append(answer)
    if not eligible:
        result["reason"]="답변에 서로 다른 특징이나 부정 표현이 있어 확인되지 않았습니다.";return result
    def clean(text):
        if IDENTITY.search(question) or NUMERIC.search(question):
            _,literal=facts(text,question)
            if literal:return literal
        value=unicodedata.normalize("NFKC",text).casefold()
        value=MODIFIERS.sub("",value)
        value=FILLERS.sub("",value)
        return re.sub(r"\s+"," ",value).strip() or text
    # Normalise common aliases as an additional model input, not an allow-list:
    # unfamiliar free text is still judged by the raw sentence embeddings above.
    def canonical(text):
        concepts,rest=facts(text,question)
        korean={"inside":"안쪽","outside":"바깥쪽","star":"별","heart":"하트","moon":"달","circle":"동그라미",
                "cat":"고양이","dog":"강아지","rabbit":"토끼","red":"빨강","blue":"파랑","black":"검정",
                "white":"흰색","leather":"가죽","cotton":"면","sticker":"스티커","engraving":"각인"}
        words=[korean.get(t,t) for g in concepts.values() for t in sorted(g)]
        return " ".join(words+[rest]).strip() or clean(text)
    texts=[supplied,clean(supplied),canonical(supplied)]
    for answer in eligible:texts.extend([answer,clean(answer),canonical(answer)])
    vectors=embeddings(texts)
    scores=[float(np.dot(vectors[j],vectors[i+j])) for i in range(3,len(texts),3) for j in range(3)]
    score=max(0.,min(1.,max(scores)))
    result.update(passed=score>=THRESHOLD,score=score,
                  reason="AI가 같은 의미의 답변으로 판단했습니다." if score>=THRESHOLD else "AI 의미 유사도가 통과 기준보다 낮습니다.")
    return result
