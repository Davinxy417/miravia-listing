"""Render the bundled Lucide SVG subset with Pillow, without SVG dependencies."""
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw

ICONS = Path(__file__).resolve().parents[2] / "assets/icons"
TOKEN = re.compile(r"[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?")


def arc_points(p, values):
    """SVG endpoint arc to sampled ellipse, including rotation and sweep."""
    rx, ry, angle, large, sweep, x, y = values
    rx, ry = abs(rx), abs(ry)
    if not rx or not ry or p == (x, y):
        return [(x, y)]
    phi = math.radians(angle)
    c, s = math.cos(phi), math.sin(phi)
    dx, dy = (p[0] - x) / 2, (p[1] - y) / 2
    u, v = c * dx + s * dy, -s * dx + c * dy
    ratio = u * u / (rx * rx) + v * v / (ry * ry)
    if ratio > 1:
        rx, ry = rx * math.sqrt(ratio), ry * math.sqrt(ratio)
    numerator = max(0, rx * rx * ry * ry - rx * rx * v * v - ry * ry * u * u)
    denominator = rx * rx * v * v + ry * ry * u * u
    f = math.sqrt(numerator / denominator) if denominator else 0
    if bool(large) == bool(sweep):
        f = -f
    uc, vc = f * rx * v / ry, -f * ry * u / rx
    cx, cy = c * uc - s * vc + (p[0] + x) / 2, s * uc + c * vc + (p[1] + y) / 2
    a = math.atan2((v - vc) / ry, (u - uc) / rx)
    b = math.atan2((-v - vc) / ry, (-u - uc) / rx)
    delta = (b - a) % (2 * math.pi)
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    return [(cx + c * rx * math.cos(a + delta * t / 32) - s * ry * math.sin(a + delta * t / 32),
             cy + s * rx * math.cos(a + delta * t / 32) + c * ry * math.sin(a + delta * t / 32))
            for t in range(1, 33)]


def path_lines(data):
    tokens = TOKEN.findall(data)
    idx, command, current, start = 0, None, (0, 0), (0, 0)
    lines, points, control, previous = [], [], None, ""
    counts = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}
    while idx < len(tokens):
        if tokens[idx].isalpha():
            command = tokens[idx]
            idx += 1
        op = command.upper()
        if op == "Z":
            points.append(start)
            current, control, previous = start, None, op
            if points:
                lines.append(points)
            points = []
            command = None
            continue
        if op not in counts:
            raise ValueError(f"图标含不支持的 SVG 命令 {op}；请换用随项目附带的图标。")
        n = counts[op]
        vals = []
        for field in range(n):
            if idx >= len(tokens):
                raise ValueError("图标 SVG 路径不完整；请恢复 assets/icons 中的原文件。")
            raw = tokens[idx]
            # SVG permits arc flags without separators: '0010' means
            # large=0, sweep=0, x=10; each flag consumes exactly one digit.
            if op == "A" and field in (3, 4):
                if not raw or raw[0] not in "01":
                    raise ValueError("图标圆弧标记无效；请恢复 assets/icons 中的原文件。")
                vals.append(float(raw[0]))
                if len(raw) > 1:
                    tokens[idx] = raw[1:]
                else:
                    idx += 1
            else:
                vals.append(float(raw))
                idx += 1
        relative = command.islower()
        def xy(a, b):
            return (a + current[0], b + current[1]) if relative else (a, b)
        if op in ("M", "L", "T"):
            end = xy(*vals)
        elif op == "H":
            end = (vals[0] + current[0] if relative else vals[0], current[1])
        elif op == "V":
            end = (current[0], vals[0] + current[1] if relative else vals[0])
        elif op == "A":
            end = xy(*vals[-2:])
        else:
            end = xy(*vals[-2:])
        if op == "M":
            if points:
                lines.append(points)
            points, start = [end], end
            command = "l" if relative else "L"
        else:
            if not points:
                points = [current]
            if op in ("C", "S", "Q", "T"):
                reflected = (2 * current[0] - control[0], 2 * current[1] - control[1]) if control else current
                if op == "C":
                    a, b = xy(*vals[:2]), xy(*vals[2:4])
                elif op == "S":
                    a, b = reflected if previous in ("C", "S") else current, xy(*vals[:2])
                elif op == "Q":
                    a = xy(*vals[:2])
                else:
                    a = reflected if previous in ("Q", "T") else current
                for step in range(1, 25):
                    t, u = step / 24, 1 - step / 24
                    if op in ("C", "S"):
                        point = tuple(u**3 * current[i] + 3*u*u*t*a[i] + 3*u*t*t*b[i] + t**3*end[i] for i in (0, 1))
                    else:
                        point = tuple(u*u*current[i] + 2*u*t*a[i] + t*t*end[i] for i in (0, 1))
                    points.append(point)
                control = b if op in ("C", "S") else a
            elif op == "A":
                points.extend(arc_points(current, vals[:5] + list(end)))
                control = None
            else:
                points.append(end)
                control = None
        current, previous = end, op
        if op == "M":
            control = None
    if points:
        lines.append(points)
    return lines


def icon(name, size, colour, stroke_width=5):
    scale = size * 3 / 24
    canvas = Image.new("RGBA", (size * 3, size * 3))
    draw = ImageDraw.Draw(canvas)
    width = max(1, round(stroke_width * 3))
    def stroke(points):
        pixels = [(round(x * scale), round(y * scale)) for x, y in points]
        if len(pixels) > 1:
            draw.line(pixels, fill=colour, width=width, joint="curve")
            radius = width / 2
            for x, y in (pixels[0], pixels[-1]):
                draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=colour)
    path = ICONS / f"{name}.svg"
    if not path.exists():
        # Original simple line icon for offline operation.
        stroke([(5, 12), (10, 17), (19, 7)])
    else:
        root = ET.parse(path).getroot()
        for el in root:
            kind = el.tag.rsplit("}", 1)[-1]
            if kind == "path":
                for line in path_lines(el.attrib["d"]):
                    stroke(line)
            elif kind in ("circle", "ellipse"):
                cx, cy = float(el.get("cx", 0)), float(el.get("cy", 0))
                rx, ry = float(el.get("rx", el.get("r", 0))), float(el.get("ry", el.get("r", 0)))
                stroke([(cx + rx*math.cos(t*math.pi/32), cy + ry*math.sin(t*math.pi/32)) for t in range(65)])
            elif kind == "rect":
                x, y = float(el.get("x", 0)), float(el.get("y", 0))
                w, h = float(el.get("width", 0)), float(el.get("height", 0))
                radius = float(el.get("rx", 0))*scale
                draw.rounded_rectangle((x*scale,y*scale,(x+w)*scale,(y+h)*scale), radius, outline=colour, width=width)
            elif kind in ("polyline", "polygon"):
                v = list(map(float, re.findall(r"[-\d.]+", el.get("points", ""))))
                pts = list(zip(v[::2], v[1::2]))
                stroke(pts + pts[:1] if kind == "polygon" else pts)
            elif kind == "line":
                stroke([(float(el.get("x1",0)),float(el.get("y1",0))), (float(el.get("x2",0)),float(el.get("y2",0)))])
            else:
                raise ValueError(f"不支持图标元素 {kind}；请换用随项目附带的图标。")
    return canvas.resize((size, size), Image.Resampling.LANCZOS)
