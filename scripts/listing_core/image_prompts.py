"""便携的出图骨架；商品事实和文字只来自当前批次。"""
import json

SLOT_PROMPTS = {
    '01': '白底主图，纯白 #FFFFFF，裸产品完整入镜，视觉居中，占画面约 70–85%，柔和接触阴影。去外部销售包装，保留产品本体标签。不得新增文字、数字、角标。每件可计数。',
    '02': '卖点设计图，浅色干净背景，商品放右下且完整清楚，占画面一半以上。左侧 3–4 个浅色圆底线条图标，配给定的短说明。',
    '03': '新构图的商业摄影细节特写，重新安排近摄镜头、侧光和景深；按真实部件表现材质，不用裁剪放大冒充新照片。zoom=true 才加一个白边圆形放大圈，依据微距参考；其他位置不加。',
    '04': '真实使用场景，只露手和少量手臂，合理操作当前商品。产品与环境一起生成，透视、尺度、光向、接触或安装一致，商品清楚突出。',
    '05': '不同于 04 的使用场景，半身、肩膀以下或背影，不露脸。商品清楚，完整入镜，正常人体比例。',
    '06': '尺寸/内容的无字底图，纯白或极浅纯色背景，正面或完全平铺展开，四周留 15% 标注空间。比例依据已核实数据。不要新增任何文字、数字或尺寸线；数字和箭头一律后续由脚本画。',
    '07': '用途拼图，按给定四个场景顺序做 2×2 或 1+3，细白格线，每格都有清楚的同款商品，每格标签只用给定场景名。',
    '08': '正脸模特场景，自然微笑，正常人体比例。选择好看、自然的西班牙/欧洲居家风真人素材，保留来源人物身份和脸，商品清楚突出。',
}


def make_prompt(slot, description, variant, qty, entry, mode, scenes=(), zoom=False, note='', use_scene='', hero_feature=''):
    text = [entry.get('title', ''), entry.get('subtitle', '')]
    text += [p['text'] for p in entry.get('points', [])]
    text += [s['title'] for s in entry.get('scenes', [])]
    text = [s for s in text if s]
    count = f'每格严格正好 {qty} 件' if slot == '07' else f'画面严格正好 {qty} 件'
    lead = (f'一张独立 1:1 方图。当前商品：{description}。变体：{variant}。'
            f'{count}，型号、颜色、图案、结构按实际附件如实还原，不美化颜色，不过饱和。'
            '外观描述可能是主推款的摘要，当前变体附件及已确认变体值优先，不把其他颜色套到本款。'
            '不画认证标志，不新增参考图里没有的配件。去掉参考图上叠加的中文、价格、水印；'
            '产品自带印刷保留原貌，不重绘假二维码。场景道具不暗示随货赠送。')
    body = SLOT_PROMPTS[slot] + f' 放大圈开关 zoom={str(zoom).lower()}。'
    if hero_feature and slot in ('02', '03'):
        body += f' 这张图的重点：{hero_feature}。要让买家一眼看到这个卖点。'
    if use_scene and slot in ('04', '05', '07', '08'):
        body += (f' 商品真实用法：{use_scene}。场景必须合乎常识：该连的管线连着、该装的地方装着、在该用的位置使用，'
                 '不要把商品拿到不相干的地方摆拍(例如花洒不能离开软管、出现在镜子或洗手台前)。')
    if slot == '02':
        body += ' 图标和对应文字：' + json.dumps(entry.get('points', []), ensure_ascii=False)
    if slot == '07':
        body += f" 布局：{entry.get('layout', '2x2')}。四格场景（空时按实际附上的四张场景底图顺序）：" + json.dumps(scenes, ensure_ascii=False)
    if slot in ('04', '05', '08'):
        body += (' 实际附上 Pexels/Unsplash 真人素材和商品主图；保持人物、脸和房间，'
                 '只自然替换/放入商品；来源记入批次 stock_fotos.csv。无素材时记录限制，不宣称真人实拍。')
    if slot in ('01', '06') or mode == 'base-overlay':
        body += ' 前述图标文字/场景名仅供构图定位与后期脚本使用，本次不画任何新增文字；保留本体真实印刷。'
    else:
        body += (' 图中文字逐字照抄以下 JSON 列表，不得改一个字、重音或数字：'
                 + json.dumps(text, ensure_ascii=False)
                 + '。只用这些文字。标题大号粗体无衬线，占宽约六成；深灰/深蓝高对比字，'
                   '场景文字放顶部半透明白横条，不压人脸和产品。')
    return lead + body + (' 本图补充：' + note if note else '') + ' 最多初次生成加一次修正；逐字校对，失败留问题。导出 1200×1200 sRGB JPG，严格小于 3145728 bytes。'
