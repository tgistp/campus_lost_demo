"""Normalisation and contradiction safeguards used by the local AI model.

This is deliberately a bounded demo matcher, not a claim of general language
understanding. Conflicting facts, negation and uncertain answers stay pending.
"""
import re
import unicodedata
from decimal import Decimal

GROUPS = {
 "location": {
  "inside":["안쪽","내부","안감","속부분","속쪽","안에","속에"], "outside":["바깥쪽","외부","겉면","바깥","겉쪽"],
  "front":["앞면","전면","앞쪽"],"back":["뒷면","뒤쪽","후면"],"left":["왼쪽","좌측"],"right":["오른쪽","우측"],
  "top":["위쪽","상단"],"bottom":["아래쪽","하단","밑부분","바닥"],"side":["옆면","측면"]},
 "motif": {
  "star":["별표","별모양","별무늬","별문양","별","star"],"heart":["하트","심장모양","heart"],
  "circle":["동그라미","동그란","원형","동그라","circle"],"triangle":["삼각형","세모","triangle"],
  "square":["사각형","네모","square"],"moon":["초승달","달모양","달문양","달"],"cross":["십자가","십자모양"],
  "flower":["꽃모양","꽃무늬","플라워","꽃"],"cat":["고양이","야옹이","냥이","cat"],
  "dog":["강아지","멍멍이","개모양","개그림","dog"],"rabbit":["토끼","래빗","rabbit"],
  "bear":["곰돌이","곰모양","곰그림","bear"],"duck":["오리","duck"],"dinosaur":["공룡","dinosaur"]},
 "color": {
  "black":["검은색","검정색","검정","검은","까만색","까만","블랙","black"],
  "white":["하얀색","흰색","화이트","하양","하얀","white"],"blue":["파란색","파랑","파란","청색","남색","네이비","블루","navy","blue"],
  "red":["빨간색","빨강색","빨강","빨간","붉은색","붉은","적색","레드","red"],
  "green":["초록색","초록","녹색","그린","green"],"yellow":["노란색","노랑","노란","황색","옐로","yellow"],
  "gray":["회색","회색빛","그레이","grey","gray"],"pink":["분홍색","분홍","핑크색","핑크","pink"],
  "purple":["보라색","보라","자주색","퍼플","purple"],"orange":["주황색","주황","오렌지색","orange"],
  "brown":["갈색","밤색","브라운","brown"],"beige":["베이지색","베이지","아이보리","beige"],
  "gold":["금색","골드","gold"],"silver":["은색","실버","silver"],"mint":["민트색","민트","mint"]},
 "material": {
  "leather":["가죽재질","가죽소재","레더","가죽","leather"],"cotton":["면소재","면재질","순면","코튼","면","cotton"],
  "silicone":["실리콘","실리콘재질","silicone"],"metal":["스테인리스","스텐","금속","메탈","metal"],
  "wood":["나무재질","나무","목재","우드","wood"],"plastic":["플라스틱","plastic"],
  "denim":["데님","청재질","청소재","denim"],"wool":["양모","모직","울소재","wool"]},
 "mark": {"sticker":["스티커","스티카","sticker"],"engraving":["각인","새겨진","새겨져","새긴","음각"],
          "embroidery":["자수","수놓은"],"writing":["손글씨","손으로쓴","볼펜글씨"]},
 "brand": {"nike":["나이키","nike"],"adidas":["아디다스","adidas"],"samsung":["삼성","갤럭시","samsung","galaxy"],
           "apple":["애플","apple"],"logitech":["로지텍","logitech"],"starbucks":["스타벅스","starbucks"],"pnu":["부산대학교","부산대","pnu"]}
}
UNCERTAIN=re.compile(r"모르|모름|기억안|확실하지|아마|혹은|또는|거나|인지")
NEGATION=re.compile(r"없|아니|아닌|아님|아닙|않")
MODIFIERS=re.compile(r"아주|매우|약간|조금|진한|짙은|어두운|연한|옅은|밝은|작은|조그만|커다란|큰|천연|귀여운|예쁜")
FILLERS=re.compile(r"데모확인특징|그려져있습니다|그려져있어요|그려져있어|그려져있음|적혀있습니다|적혀있어요|적혀있음|쓰여있어요|써있어요|써있음|붙어있어요|붙어있습니다|붙어있음|붙어있는|달려있어요|달려있습니다|달려있음|부착되어|부착된|붙어|붙인|달려|있습니다|있어요|있어|있음|입니다|이에요|이예요|예요|에요|모양|문양|무늬|표시|그림|마크|특징|색깔|색상|재질|소재|같아요|적혀|그려진|그려져|쓰여진|써진|해요")
OBJECTS=["지갑","케이스","이어폰","우산","손잡이","라벨","태그","후드","지퍼","카드","가방","학생증","텀블러","노트북","충전기","파우치","옷"]
IDENTITY=re.compile(r"이름|성명|이니셜|문구|글자|영문|알파벳|번호|숫자|시리얼")
NUMERIC=re.compile(r"숫자|번호|몇\s*(?:번|개|장|쌍|자루|켤레)")

