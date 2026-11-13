"""从用户上传的 PDF 提取文本，原文件只在内存中处理。"""

from io import BytesIO


class ResumeFileError(Exception):
    pass


def extract_pdf(content):
    if not content.startswith(b"%PDF-"):
        raise ResumeFileError("文件内容不是有效的 PDF。")
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ResumeFileError("请先运行 python -m pip install -r requirements.txt 安装 PDF 解析依赖。") from None
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise ResumeFileError("请先解除 PDF 密码保护，再上传。")
        if not 1 <= len(reader.pages) <= 10:
            raise ResumeFileError("简历 PDF 需为 1–10 页。")
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
            if sum(len(part) for part in parts) > 12000:
                raise ResumeFileError("PDF 正文超过 12,000 字符，请精简后上传。")
        text = "\n".join(parts).strip()
        if len(text) < 20:
            raise ResumeFileError("未提取到足够文字。扫描件或图片型 PDF 请先进行 OCR，或直接粘贴正文。")
        return {"text": text, "pages": len(reader.pages)}
    except ResumeFileError:
        raise
    except Exception:
        raise ResumeFileError("无法解析该 PDF，请重新导出为文字型 PDF 后重试。") from None
