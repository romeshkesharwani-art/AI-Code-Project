import io
import re
from dataclasses import dataclass

import pymupdf as fitz
from docx import Document


@dataclass(frozen=True)
class SourceSegment:
    text: str
    page_number: int | None
    order: int


@dataclass(frozen=True)
class PolicyTextChunk:
    content: str
    section: str
    page_number: int | None
    chunk_index: int


_HEADING = re.compile(
    r"^\s*(?:section\s+[\w.-]+[:.]?\s+|"
    r"(?:\d+(?:\.\d+)*[\).]?\s+)?"
    r"(coverage|benefits?|deductibles?|exclusions?|claims?|eligibility|"
    r"definitions?|limits?|premium|conditions?|waiting period|"
    r"policy period|cancellation|renewal|liability|property|"
    r"covered services|not covered)\b.*)$",
    re.IGNORECASE,
)


def extract_pdf(data: bytes) -> list[SourceSegment]:
    segments: list[SourceSegment] = []
    with fitz.open(stream=data, filetype="pdf") as document:
        for page_index, page in enumerate(document):
            text = page.get_text("text").strip()
            if text:
                segments.append(
                    SourceSegment(text=text, page_number=page_index + 1, order=page_index)
                )
    return segments


def extract_docx(data: bytes) -> list[SourceSegment]:
    document = Document(io.BytesIO(data))
    blocks: list[tuple[int, str]] = []
    # Preserve body order, including tables interleaved with paragraphs.
    blocks = []
    for order, element in enumerate(document.element.body):
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = _text_content(element)
            if text:
                blocks.append((order, text))
        elif tag == "tbl":
            for row in element.findall(".//{*}tr"):
                cells = [_text_content(cell) for cell in row.findall("./{*}tc")]
                text = " | ".join(cell for cell in cells if cell)
                if text:
                    blocks.append((order, text))
    blocks.sort(key=lambda item: item[0])
    return [
        SourceSegment(text=text, page_number=None, order=index)
        for index, (_, text) in enumerate(blocks)
    ]


def _text_content(element) -> str:
    return " ".join(
        text.strip()
        for node in element.iter()
        if node.tag.rsplit("}", 1)[-1] == "t"
        and (text := node.text)
        and text.strip()
    )


def extract_document(data: bytes, file_type: str) -> list[SourceSegment]:
    if file_type == "pdf":
        return extract_pdf(data)
    if file_type == "docx":
        return extract_docx(data)
    raise ValueError(f"Unsupported policy document type: {file_type}")


def section_aware_chunks(
    segments: list[SourceSegment],
    chunk_size: int = 1400,
    chunk_overlap: int = 180,
) -> list[PolicyTextChunk]:
    if chunk_size < 1 or not 0 <= chunk_overlap < chunk_size:
        raise ValueError("chunk_overlap must be non-negative and less than chunk_size.")

    groups: list[tuple[str, list[SourceSegment]]] = []
    active_section = "General"
    for segment in segments:
        lines = [line.strip() for line in segment.text.splitlines() if line.strip()]
        for line in lines:
            if _HEADING.match(line) and len(line) <= 200:
                active_section = re.sub(r"\s+", " ", line).strip(" :-")
                groups.append((active_section, []))
                continue
            if not groups or groups[-1][0] != active_section:
                groups.append((active_section, []))
            groups[-1][1].append(
                SourceSegment(text=line, page_number=segment.page_number, order=segment.order)
            )

    chunks: list[PolicyTextChunk] = []
    for section, section_segments in groups:
        text = "\n".join(segment.text for segment in section_segments)
        if not text.strip():
            continue
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            if end < len(text):
                boundary = text.rfind(" ", start + chunk_size // 2, end)
                if boundary > start:
                    end = boundary
            content = text[start:end].strip()
            if content:
                chunk_text_start = start
                source_position = 0
                page_number = section_segments[0].page_number if section_segments else None
                for segment in section_segments:
                    segment_start = source_position
                    segment_end = segment_start + len(segment.text)
                    if segment_end >= chunk_text_start:
                        page_number = segment.page_number
                        break
                    source_position = segment_end + 1
                chunks.append(
                    PolicyTextChunk(
                        content=content,
                        section=section[:200],
                        page_number=page_number,
                        chunk_index=len(chunks),
                    )
                )
            if end >= len(text):
                break
            start = max(start + 1, end - chunk_overlap)
    return chunks
