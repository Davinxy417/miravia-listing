"""只给模型本图需要的视觉指令；路径、预算、导出规格留在程序。"""
import re


def has_people(scene):
    text = '；'.join(str(v) for v in scene.values()) if isinstance(scene, dict) else str(scene)
    text = re.sub(r'不露脸|不露正脸|不遮人物|无人物遮挡|手柄|扶手椅|手持式', '', text)
    if re.search(r'无人|不出现人物|无人物|不含人物', text):
        return False
    return bool(re.search(r'人物|模特|真人|手|臂|肩|背影|人站|坐|躺|洗澡|淋浴的人|冲洗身体|冲洗头发|宠物主人|脸', text))


def make_prompt(slot, description, variant, qty, entry, mode, scenes=(), zoom=False,
                note='', use_scene='', hero_feature='', references=(), scene_brief=None):
    goals = {
        '01': '生成一张1:1白底电商主图。',
        '02': f'生成一张1:1卖点图，第一眼突出{hero_feature}。' if hero_feature else '生成一张1:1卖点图。',
        '03': f'生成一张1:1部件特写，拍清{hero_feature}。' if hero_feature else '生成一张1:1商品部件特写。',
        '04': '生成一张1:1真实操作近景。', '05': '生成一张1:1生活使用图。',
        '06': '生成一张1:1尺寸说明用无字底图。',
        '07': f"生成一张1:1的{entry.get('layout', '2x2')}四格用途图，细白线分隔。",
        '08': '生成一张1:1生活结果图。',
    }
    roles = '；'.join(f'图{i}{r["use"]}' for i, r in enumerate(references, 1))
    parts = [goals[slot]]
    if roles: parts.append('参考图用途：' + roles + '。')
    parts.append(f'商品：{description}；当前变体{variant}，颜色与结构按当前变体附件。')
    scene = scene_brief or {}
    if slot in ('04', '05', '08'):
        if note:
            # Replace the old scene and camera direction, not a contradictory tail.
            parts.append('本次场景与取景改为：' + note.strip() + '。')
        else:
            labels = {'location': '地点', 'action': '动作', 'connections': '连接', 'visible_result': '结果'}
            parts.extend(f'{label}：{scene[k]}。' for k, label in labels.items() if scene.get(k))
        parts.append('允许必要环境连接，道具不作赠品；接触与作用方向一致。')
    frames = {
        '01': f'纯白#FFFFFF，{qty}件裸商品完整分开可数，居中最长边占80%～85%；轻微侧角、柔和棚拍光与薄接触阴影。去外包装与叠加广告，保留本体印刷。只展示确认随货内容。',
        '02': f'{qty}件完整置于右侧55%版面，最长边约75%，浅底柔和侧光，关键部件清晰；左侧35%纵排线条图标，四周留5%安全边距。',
        '03': '关键部件占60%，保留相邻结构定位；斜侧近摄、柔和侧光、背景微虚，允许局部出画。不虚构不可见内部、剖面或彩色颗粒。',
        '04': '斜侧近景，商品最长边约55%，靠近镜头取景，保持真实尺度与柔和环境光。',
        '05': '中近景，商品完整可辨、最长边35%～50%，保持真实尺度，焦点落在商品和作用处。',
        '06': f'纯白背景，确认随货的{qty}件完整分开可数，正面或垂直俯拍，中央70%构图、四周留15%标注空间。比例按附件，均匀光线、轮廓清楚，保留本体印刷。',
        '07': '每格按实际操作件数展示同款商品，主体约占半格，尺度与接触合理，光线色调统一。',
        '08': '中近景，商品最长边30%～45%，保持真实尺度、关键部件无遮挡，自然柔光，结果清楚。',
    }
    if slot == '07':
        parts.append('四格按左上、右上、左下、右下排列：' if entry.get('layout', '2x2') == '2x2' else '四格按左侧大格、右上、右中、右下排列：')
        if note: parts.append('四格场景改为：' + note.strip() + '。')
        else: parts.extend(f'{i}.{scene_text}。' for i, scene_text in enumerate(scenes, 1))
    if note and slot not in ('04', '05', '07', '08'):
        parts.append('本次构图与外观修正：' + note.strip() + ('；允许局部出画，不画不可见内部或剖面。' if slot == '03' else f'；售卖数量仍为{qty}件。'))
    elif not note:
        parts.append(frames[slot])
    if slot in ('04', '05', '08') and has_people(scene if not note else note):
        parts.append({'04': '只露手和少量手臂，不遮关键部件。',
                      '05': '人物肩以下或背影入镜，不露脸。',
                      '08': '保留素材人物身份和脸，正脸或轻微侧正脸，表情自然。'}[slot])
    if slot == '03':
        macro = next((i for i, ref in enumerate(references, 1) if ref['role'] == 'macro'), None)
        parts.append(f'右下一个白边小放大圈，仅依据图{macro}，不重复整件。' if zoom and macro else '不加放大圈。')
    if slot in ('01', '06') or mode == 'base-overlay':
        parts.append('不新增文字、数字、箭头、图标或emoji。')
    else:
        if entry.get('title'): parts.append(f'顶部深色粗体标题“{entry["title"]}”。')
        if entry.get('subtitle'): parts.append(f'副标题“{entry["subtitle"]}”。')
        if slot == '02' and entry.get('points'):
            parts.append('图标及短语：' + '；'.join(f'{p["icon"]}：“{p["text"]}”' for p in entry.get('points', [])) + '。')
        if slot == '07' and entry.get('scenes'):
            parts.append('各格标签依次：' + '；'.join(f'“{s["title"]}”' for s in entry.get('scenes', [])) + '。')
        parts.append('西语逐字照抄，保留重音大小写；大字放留白，避开商品和人物，不重复、不加其他字、认证标志或emoji。')
    return '\n'.join(parts)
