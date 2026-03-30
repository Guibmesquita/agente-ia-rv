import base64
import io
import json
import logging
import tempfile
from datetime import datetime, timezone

import fitz
from openai import OpenAI
from PIL import Image
from sqlalchemy.orm import Session

from core.config import get_settings
from database.models import ContentBlock, MaterialFile, VisualCache

logger = logging.getLogger(__name__)

settings = get_settings()

VISION_PROMPT = (
    "Analise esta página de um relatório gerencial de Fundo de Investimento Imobiliário (FII).\n\n"
    "Identifique se há um gráfico (barras, linhas, pizza, área, comparativo, waterfall, etc.) nesta página.\n\n"
    "Responda em JSON exato:\n"
    '{"has_chart": true/false, "chart_type": "tipo do gráfico", '
    '"chart_position": {"top_pct": 0-100, "bottom_pct": 0-100, "left_pct": 0-100, "right_pct": 0-100}, '
    '"chart_description": "breve descrição do que o gráfico mostra"}\n\n'
    "has_chart: true se esta página contém pelo menos um gráfico visual (não tabela).\n"
    "chart_type: tipo do gráfico (barras, linhas, pizza, área, waterfall, etc.).\n"
    "chart_position: coordenadas aproximadas do gráfico PRINCIPAL em porcentagem da página "
    "(top=0 é o topo da página, bottom=100 é o rodapé). Marque a região que contém APENAS o gráfico, "
    "excluindo cabeçalhos, rodapés, logos, e texto fora do gráfico.\n"
    "chart_description: breve descrição do conteúdo do gráfico.\n"
    "Se houver múltiplos gráficos, localize o MAIOR/mais proeminente.\n"
    "Se não houver gráfico, use chart_position com valores zeros."
)

BBOX_AREA_THRESHOLD = 85.0
RENDER_DPI = 200
CROP_MARGIN_PX = 20


def extract_visual(content_block_id: int, db: Session) -> dict | None:
    cached = db.query(VisualCache).filter(VisualCache.content_block_id == content_block_id).first()
    if cached:
        cached.last_accessed_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"Visual cache hit for block {content_block_id}")
        return {
            "image_bytes": cached.image_data,
            "mime_type": cached.mime_type,
            "used_fallback": cached.used_fallback,
            "bbox": json.loads(cached.bbox) if cached.bbox else None,
            "from_cache": True
        }

    block = db.query(ContentBlock).filter(ContentBlock.id == content_block_id).first()
    if not block:
        logger.warning(f"ContentBlock {content_block_id} not found")
        return None

    if block.block_type != "grafico":
        logger.warning(f"ContentBlock {content_block_id} is not a graphic block (type={block.block_type})")
        return None

    if not block.source_page:
        logger.warning(f"ContentBlock {content_block_id} has no source_page")
        return None

    mat_file = db.query(MaterialFile).filter(MaterialFile.material_id == block.material_id).first()
    if not mat_file or not mat_file.file_data:
        logger.warning(f"No PDF found for material_id={block.material_id}")
        return None

    try:
        image = _render_page(bytes(mat_file.file_data), block.source_page)
    except Exception as e:
        logger.error(f"Failed to render page {block.source_page} for block {content_block_id}: {e}")
        return None

    if image is None:
        logger.warning(f"Page {block.source_page} out of range for block {content_block_id}")
        return None

    try:
        vision_result = _call_vision(image)
    except Exception as e:
        logger.error(f"Vision API call failed for block {content_block_id}: {e}")
        vision_result = None

    used_fallback = False
    bbox = None

    if vision_result and vision_result.get("has_chart"):
        pos = vision_result.get("chart_position", {})
        bbox_area = _calculate_bbox_area(pos)

        if bbox_area < BBOX_AREA_THRESHOLD:
            cropped = _crop_image(image, pos)
            bbox = pos
            logger.info(f"Block {content_block_id}: chart located, bbox_area={bbox_area:.1f}%")
        else:
            cropped = image
            used_fallback = True
            bbox = pos
            logger.info(f"Block {content_block_id}: bbox too large ({bbox_area:.1f}%), using full page")
    else:
        cropped = image
        used_fallback = True
        logger.info(f"Block {content_block_id}: no chart detected, using full page as fallback")

    MAX_IMAGE_SIZE = 2 * 1024 * 1024
    MAX_DIMENSION = 2000

    if cropped.width > MAX_DIMENSION or cropped.height > MAX_DIMENSION:
        cropped.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

    img_buffer = io.BytesIO()
    cropped.save(img_buffer, format="PNG", optimize=True)
    image_bytes = img_buffer.getvalue()

    if len(image_bytes) > MAX_IMAGE_SIZE:
        img_buffer = io.BytesIO()
        cropped.save(img_buffer, format="JPEG", quality=80, optimize=True)
        image_bytes = img_buffer.getvalue()
        mime = "image/jpeg"
    else:
        mime = "image/png"

    cache_entry = VisualCache(
        content_block_id=content_block_id,
        image_data=image_bytes,
        mime_type=mime,
        bbox=json.dumps(bbox) if bbox else None,
        used_fallback=used_fallback
    )
    db.add(cache_entry)
    db.commit()

    logger.info(f"Block {content_block_id}: cached visual ({len(image_bytes)} bytes, fallback={used_fallback})")

    return {
        "image_bytes": image_bytes,
        "mime_type": "image/png",
        "used_fallback": used_fallback,
        "bbox": bbox,
        "from_cache": False
    }


