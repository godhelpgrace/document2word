"""
Image preprocessor for scanned PDF pages.

Applies denoising, deskewing, and binarization to improve OCR quality.
"""

import cv2
import numpy as np


def preprocess_image(image: np.ndarray) -> np.ndarray:
    """
    Preprocess a scanned page image for OCR.

    Steps:
    1. Convert to grayscale (if color)
    2. Denoise
    3. Deskew (if skew detected)
    4. Adaptive binarization

    Args:
        image: Input image as numpy array (BGR or grayscale)

    Returns:
        Preprocessed image as numpy array
    """
    # 1. Convert to grayscale if needed
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    # 2. Denoise
    denoised = cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)

    # 3. Deskew
    deskewed = _deskew(denoised)

    # 4. Adaptive binarization
    binary = cv2.adaptiveThreshold(
        deskewed,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=11,
        C=2,
    )

    return binary


def _deskew(image: np.ndarray, max_angle: float = 5.0) -> np.ndarray:
    """
    Detect and correct skew in the image.

    Only corrects small angles (< max_angle degrees) to avoid
    over-rotating properly aligned documents.
    """
    # Use Hough transform to detect lines
    edges = cv2.Canny(image, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=100,
        minLineLength=100,
        maxLineGap=10,
    )

    if lines is None or len(lines) == 0:
        return image

    # Calculate angles of detected lines
    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        if x2 - x1 == 0:
            continue
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        # Only consider near-horizontal lines
        if abs(angle) < max_angle:
            angles.append(angle)

    if not angles:
        return image

    # Use median angle for robustness
    median_angle = np.median(angles)

    if abs(median_angle) < 0.5:  # Skip very small corrections
        return image

    # Rotate to correct skew
    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    rotation_matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    rotated = cv2.warpAffine(
        image,
        rotation_matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )

    return rotated
