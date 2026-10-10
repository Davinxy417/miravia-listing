"""规范主图白底；只处理与边缘连通的近白区域，不修改封闭高光。"""
from PIL import Image, ImageChops


WHITE_BACKGROUND_VERSION = 1


def normalize_white_background(image, threshold=245):
    im = image.convert('RGB')
    width, height = im.size
    # Every RGB channel must qualify; a bright coloured pixel is not white.
    red, green, blue = im.split()
    mask = ImageChops.darker(ImageChops.darker(red, green), blue).point(
        lambda value: 255 if value >= threshold else 0)
    eligible = bytearray(mask.tobytes())
    connected = bytearray(width * height)
    seeds = [(x, 0) for x in range(width)] + [(x, height - 1) for x in range(width)]
    seeds += [(0, y) for y in range(1, height - 1)] + [(width - 1, y) for y in range(1, height - 1)]
    # Scanline flood fill visits each qualifying pixel once. Four-neighbour
    # connectivity prevents a diagonal highlight from joining the background.
    while seeds:
        x, y = seeds.pop()
        offset = y * width
        if not eligible[offset + x]:
            continue
        left = right = x
        while left > 0 and eligible[offset + left - 1]:
            left -= 1
        while right + 1 < width and eligible[offset + right + 1]:
            right += 1
        span = right - left + 1
        eligible[offset + left:offset + right + 1] = b'\x00' * span
        connected[offset + left:offset + right + 1] = b'\xff' * span
        for neighbour in (y - 1, y + 1):
            if not 0 <= neighbour < height:
                continue
            in_run = False
            for column in range(left, right + 1):
                present = bool(eligible[neighbour * width + column])
                if present and not in_run:
                    seeds.append((column, neighbour))
                in_run = present
    result = im.copy()
    result.paste((255, 255, 255), mask=Image.frombytes('L', im.size, bytes(connected)))
    return result
