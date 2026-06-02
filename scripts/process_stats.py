import os
import re
import sys
import csv


def read_csv_blocks(path, encoding='gbk'):
    """读取CSV文件，按空行/标题分割成数据块"""
    with open(path, 'r', encoding=encoding) as f:
        reader = csv.reader(f)
        rows = list(reader)
    blocks = []
    current = []
    for row in rows:
        if all(cell.strip() == '' for cell in row):
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(row)
    if current:
        blocks.append(current)
    return blocks


def parse_block_v1(block):
    """解析文件1的一个数据块（可能包含多个子段）"""
    # 按子标题分割block: 行中的col0为空且col1不为空 → 子标题
    sub_blocks = []
    cur = []
    for row in block:
        is_title = (not row[0].strip()) and (len(row) > 1 and row[1].strip()) and not any(
            cell.strip() in ('金额', '户数', '期初(万元)', '期末(万元)', '增减(万元)', '类别', '指标', '25.9') or
            re.match(r'\d', cell.strip())
            for cell in row[1:3]
        )
        # 第一行永远是标题
        if is_title and cur:
            sub_blocks.append(cur)
            cur = [row]
        else:
            cur.append(row)
    if cur:
        sub_blocks.append(cur)

    results = []
    for sub in sub_blocks:
        if len(sub) < 3:
            continue
        title_row = sub[0]
        data_rows = sub[1:]  # 跳过标题行(子段标题行同时也是数据区的标题行)

        title_str = ','.join(cell for cell in title_row if cell.strip())
        yr = re.search(r'(\d{4})', title_str)
        if not yr:
            continue
        year_base = int(yr.group(1))

        sec = title_row[1] if len(title_row) > 1 else ''
        sec = re.sub(r'[（(]\d{2,4}年?[）)].*', '', sec).strip()
        if not sec:
            sec = re.sub(r'[（(]\d{2,4}年?[）)].*', '', title_str).strip()

        # 找到header行（包含"期初"的行），之后的才是数据行
        actual_data = []
        for row in data_rows:
            if any('期初' in (c or '') for c in row):
                continue
            if any('25.9' in (c or '') for c in row):
                continue
            actual_data.append(row)

        for row in actual_data:
            if len(row) < 5:
                continue
            label1 = row[0].strip() if row[0] else ''
            label2 = row[6].strip() if len(row) > 6 and row[6] else ''
            if not label1 and not label2:
                continue

            def to_num(s):
                s = s.strip().replace(',', '').replace('，', '')
                try:
                    return float(s)
                except:
                    return None

            if label1:
                v = [to_num(row[i]) for i in range(1, 5)]
                if None not in v:
                    results.append((sec, year_base, label1, v[0], v[1], v[2], v[3]))
            if label2 and len(row) >= 11:
                v = [to_num(row[i]) for i in range(7, 11)]
                if None not in v:
                    results.append((sec, year_base + 1, label2, v[0], v[1], v[2], v[3]))
    return results


def parse_block_v2(block):
    """解析文件2的一个数据块"""
    if len(block) < 3:
        return []
    title_row = block[0]
    data_rows = block[2:]

    title_str = ','.join(cell for cell in title_row if cell.strip())
    yr = re.search(r'(\d{4})', title_str)
    if not yr:
        return []
    year = int(yr.group(1))

    sec = title_row[1] if len(title_row) > 1 else title_row[0] if title_row else ''
    sec = re.sub(r'\d{4}', '', sec).strip()
    sec = re.sub(r'[（(]\d{2,4}年?[）)].*', '', sec).strip()

    results = []
    for row in data_rows:
        if len(row) < 5:
            continue
        cat1 = row[0].strip() if row[0] else ''
        ind1 = row[1].strip() if len(row) > 1 and row[1] else ''
        cat2 = row[6].strip() if len(row) > 6 and row[6] else ''
        ind2 = row[7].strip() if len(row) > 7 and row[7] else ''
        if not cat1 or not ind1:
            continue

        def to_num(s):
            s = s.strip().replace(',', '').replace('，', '')
            try:
                return float(s)
            except:
                return None

        # 2025: [cat, ind, begin, end, change, empty, ...]
        if cat1 and ind1:
            v = [to_num(row[i]) for i in range(2, 5)]
            if None not in v:
                results.append((sec, year, cat1, ind1, v[0], v[1], v[2]))
        # 2026: [..., empty, cat, ind, begin, end, change]
        if cat2 and ind2 and len(row) >= 11:
            v = [to_num(row[i]) for i in range(8, 11)]
            if None not in v:
                results.append((sec, year + 1, cat2, ind2, v[0], v[1], v[2]))
    return results