def _render_page(pdf_bytes: bytes, page_num: int) -> Image.Image | None:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        doc = fitz.open(tmp.name)
        if page_num < 1 or page_num > len(doc):
            doc.close()
            return None
        page = doc[page_num - 1]
        zoom = RENDER_DPI / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        doc.close()
        return img


def _call_vision(image: Image.Image) -> dict | None:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", quality=85)
    b64_image = base64.b64encode(buffer.getvalue()).decode("utf-8")

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": VISION_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}", "detail": "high"}}
            ]
        }],
        max_tokens=300,
        temperature=0.0
    )

    result_text = response.choices[0].message.content.strip()
    if "```json" in result_text:
        result_text = result_text.split("```json")[1].split("```")[0].strip()
    elif "```" in result_text:
        result_text = result_text.split("```")[1].split("```")[0].strip()

    return json.loads(result_text)


def _calculate_bbox_area(pos: dict) -> float:
    width_pct = max(0, pos.get("right_pct", 100) - pos.get("left_pct", 0))
    height_pct = max(0, pos.get("bottom_pct", 100) - pos.get("top_pct", 0))
    return (width_pct * height_pct) / 100


def _crop_image(image: Image.Image, pos: dict) -> Image.Image:
    w, h = image.size
    top = max(0, int(h * pos.get("top_pct", 0) / 100) - CROP_MARGIN_PX)
    bottom = min(h, int(h * pos.get("bottom_pct", 100) / 100) + CROP_MARGIN_PX)
    left = max(0, int(w * pos.get("left_pct", 0) / 100) - CROP_MARGIN_PX)
    right = min(w, int(w * pos.get("right_pct", 100) / 100) + CROP_MARGIN_PX)
    return image.crop((left, top, right, bottom))


def get_visual_base64(content_block_id: int, db: Session) -> dict | None:
    result = extract_visual(content_block_id, db)
    if not result:
        return None

    b64 = base64.b64encode(result["image_bytes"]).decode("utf-8")
    return {
        "base64": f"data:{result['mime_type']};base64,{b64}",
        "mime_type": result["mime_type"],
        "used_fallback": result["used_fallback"],
        "from_cache": result["from_cache"],
        "size_bytes": len(result["image_bytes"])
    }
