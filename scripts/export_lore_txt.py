# -*- coding: utf-8 -*-
"""把《蛊真人》资料合集 docx 按已校对分级目录导出为多个 TXT。
输出：项目外 gu-zhen-ren-lore-txt/，一级目录=文件夹，二级目录=文件，三级目录=文件内小节。
"""
import re
from pathlib import Path
from app import library

def sanitize(name):
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip(' .')
    return name[:80]

def main():
    data = library.lore_structured()
    out_root = Path(__file__).resolve().parent.parent.parent / 'gu-zhen-ren-lore-txt'
    out_root.mkdir(parents=True, exist_ok=True)
    cur_dir = None
    cur_l1 = 0
    cur_l2 = 0
    fh = None
    count_files = 0
    for para in data['paras']:
        kind = para.get('kind')
        text = str(para.get('text', '')).strip()
        if kind == 'h2':
            level = int(para.get('level', 2))
            if level == 1:
                cur_l1 += 1
                cur_l2 = 0
                cur_dir = out_root / ('%02d-%s' % (cur_l1, sanitize(text)))
                cur_dir.mkdir(parents=True, exist_ok=True)
                if fh:
                    fh.close()
                    fh = None
                index = cur_dir / '00-本目录说明.txt'
                index.write_text('# %s\n\n（本文件由资料合集 docx 按分级目录导出）\n' % text, encoding='utf-8')
            elif level == 2:
                if cur_dir is None:
                    continue
                cur_l2 += 1
                if fh:
                    fh.close()
                fh = (cur_dir / ('%02d-%s.txt' % (cur_l2, sanitize(text)))).open('w', encoding='utf-8')
                fh.write('# %s\n\n' % text)
                count_files += 1
            elif level == 3:
                if fh:
                    fh.write('\n## %s\n\n' % text)
        else:
            if fh and text:
                fh.write(text + '\n')
    if fh:
        fh.close()
    print('exported to', out_root, 'files', count_files)

if __name__ == '__main__':
    main()
