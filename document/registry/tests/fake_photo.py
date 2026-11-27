"""가상 등기부 PDF를 휴대폰 사진·스캔본처럼 만든다 (테스트·시연용). 실제 등기부는 쓰지 않는다.

사용: python document/registry/tests/fake_photo.py 입력.pdf 출력폴더 [--angle 2] [--noise 12] [--blur 0.8]
쪽마다 <이름>_p1.jpg ... 를 만들고, 같은 그림을 한 PDF(글자 층 없음)로도 묶는다.
"""

from __future__ import annotations

import argparse
import io
import os


def photoify(image, *, angle: float = 2.0, noise: int = 12, blur: float = 0.8, seed: int = 0):
    """기울이고, 흐리게 하고, 점 노이즈와 약간 누런 종이색을 넣는다."""
    import numpy as np
    from PIL import Image, ImageFilter

    rng = np.random.default_rng(seed)
    img = image.convert("RGB")
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    if angle:
        img = img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(235, 232, 225))
    a = np.asarray(img).astype(np.int16)
    a = a * np.array([0.97, 0.96, 0.92])  # 종이색
    if noise:
        a = a + rng.normal(0, noise, a.shape)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def pdf_to_photos(pdf_source, **kw) -> list:
    import pdfplumber

    with pdfplumber.open(pdf_source) as pdf:
        pages = [p.to_image(resolution=216).original for p in pdf.pages]
    return [photoify(p, seed=i, **kw) for i, p in enumerate(pages)]


def images_to_pdf(images) -> bytes:
    """그림만 든 PDF (글자 층 없음) = 스캔본."""
    buf = io.BytesIO()
    images[0].save(buf, format="PDF", save_all=True, append_images=images[1:], resolution=216)
    return buf.getvalue()


def to_jpeg(image, quality: int = 80) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("out")
    ap.add_argument("--angle", type=float, default=2.0)
    ap.add_argument("--noise", type=int, default=12)
    ap.add_argument("--blur", type=float, default=0.8)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    name = os.path.splitext(os.path.basename(a.pdf))[0]
    photos = pdf_to_photos(a.pdf, angle=a.angle, noise=a.noise, blur=a.blur)
    for i, p in enumerate(photos, start=1):
        with open(os.path.join(a.out, f"{name}_사진_p{i}.jpg"), "wb") as f:
            f.write(to_jpeg(p))
    with open(os.path.join(a.out, f"{name}_스캔본.pdf"), "wb") as f:
        f.write(images_to_pdf(photos))
    print(f"{len(photos)}쪽 -> {a.out}")


if __name__ == "__main__":
    main()
