import io
import uuid
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from security import SecurityError


def save_image(upload, data):
    if upload is None:
        return ""
    raw = upload.getvalue()
    if not raw or len(raw) > 5 * 1024 * 1024:
        raise SecurityError("사진은 5MB 이하로 업로드해 주세요.")
    if Path(upload.name).suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise SecurityError("JPG 또는 PNG 사진을 선택해 주세요.")
    if not (raw.startswith(b"\xff\xd8\xff") or raw.startswith(b"\x89PNG\r\n\x1a\n")):
        raise SecurityError("사진 파일 내용을 확인해 주세요.")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in {"JPEG", "PNG"} or im.width * im.height > 16_000_000:
                raise SecurityError("JPG/PNG, 최대 1,600만 화소 사진을 사용해 주세요.")
            im.verify()
        with Image.open(io.BytesIO(raw)) as im:
            im = im.convert("RGB")
            im.thumbnail((1600, 1600))
            folder = Path(data) / "images"
            folder.mkdir(parents=True, exist_ok=True)
            if folder.resolve().parent != Path(data).resolve():
                raise SecurityError("사진 저장 경로를 확인해 주세요.")
            if sum(p.stat().st_size for p in folder.glob("*.jpg")) > 500 * 1024 * 1024:
                raise SecurityError("사진 저장 용량을 확인해 주세요.")
            path = folder / f"{uuid.uuid4().hex}.jpg"
            im.save(path, "JPEG", quality=85)
            return path.relative_to(data).as_posix()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise SecurityError("사진을 처리할 수 없습니다. 다른 JPG/PNG 파일을 사용해 주세요.") from exc