NATIVE_ONES={"한":1,"하나":1,"두":2,"둘":2,"세":3,"셋":3,"네":4,"넷":4,
             "다섯":5,"여섯":6,"일곱":7,"여덟":8,"아홉":9}
NATIVE_TENS={"열":10,"스물":20,"스무":20,"서른":30,"마흔":40,"쉰":50,
             "예순":60,"일흔":70,"여든":80,"아흔":90}
_native_words=set(NATIVE_ONES)|set(NATIVE_TENS)|{a+b for a in NATIVE_TENS for b in NATIVE_ONES}
_native_pattern="|".join(re.escape(word) for word in sorted(_native_words,key=len,reverse=True))
_number_pattern=r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
_count_pattern=re.compile(r"("+_number_pattern+"|"+_native_pattern+r"|[영공일이삼사오육칠팔구십백천]+)\s*(켤레|자루|개|장|쌍|번)")


def numeric_text(text):
    value=unicodedata.normalize("NFKC",str(text)).casefold()
    # Thousands separators may be removed; decimal points and signs must survive.
    return re.sub(r"(?<!\d)\d{1,3}(?:,\d{3})+(?!\d)",lambda m:m[0].replace(",",""),value)


def number_value(text):
    if re.fullmatch(_number_pattern,text):return Decimal(text)
    value=korean_number(text)
    return Decimal(value) if value.isdigit() else None


def literal_number(text,question):
    if not NUMERIC.search(question):return None
    value=re.sub(r"\s+","",numeric_text(text)).rstrip(".!?")
    value=re.sub(r"^(?:숫자|번호)(?:은|는|이|가)?","",value)
    value=FILLERS.sub("",value)
    value=re.sub(r"(?:이라고|라고|이요|요)$","",value)
    unit=re.search(r"몇\s*(켤레|자루|개|장|쌍|번)",question)
    allowed=unit[1] if unit else "번"
    value=re.sub(re.escape(allowed)+r"$","",value)
    return number_value(value)


def number_signature(text,question=""):
    literal=literal_number(text,question)
    if literal is not None:return ("literal",literal)
    value=numeric_text(text)
    counts=[]
    def extract(match):
        number=number_value(match[1])
        if number is not None:counts.append((match[2],number))
        return " "*len(match[0])
    remaining=_count_pattern.sub(extract,value)
    plain=tuple(Decimal(m[0]) for m in re.finditer(_number_pattern,remaining))
    return (tuple(counts),plain)


def normalized_counts(text):
    def replace(match):
        value=number_value(match[1])
        return format(value.normalize(),"f")+match[2] if value is not None else match[0]
    return _count_pattern.sub(replace,numeric_text(text))


def state_facts(text):
    """Keep factual polarity separate from embedding similarity."""
    value=compact(text)
    states={}
    def put(key,sign):
        states.setdefault(key,set()).add(sign)
    # Prefer the negative form over the affirmative substring it contains.
    for key,negative,positive in (
        ("closure",r"(?:안|못)닫|닫\w{0,3}지(?:않|못)|닫을수없",r"닫"),
        ("opening",r"(?:안|못)열|열\w{0,3}지(?:않|못)|열수없",r"열려|열리|열린|열어|열림|열었"),
        ("attachment",r"떨어|떼어|떼었|떼짐|떼진|탈락|분리|(?:안|못)붙|붙\w{0,3}지않|(?:안|못)달려|달려있지않",
                      r"붙|달려|부착|부착됨"),
        ("function",r"정상(?:이)?아니|정상아님|정상이아님|고장|망가|파손|부서|불량|작동(?:이)?안|작동하지않|(?:안|못)작동|충전(?:이)?안|충전되지않",
                    r"정상|잘작동|작동잘|문제없|고장없|고장나지않"),
    ):
        # '고장 없음' describes a working item, despite containing '고장'.
        if key=="function" and re.search(r"고장(?:이)?없|고장나지않|문제없",value):
            put(key,1)
        elif key=="attachment" and re.search(r"(?:안|못)떨어|떨어\w{0,3}지않|분리되지않|떼지않",value):
            put(key,1)
        elif re.search(negative,value):put(key,-1)
        elif re.search(positive,value):put(key,1)
    for key in ("closure","opening"):
        if key in states:
            states.setdefault("function",set()).update(states[key])
    # A physical state is a separate fact from whether the mechanism works.
    if states.get("closure")=={1}:put("position",-1)
    if states.get("opening")=={1}:put("position",1)
    return states