def calc_per_capita(file1_data, file2_data):
    """计算人均，返回原始+人均的CSV行"""
    # 建立文件1的人数索引: (section, label, year) -> count
    count_index = {}
    for sec, year, label, count, begin, end, change in file1_data:
        count_index[(sec, label, year)] = count

    def get_count(p_sec, p_cat, p_ind, p_year):
        """找到文件2行对应的人数
        p_cat: 全市/贷款 (文件2行中的类别)
        p_ind: 金额/户数 (文件2行中的指标)
        """
        # p_cat=贷款 → 用文件1贷款段的count
        # p_cat=全市 → 用文件1全市段的count
        if p_cat == '贷款':
            key = ('贷款', p_ind, p_year)
        else:
            key = ('全市', p_ind, p_year)
        if key in count_index:
            return count_index[key]
        # 模糊匹配: 同一年+同指标
        for (s, l, y), c in count_index.items():
            if y == p_year and l == p_ind:
                return c
        return 0

    all_rows = []

    # 文件1: 已有count, 直接算人均
    for sec, year, label, count, begin, end, change in file1_data:
        pc_b = round(begin / count, 6) if count else 0
        pc_e = round(end / count, 6) if count else 0
        pc_c = round(change / count, 6) if count else 0
        all_rows.append({
            'source': '业务统计', 'section': sec, 'year': year,
            'label': label, 'count': count,
            'begin': begin, 'end': end, 'change': change,
            'pc_begin': pc_b, 'pc_end': pc_e, 'pc_change': pc_c,
        })

    # 文件2: 从文件1取人数算人均
    for sec, year, cat, ind, begin, end, change in file2_data:
        cnt = get_count(sec, cat, ind, year)
        pc_b = round(begin / cnt, 6) if cnt else 0
        pc_e = round(end / cnt, 6) if cnt else 0
        pc_c = round(change / cnt, 6) if cnt else 0
        all_rows.append({
            'source': '购买统计', 'section': sec, 'year': year,
            'label': f'{cat}/{ind}', 'count': cnt,
            'begin': begin, 'end': end, 'change': change,
            'pc_begin': pc_b, 'pc_end': pc_e, 'pc_change': pc_c,
        })

    return all_rows


def write_csv(all_rows, output_path):
    """输出到CSV"""
    headers = [
        '数据来源', '分类', '年份', '指标',
        '人数/户数', '期初(万元)', '期末(万元)', '增减(万元)',
        '人均期初', '人均期末', '人均增减'
    ]
    with open(output_path, 'w', encoding='gbk', newline='') as f:
        w = csv.writer(f)
        w.writerow(headers)
        for r in all_rows:
            w.writerow([
                r['source'], r['section'], r['year'], r['label'],
                r['count'],
                round(r['begin'], 2), round(r['end'], 2), round(r['change'], 2),
                r['pc_begin'], r['pc_end'], r['pc_change'],
            ])
    print(f'结果已保存: {output_path}')
    print(f'  共 {len(all_rows)} 行')


def main():
    if len(sys.argv) < 3:
        print('用法: python process_stats.py <业务统计.csv> <购买统计.csv> [输出.csv]')
        sys.exit(1)

    f1, f2 = sys.argv[1], sys.argv[2]
    out = sys.argv[3] if len(sys.argv) >= 4 else '业务数据统计结果.csv'

    for f in [f1, f2]:
        if not os.path.exists(f):
            print(f'文件不存在: {f}')
            sys.exit(1)

    print(f'读取 {f1}')
    blocks1 = read_csv_blocks(f1)
    data1 = []
    for b in blocks1:
        data1.extend(parse_block_v1(b))
    print(f'  解析出 {len(data1)} 条记录')

    print(f'读取 {f2}')
    blocks2 = read_csv_blocks(f2)
    data2 = []
    for b in blocks2:
        data2.extend(parse_block_v2(b))
    print(f'  解析出 {len(data2)} 条记录')

    print('\n--- 文件1 数据 ---')
    for r in data1:
        print(f'  [{r[0]}] {r[1]} {r[2]}: count={r[3]}, 期初={r[4]}, 期末={r[5]}, 增减={r[6]}')

    print('\n--- 文件2 数据 ---')
    for r in data2:
        print(f'  [{r[0]}] {r[1]} {r[2]}/{r[3]}: 期初={r[4]}, 期末={r[5]}, 增减={r[6]}')

    all_rows = calc_per_capita(data1, data2)
    write_csv(all_rows, out)


if __name__ == '__main__':
    main()
