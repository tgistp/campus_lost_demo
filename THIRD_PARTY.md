# React Bits 시작 화면

## 로컬 AI 모델과 지도 데이터

답변 의미 비교는 [Sentence Transformers multilingual MiniLM](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)의 [Xenova ONNX 변환](https://huggingface.co/Xenova/paraphrase-multilingual-MiniLM-L12-v2)을 사용합니다. Apache-2.0 전문·고정 리비전·파일 SHA-256은 `models/answer-minilm/`에 보관합니다. 모델은 CPU에서 로컬 실행하며 추론 API를 호출하지 않습니다.

지도 건물 도형과 대표 좌표는 OpenStreetMap 데이터에서 산출했습니다. © OpenStreetMap contributors, [ODbL 1.0](https://www.openstreetmap.org/copyright). 도형과 원본 way 링크·이름 대조 출처는 `assets/campus/`에 있습니다.

시작 화면은 [React Bits](https://reactbits.dev)의 [ShapeGrid](https://github.com/DavidHDev/react-bits/tree/main/src/content/Backgrounds/ShapeGrid)와 [SpotlightCard](https://github.com/DavidHDev/react-bits/tree/main/src/content/Components/SpotlightCard)를 사용합니다.

실제 고정 커밋은 `landing/src/vendor/UPSTREAM_COMMIT.txt`에 보관합니다. 원본 소스와 저작권·라이선스 전문은 같은 폴더에 포함했습니다. 원본의 MIT + Commons Clause 조건을 따르며 컴포넌트 팩으로 재판매하는 용도가 아닙니다. 이 앱의 시작 화면에 통합한 형태입니다.

React/React DOM은 `landing/package.json`과 `pnpm-lock.yaml`에 정확한 버전을 기록합니다. 빌드된 `landing/dist`도 포함하므로 사용자 PC에는 Node.js를 설치할 필요가 없습니다. 시작 화면 실행 중 CDN에서 코드나 폰트를 받아오지 않습니다.

로컬 컴포넌트는 부모로부터 받은 Streamlit 렌더 메시지만 처리하고, 허용된 두 문자열만 서버로 전달합니다. 사용자 입력·인증 정보는 이 컴포넌트에 전달하지 않습니다. 애니메이션은 OS의 모션 감소 설정을 존중합니다.