def contradicts(expected,supplied,question=""):
    want,got=state_facts(expected),state_facts(supplied)
    shared=want.keys() & got.keys()
    if any(want[key]!=got[key] for key in shared):return True
    if any(len(states.get("position",set()))>1 for states in (want,got)):return True
    # These negations are already represented by their predicate's state above.
    # Keep negation elsewhere (e.g. a missing mark) even when another state agrees.
    def has_negation(text):
        value=compact(text)
        value=re.sub(r"고장(?:이)?없|고장나지않|문제없|정상(?:이)?아니|정상(?:이)?아님", "", value)
        value=re.sub(r"(?:닫|열|붙|달려|작동|충전|떨어|분리|떼)\w{0,4}지(?:않|못)|닫을수없|열수없", "", value)
        value=re.sub(r"(?:안|못)(?:닫|열|되|돼|붙|달려|작동|충전|떨어)", "", value)
        return bool(NEGATION.search(value) or re.search(r"(?:안|못)(?:보이|잠|움직|켜|꺼)",value))
    if has_negation(expected)!=has_negation(supplied):return True
    return number_signature(expected,question)!=number_signature(supplied,question)


def compact(text):
    return re.sub(r"[^가-힣a-z0-9]","",unicodedata.normalize("NFKC",str(text)).casefold())


def korean_number(text):
    native={"하나":"1","한개":"1","둘":"2","두개":"2","셋":"3","세개":"3","넷":"4","네개":"4","다섯":"5","여섯":"6","일곱":"7","여덟":"8","아홉":"9","열":"10","스물":"20"}
    if text in native:return native[text]
    if text in NATIVE_ONES:return str(NATIVE_ONES[text])
    for prefix,amount in NATIVE_TENS.items():
        if text==prefix:return str(amount)
        if text.startswith(prefix) and text[len(prefix):] in NATIVE_ONES:
            return str(amount+NATIVE_ONES[text[len(prefix):]])
    if not text or not re.fullmatch(r"[영공일이삼사오육칠팔구십백천]+",text):return text
    digits={c:i for i,c in enumerate("영일이삼사오육칠팔구")};digits["공"]=0
    if not any(u in text for u in "십백천"):
        return "".join(str(digits[c]) for c in text)
    total=current=0
    for c in text:
        if c in digits:current=digits[c]
        else:total+=(current or 1)*{"십":10,"백":100,"천":1000}[c];current=0
    return str(total+current)


def facts(text,question=""):
    literal=literal_number(text,question)
    if literal is not None:
        return {group:set() for group in GROUPS},format(literal.normalize(),"f")
    identity=bool(IDENTITY.search(question))
    value=compact(text if identity else normalized_counts(text)).replace("별표시","별")
    if identity:
        value=re.sub(r"^(?:이름|성명|이니셜|문구|글자|영문|알파벳|번호|숫자)(?:은|는|이|가)?","",value)
    if not identity:value=MODIFIERS.sub("",value)
    found={group:set() for group in GROUPS}
    lookup={}
    for group,concepts in GROUPS.items():
        if identity and group=="brand":continue
        for token,words in concepts.items():
            for word in words:lookup[word]=(group,token)
    regex="|".join(re.escape(w) for w in sorted(lookup,key=len,reverse=True))
    def extract(match):
        group,token=lookup[match.group()];found[group].add(token);return "|"
    value=re.sub(regex,extract,value)
    value=FILLERS.sub("",value)
    for noun in OBJECTS:
        if noun in compact(question):value=value.replace(noun,"")
    # Strip grammar at a fact boundary or the end of a literal, not internal letters.
    parts=[]
    for part in value.split("|"):
        numeric=korean_number(re.sub(r"(?:번|개)$","",part)) if NUMERIC.search(question) else ""
        if numeric.isdigit():
            parts.append(numeric);continue
        if identity:
            part=re.sub(r"(?:이라고|라고)$","",part)
        else:
            part=re.sub(r"^(?:에는|에서|에|의|은|는|이|가|을|를|로)+","",part)
            part=re.sub(r"(?:이라고|라고|으로|이에|이고|이요|요|은|는|이|가|을|를|에)$","",part)
        parts.append(part)
    rest="".join(parts)
    if not identity:
        # Keep literal names/numbers intact while accepting e.g. sky vs sky photo.
        rest=re.sub(r"(?:사진|이미지)$","",rest)
    if NUMERIC.search(question):rest=korean_number(re.sub(r"(?:번|개)$","",rest))
    return found,rest



def answers_match(expected,supplied,question=""):
    from semantic_ai import judge_answer
    return judge_answer(expected,supplied,question)["passed"]
