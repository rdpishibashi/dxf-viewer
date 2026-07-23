"""矩形領域（直交ポリゴン）検出モジュール

電気回路 DXF 内の閉領域（直交ポリゴン。四角形に限らない）を検出し、領域内
ラベルに領域名を付与する。

識別キー:
  - 図面枠      : lineweight=100 かつ color=7(ACI白) の線分
  - 領域境界線  : lineweight=25 かつ color=2(ACI黄)

このモジュールは DXF-extract-labels プロジェクトの同名モジュールを DXF-viewer 用に
移植したもの。アルゴリズム本体は流用元と同一で、依存関数（テキスト抽出・図番抽出・
機器符号フィルタ）のみ自己完結化している。DXF-extract-labels 側にしか無い機能
（領域名称選択UI向けの `default_name_tier`・`regions_overlap`・行き止まり枝の
handle解決報告）は、DXF-viewer に対応するUIが無いため未移植。逆に DXF-viewer 側
にしか無い機能（Search Boundary 用の `_label_position_for_candidate` 等、大規模
図面向けの `_filter_eligible_labels`/`block_has_relevant_content` 性能最適化）もある。

モジュール内の構成（処理パイプラインの順）:
  1. 移植元の依存関数（自己完結化）
  2. 設定（DEFAULT_REGION_CONFIG）
  3. DXFジオメトリ収集（_collect_region_geometry 系）
  4. ポリゴン・点の幾何ユーティリティ（汎用、複数セクションから使われる）
  5. 線分処理の共通ユーティリティ（分類・クラスタリング・結合）
  6. 図面枠検出（detect_drawing_frames）
  7. 閉領域検出（半面探索・行き止まり枝、_detect_regions まで）
  8. 領域名称候補（Tier付き優先順位、region_name_candidates）
  9. ラベル座標逆引き（Search Boundary のハイライト用）
  10. 図面回転判定（90°回転対応）
  11. タイトルブロック除外
  12. トップレベル解析（公開API: analyze_dxf_regions, assign_region_labels）
"""
import math
import gc
import re
from collections import defaultdict

import ezdxf

from utils.text_utils import clean_mtext_format_codes, normalize_width


# ============================================================
# 1. 移植元の依存関数（DXF-extract-labels の extract_labels.py / common_utils.py より移植）
# ============================================================

# 図番フォーマット（例: EE6868-500-01C, EE6888-602-01A）
DRAWING_NUMBER_PATTERN = r'[A-Z]{2}\d{4}-\d{3}(?:-\d{2})?[A-Z]'

# 機器符号（回路コンポーネント記号）パターン
_CIRCUIT_SYMBOL_PATTERNS = [
    r'^[A-Za-z]{2,}$',                   # 英文字のみ 2 字以上 (FB, CNCNT)
    r'^[A-Za-z]+\d+$',                   # 英文字+数字 (R10, CN3)
    r'^[A-Za-z]+\d+[A-Za-z]+$',          # 英文字+数字+英文字 (X14A, RMSS2A)
    r'^[A-Za-z]{2,}\([^)]*\)$',          # 英文字のみ+括弧 (FB(), MSS(MOTOR))
    r'^[A-Za-z]+\d+\([^)]*\)$',          # 英文字+数字+括弧 (R10(2.2K))
    r'^[A-Za-z]+\d+[A-Za-z]+\([^)]*\)$',  # 英文字+数字+英文字+括弧 (U23B(DAC))
]


def extract_text_from_entity(entity):
    """TEXT / MTEXT エンティティから (raw, clean, (x, y)) を返す。"""
    try:
        x, y = 0.0, 0.0
        if hasattr(entity.dxf, 'insert'):
            x, y = entity.dxf.insert[0], entity.dxf.insert[1]
        elif hasattr(entity.dxf, 'location'):
            x, y = entity.dxf.location[0], entity.dxf.location[1]

        raw_text = getattr(entity.dxf, 'text', '') or ''
        if not raw_text and entity.dxftype() == 'MTEXT':
            raw_text = getattr(entity, 'text', '') or ''

        if not raw_text:
            return '', '', (x, y)
        if entity.dxftype() == 'MTEXT':
            clean_text = clean_mtext_format_codes(raw_text)
        else:
            clean_text = raw_text.strip()
        return raw_text, clean_text, (x, y)
    except Exception:
        return '', '', (0.0, 0.0)


def extract_drawing_numbers(text):
    """テキストから図番フォーマットに一致する文字列を抽出する。"""
    out = []
    for m in re.findall(DRAWING_NUMBER_PATTERN, text, re.IGNORECASE):
        if m.upper() not in [d.upper() for d in out]:
            out.append(m.upper())
    return out


def filter_non_circuit_symbols(labels):
    """機器符号フォーマットに一致するラベルを (matched, excluded_count) で返す。

    判定は normalize_width()（NFKC）後の文字列で行う。全角の機器符号
    （例 `ＤＯＵＴ４（ＭＯＶＥ）`）はASCII前提のパターンに素通りしてしまうため
    （primary: DXF-extract-labels の同じ修正から移植、2026-07-16）。
    返すラベルは原文のまま（呼び出し元は原文と突き合わせるため）。
    """
    matched = []
    excluded = 0
    for label in labels:
        target = normalize_width(label)
        if any(re.match(p, target) for p in _CIRCUIT_SYMBOL_PATTERNS):
            matched.append(label)
        else:
            excluded += 1
    return matched, excluded


# ============================================================
# 2. 設定
# ============================================================

DEFAULT_REGION_CONFIG = {
    'frame_lineweight': 100,    # 図面枠の線の太さ
    'frame_color': 7,           # 図面枠の色(ACI)。lineweight=100だけでは図面枠以外の
                                # 短い無関係な線分（実例: 色5の小さな線分群）も拾ってしまうため、
                                # 色も合わせて判定する（2026-06-24、サンプル137件で検証）。
    'region_lineweight': 25,    # 領域境界線の太さ
    'region_color': 2,          # 領域境界線の色(ACI)
    'snap': 2.0,                # 軸平行判定・レベルクラスタの許容誤差
    'face_snap': 0.1,           # 矩形を構成する線分同士の接続点(交点)の座標マージン
                                # ※小さく（違う矩形を取り込むリスクを抑える）
    'merge_level_tol': 0.5,     # 共線セグメント結合時のレベル座標(縦=x/横=y)一致許容
                                # ※小さくする（別レベルの線=別矩形を結合しない）
    # ギャップ（隙間）の橋渡し方針：部品ラベルは縦線分だけを途切れさせるため、
    # 縦線分のギャップのみ橋渡しし、横線分のギャップは橋渡ししない（別矩形の取り込み防止）。
    'bridge_vertical_gaps': True,    # 縦線分(同一X)のギャップを橋渡しする
    'bridge_horizontal_gaps': False, # 横線分(同一Y)のギャップは橋渡ししない
    'corner_tol': 0.5,               # 縦線端点と横線端点が一致（コーナー）とみなす許容。
                                     # ギャップ両端にコーナー相手がいれば橋渡ししない。
    'span_level_merge': False,  # 共線結合のレベルを「スパンを構成した線分だけ」の平均で
                                # 算出する（既定はレベルクラスタ全体の平均）。レベル汚染
                                # フォールバック（analyze_dxf_regions 4パス目）が True で使う。
    'area_ratio': 0.05,         # 単独の領域の最小面積（枠面積比、整数%比較。v1.9.0で0.15から変更）
    'group_area_ratio': 0.10,   # 同名複数ピースを合算した場合の最小合計面積（枠面積比）
    'min_face_ratio': 0.005,    # 個々の閉領域として残す最小面積（枠面積比、ノイズ除去）
    'name_max_dist': 10.0,      # 名称ラベルの境界からの最大距離
    'name_min_dist': 1.0,       # 名称ラベルの境界からの最小距離（線分上=0 を除外）
    'name_min_letters': 3,      # 名称候補に必要な英字数
    'name_exclude_terms': ('NOTE', '☆'),  # 候補から除外する語（含む場合）
    'name_exclude_lowercase': True,  # 英小文字を含むラベルを名称候補から除外
    'exclude_titleblock': True, # 図番枠（タイトルブロック）を領域から除外
    'exclude_circuit_symbols': True,   # 機器符号(候補)を名称候補から除外
    'circuit_symbol_keep_terms': ('RACK',),  # この語を含むラベルは機器符号扱いしない（例 RACK1）
    'exclude_connection_point_regions': True,  # 境界に接続点(円)を持つ領域(配線ループ)を除外
    'connection_point_threshold': 1,    # 境界上の接続点がこの数(個数)以上なら除外
    'connection_point_margin': 0.05,   # 接続点が境界線上とみなす座標距離マージン（primaryと統一、2026-07-16）
}

# 内部定数（マジックナンバーの明示）
_FRAME_MARGIN = 5       # 図面枠フィルタリング時の座標マージン（枠境界に対し ±5 単位で線分を収集）
_MAX_FACE_NODES = 200_000  # 半面探索の暴走ループ防止: 頂点数がこれを超えたら無効とみなす


def _area_ratio_met(area, frame_area, ratio):
    """面積比較を整数%で行う（DXF-extract-labels primary v1.9.0 と同一実装）。

    UI表示（四捨五入）と同じ丸めで面積比を整数化し、設定値（比率、例 0.05）も
    同様に整数%化した上で `>=` 比較する。フロート同士の直接比較だと、表示上
    「5%」に見える領域が僅かな誤差で不採用になる、逆に採用されるといった、
    表示値と採否が食い違う挙動を防ぐ。
    """
    if frame_area <= 0:
        return False
    pct = round(100.0 * area / frame_area)
    ratio_pct = round(ratio * 100)
    return pct >= ratio_pct


# ============================================================
# 3. DXFジオメトリ収集
# ============================================================

def _is_continuous_linetype(e, doc):
    """エンティティの線種が実質的に Continuous（実線）かどうかを判定する
    （DXF-extract-labels から移植）。

    PHANTOM（二点鎖線）等の装飾的な線種は、lineweight/color が境界線条件
    （region_lineweight/region_color）に一致していても、実際の閉領域の壁を
    表すものではない。`linetype='ByLayer'` の場合はレイヤーの既定線種まで
    解決する。
    """
    lt = (getattr(e.dxf, 'linetype', None) or 'BYLAYER').upper()
    if lt == 'BYLAYER':
        layer = doc.layers.get(e.dxf.layer) if doc else None
        lt = (layer.dxf.linetype if layer else 'CONTINUOUS').upper()
    return lt == 'CONTINUOUS'


def _collect_region_geometry(msp, cfg):
    """msp を1回走査し、INSERT も展開して、図面枠線・領域境界線・テキスト・
    接続点（CIRCLE を含むブロックの INSERT 位置）を収集する。"""
    frame_lines = []
    region_lines = []
    label_entities = []
    connection_points = []
    flw = cfg['frame_lineweight']
    fcol = cfg['frame_color']
    rlw = cfg['region_lineweight']
    rcol = cfg['region_color']

    doc = getattr(msp, 'doc', None)
    _circle_block = {}

    def block_has_circle(name):
        if name not in _circle_block:
            has = False
            try:
                blk = doc.blocks.get(name) if doc else None
                if blk is not None:
                    has = any(x.dxftype() == 'CIRCLE' for x in blk)
            except Exception:
                has = False
            _circle_block[name] = has
        return _circle_block[name]

    _relevant_block = {}

    def block_has_relevant_content(name):
        """ブロック定義の直接の子に、このパスで実際に使う種類のエンティティ
        （図面枠/領域境界線になり得る LINE・LWPOLYLINE、または常に収集対象の
        TEXT/MTEXT）が1つでもあるかを判定する（ブロック名単位でキャッシュ）。

        `e.virtual_entities()` はブロック内容全体を複製・変換するため、無関係な
        図形（HATCH・寸法線・ネストINSERT 等）しか持たないブロックの INSERT
        （手描き回路図では極めて多数）に対して呼ぶと無駄なコストが大きい。
        lineweight/color は INSERT の変換（移動・回転・拡大縮小）の影響を受けない
        ブロック定義側の静的な属性なので、変換前のブロック直接の子だけを見れば
        十分（ネストINSERT内の内容は元々このパスでは展開対象外＝既存の挙動と同じ）。
        判定不能な場合は安全側（True=展開する）に倒し、挙動を変えない。
        """
        if name not in _relevant_block:
            has = True
            try:
                blk = doc.blocks.get(name) if doc else None
                if blk is not None:
                    has = False
                    for x in blk:
                        xt = x.dxftype()
                        if xt in ('TEXT', 'MTEXT'):
                            has = True
                            break
                        if xt == 'LINE':
                            lw = getattr(x.dxf, 'lineweight', None)
                            col = getattr(x.dxf, 'color', None)
                            if (lw == flw and col == fcol) or (lw == rlw and col == rcol):
                                has = True
                                break
                        elif xt == 'LWPOLYLINE':
                            lw = getattr(x.dxf, 'lineweight', None)
                            if lw == rlw and getattr(x.dxf, 'color', None) == rcol:
                                has = True
                                break
            except Exception:
                has = True
            _relevant_block[name] = has
        return _relevant_block[name]

    def handle_line(e):
        lw = getattr(e.dxf, 'lineweight', None)
        col = getattr(e.dxf, 'color', None)
        if lw == flw and col == fcol:
            frame_lines.append((e.dxf.start, e.dxf.end))
        elif (lw == rlw and col == rcol
              and _is_continuous_linetype(e, doc)):
            region_lines.append((e.dxf.start, e.dxf.end))

    region_lines_lp = []  # LWPOLYLINE 由来の境界線（LINE と分離して収集）

    def handle_lwpolyline_lp(e):
        """LWPOLYLINE の辺を LINE 相当として収集する（別リストへ）。"""
        lw = getattr(e.dxf, 'lineweight', None)
        if (lw != rlw or getattr(e.dxf, 'color', None) != rcol
                or not _is_continuous_linetype(e, doc)):
            return
        try:
            pts = list(e.get_points())  # (x, y, bulge, start_width, end_width)
        except Exception:
            return
        n = len(pts)
        if n < 2:
            return
        close_range = n if e.closed else n - 1
        for i in range(close_range):
            p0 = pts[i]
            p1 = pts[(i + 1) % n]
            if abs(p0[2]) > 1e-6:
                continue
            region_lines_lp.append(((p0[0], p0[1]), (p1[0], p1[1])))

    for e in msp:
        t = e.dxftype()
        if t == 'LINE':
            handle_line(e)
        elif t == 'LWPOLYLINE':
            handle_lwpolyline_lp(e)
        elif t in ('TEXT', 'MTEXT'):
            label_entities.append(e)
        elif t == 'INSERT':
            if block_has_circle(e.dxf.name):
                ins = e.dxf.insert
                connection_points.append((ins[0], ins[1]))
            if not block_has_relevant_content(e.dxf.name):
                continue
            try:
                for v in e.virtual_entities():
                    vt = v.dxftype()
                    if vt == 'LINE':
                        handle_line(v)
                    elif vt == 'LWPOLYLINE':
                        handle_lwpolyline_lp(v)
                    elif vt in ('TEXT', 'MTEXT'):
                        label_entities.append(v)
            except Exception:
                pass
    return frame_lines, region_lines, region_lines_lp, label_entities, connection_points


# ============================================================
# 4. ポリゴン・点の幾何ユーティリティ（汎用）
# ============================================================

def _polygon_area(poly):
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _polygon_corners(poly, tol=0.5):
    """ポリゴンの角（直角に折れる頂点）だけを抽出し、左下から順に並べて返す。

    面探索由来の共線中間点を除去し、最も左下（最小y→最小x）の角を先頭にする。
    """
    n = len(poly)
    out = []
    for i in range(n):
        p0 = poly[(i - 1) % n]
        p1 = poly[i]
        p2 = poly[(i + 1) % n]
        cross = (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p1[1] - p0[1]) * (p2[0] - p0[0])
        if abs(cross) > tol:   # 折れ点（共線でない）→ 角
            out.append((round(p1[0], 2), round(p1[1], 2)))
    if not out:
        out = [(round(x, 2), round(y, 2)) for (x, y) in poly]
    start = min(range(len(out)), key=lambda i: (out[i][1], out[i][0]))
    return out[start:] + out[:start]


def _point_in_polygon(pt, poly, boundary_eps=1e-4):
    """ラベルが領域境界線ちょうど（浮動小数点誤差の範囲内）にある場合は内側扱いにする。

    手描き図面の座標は完全一致しないため、名称ラベル・機器符号が領域境界と
    ほぼ同一座標に配置されることがある。素の ray casting は境界上の点を
    浮動小数点誤差（1e-7オーダー）次第で内外どちらにも倒すため、同じ図面
    フォーマットの2図面で片方は境界のわずか内側・もう片方はわずか外側という
    座標になり、後者だけラベルが領域から漏れる不具合が実データで発生した
    （DXF-extract-labels 側で2026-07-23発見・移植。CNPG01 が
    EE6491-039-21A.dxf で領域無しになる report）。
    """
    if _dist_point_to_polygon(pt, poly) <= boundary_eps:
        return True
    x, y = pt
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _dist_point_to_polygon(pt, poly):
    x, y = pt
    best = float('inf')
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        denom = dx * dx + dy * dy
        t = 0.0 if denom == 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / denom))
        px, py = x1 + t * dx, y1 + t * dy
        best = min(best, math.hypot(x - px, y - py))
    return best


def _count_connection_points_on_boundary(polygon, points, margin):
    """ポリゴン境界から margin 以内にある接続点の数を返す（bbox で事前絞り込み）。"""
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    x0, x1 = min(xs) - margin - 1, max(xs) + margin + 1
    y0, y1 = min(ys) - margin - 1, max(ys) + margin + 1
    n = 0
    for (px, py) in points:
        if x0 <= px <= x1 and y0 <= py <= y1:
            if _dist_point_to_polygon((px, py), polygon) <= margin:
                n += 1
    return n


def _polygon_sample_points(poly):
    """ポリゴンの頂点＋各辺の中点を返す（重なり判定のサンプル点）。"""
    pts = list(poly)
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        pts.append(((x1 + x2) / 2.0, (y1 + y2) / 2.0))
    return pts


def _polygon_has_point_strictly_inside(pts, poly, tol):
    """pts のいずれかが poly の内部に（境界から tol より離れて）あるか。"""
    for pt in pts:
        if _point_in_polygon(pt, poly) and _dist_point_to_polygon(pt, poly) > tol:
            return True
    return False


def regions_overlap(poly_a, poly_b, tol=1.0):
    """2つの領域ポリゴンが重なっているか（完全内包・部分重複を含む）。隣接のみは False。"""
    pts_a = _polygon_sample_points(poly_a)
    pts_b = _polygon_sample_points(poly_b)
    return (_polygon_has_point_strictly_inside(pts_a, poly_b, tol)
            or _polygon_has_point_strictly_inside(pts_b, poly_a, tol))


# ============================================================
# 5. 線分処理の共通ユーティリティ（分類・クラスタリング・結合）
# ============================================================

def _split_axis_aligned(pairs, eps):
    """線分(start,end)を水平 H[(y,x0,x1)] と垂直 V[(x,y0,y1)] に分類する。"""
    H = []
    V = []
    for s, en in pairs:
        x1, y1, x2, y2 = s[0], s[1], en[0], en[1]
        if abs(y1 - y2) <= eps and abs(x1 - x2) >= eps:
            H.append(((y1 + y2) / 2.0, min(x1, x2), max(x1, x2)))
        elif abs(x1 - x2) <= eps and abs(y1 - y2) >= eps:
            V.append(((x1 + x2) / 2.0, min(y1, y2), max(y1, y2)))
    return H, V


def _cluster_1d(vals, tol):
    vals = sorted(vals)
    out = []
    cur = [vals[0]]
    for v in vals[1:]:
        if v - cur[-1] <= tol:
            cur.append(v)
        else:
            out.append(sum(cur) / len(cur))
            cur = [v]
    out.append(sum(cur) / len(cur))
    return out


def _gap_has_circle(level, a, b, circles, band):
    """縦線分(level=x)のギャップ [a,b]（y方向）に接続点(円)が乗っているか判定する。"""
    if not circles:
        return False
    for (cx, cy) in circles:
        if abs(cx - level) <= band and a - band <= cy <= b + band:
            return True
    return False


def _has_corner_partner(level, y, h_endpoints, tol):
    """縦線端点 (level, y) に、横線分の端点が一致しているか（＝コーナー相手がいるか）。
    コーナー相手がいる端点は境界がそこで折れるので、ギャップ橋渡ししない。"""
    for (hx, hy) in (h_endpoints or ()):
        if abs(hx - level) <= tol and abs(hy - y) <= tol:
            return True
    return False


def _merge_collinear(items, level_tol, bridge=True, circles=None, circle_band=2.0,
                     h_endpoints=None, corner_tol=0.5, span_levels=False):
    """同一レベル(±level_tol)の共線セグメントを結合する。

    bridge=True のとき隙間（ギャップ）も橋渡しして1本にする（部品で途切れた縦線分の
    復元用）。bridge=False のときは重なり/接触するセグメントのみ結合し、隙間は別スパン
    として残す（横線分。別矩形の取り込みを防ぐ）。

    縦線のギャップ橋渡しは、**ギャップ両端のどちらにも横線分の端点が一致しない**場合
    のみ行う（端点が一致する＝コーナーで境界が折れるステップなので橋渡ししない。これに
    より、別境界片や段差を誤って繋がない）。circles がギャップ上にある場合も橋渡ししない。

    span_levels=True のとき、出力スパンのレベルを「そのスパンを構成した線分だけ」の
    平均で算出する（既定 False はレベルクラスタ全体の平均）。既定の全体平均は、スパンが
    重ならない無関係な近接線分（例: 境界線 y=122.00 の 0.37 上に乗ったコネクタ箱の底辺
    y=122.37）にレベルを汚染され、境界線がシフト → 縦線端点とのノード接続（face_snap）
    が切れて閉領域が不成立になることがある（EE6892-039-05B.dxf 2枠目で実証）。
    `analyze_dxf_regions` のレベル汚染フォールバック（4パス目）が True で再検出する。
    ギャップのコーナー相手・CIRCLE 判定は従来どおりクラスタ全体平均レベルで行う
    （判定許容誤差に対して汚染幅は level_tol 以下なので結果は変わらない）。
    """
    if not items:
        return []
    items = sorted(items, key=lambda t: t[0])
    groups = []
    cur = [items[0]]
    for it in items[1:]:
        if it[0] - cur[-1][0] <= level_tol:
            cur.append(it)
        else:
            groups.append(cur)
            cur = [it]
    groups.append(cur)

    out = []
    for g in groups:
        level = sum(t[0] for t in g) / len(g)
        # merged 要素: [lo, hi, [構成線分のレベル, ...]]
        spans = sorted((t[1], t[2], t[0]) for t in g)
        merged = [[spans[0][0], spans[0][1], [spans[0][2]]]]
        for lo, hi, lv in spans[1:]:
            phi = merged[-1][1]
            if lo <= phi + 1e-6:  # 重なり/接触 → 結合
                merged[-1][1] = max(phi, hi)
                merged[-1][2].append(lv)
            elif (bridge
                  and not _has_corner_partner(level, phi, h_endpoints, corner_tol)
                  and not _has_corner_partner(level, lo, h_endpoints, corner_tol)
                  and not _gap_has_circle(level, phi, lo, circles, circle_band)):
                merged[-1][1] = max(phi, hi)  # 橋渡し（両端コーナー無し・円無し）
                merged[-1][2].append(lv)
            else:
                merged.append([lo, hi, [lv]])  # 隙間 → 別スパンとして分離
        for lo, hi, lvs in merged:
            out.append((sum(lvs) / len(lvs) if span_levels else level, lo, hi))
    return out


# ============================================================
# 6. 図面枠検出
# ============================================================

def detect_drawing_frames(frame_lines, eps=2.0, min_side=0.0):
    """lineweight=100・color=7 の線分（呼び出し元の `_collect_region_geometry` で
    既にこの2条件で絞り込まれている）から図面枠（複数可）を検出する。
    枠の縦長辺が左右ペアで横並びになる前提。戻り値: [(xl,xr,y0,y1), ...]

    注: 枠の縦辺が複数線分に分断されている場合（例: ブロック内で line が分割されて
    いるケース）でも正しく検出できるよう、分類後に共線セグメントを結合してから
    高さ判定を行う。

    `min_side`（既定0=フィルタなし）: 2026-06-24以前は400.0固定で、縦辺の高さが
    これ未満の枠（実例: EE6097-039-06C.dxf、高さ277）を取り落としていた。
    color=7 条件を追加導入したことで、無関係な短い lineweight=100 線分（実例:
    色5の小さな線分群、サンプル137件で確認）が混入しなくなったため、高さに
    よる足切りは不要になった。
    """
    _, V = _split_axis_aligned(frame_lines, eps)
    # 同一 x に複数の線分が分断されている場合（接触・重複）を 1 本に統合してから高さ判定。
    # bridge=False: 隙間は橋渡しせず、接触/重複のみ結合する。
    # 枠縦辺が接触点で 2 分割されているケース（EE6888-631-01A.dxf など）は接触結合で十分。
    # bridge=True にすると無関係なセグメントが橋渡しされ余分なフレームが生じる。
    Vm = _merge_collinear(V, eps, bridge=False)
    tall = [v for v in Vm if (v[2] - v[1]) >= min_side]
    if len(tall) < 2:
        return []
    xedges = _cluster_1d([v[0] for v in tall], eps)
    ys = [v[1] for v in tall] + [v[2] for v in tall]
    y0, y1 = min(ys), max(ys)
    frames = []
    for i in range(0, len(xedges) - 1, 2):
        frames.append((xedges[i], xedges[i + 1], y0, y1))
    return frames


# ============================================================
# 7. 閉領域検出（半面探索・行き止まり枝）
# ============================================================

def _build_planar_graph(Hm, Vm, eps):
    """結合済み水平線 Hm[(y,x0,x1)]・垂直線 Vm[(x,y0,y1)] から、端点接続ベースの
    平面グラフ（隣接リスト adj とノード座標 node_xy）を構築する。

    接続は **線分の端点が相手の線分に乗っている箇所（角・T字）のみ** で作る。
    中ほど同士の交差（どちらの端点でもない交差）では接続しない。これにより、
    コネクタ横線が矩形右辺の途中を横切るだけの箇所で誤って繋がるのを防ぐ。
    座標は許容誤差クラスタリングで正規化する（round の境界で一致点が分裂するのを
    防ぐ。手描きの微小ズレ、例 y=231.91 と 231.96 を同一ノードに寄せる）。

    戻り値: (adj, node_xy)。adj は {node_key: {隣接node_key, ...}} の隣接リスト
    （無向グラフ、双方向に登録）。node_xy は {node_key: (x, y)} の実座標。
    """
    ctol = max(eps, 0.2)

    def _canon_map(values):
        sv = sorted(set(values))
        m = {}
        if not sv:
            return m
        cluster = [sv[0]]
        for v in sv[1:]:
            if v - cluster[-1] <= ctol:
                cluster.append(v)
            else:
                c = sum(cluster) / len(cluster)
                for u in cluster:
                    m[u] = c
                cluster = [v]
        c = sum(cluster) / len(cluster)
        for u in cluster:
            m[u] = c
        return m

    all_x = set()
    all_y = set()
    for (y, x0, x1) in Hm:
        all_y.add(y); all_x.add(x0); all_x.add(x1)
    for (x, y0, y1) in Vm:
        all_x.add(x); all_y.add(y0); all_y.add(y1)
    cx = _canon_map(all_x)
    cy = _canon_map(all_y)

    def cluster_key(x, y):
        return (round(cx[x], 3), round(cy[y], 3))

    v_endpoints = []
    for (x, y0, y1) in Vm:
        v_endpoints.append((x, y0))
        v_endpoints.append((x, y1))
    h_endpoints = []
    for (y, x0, x1) in Hm:
        h_endpoints.append((x0, y))
        h_endpoints.append((x1, y))

    node_xy = {}
    line_pts = {}
    # 横線上のノード = 自身の端点 ＋ そこに端点で接する縦線の位置
    for hi, (y, x0, x1) in enumerate(Hm):
        xs = [x0, x1]
        for (vx, vy) in v_endpoints:
            if x0 - eps <= vx <= x1 + eps and abs(vy - y) <= eps:
                xs.append(vx)
        for x in xs:
            k = cluster_key(x, y)
            node_xy[k] = (x, y)
            line_pts.setdefault(('H', hi), []).append((x, k))
    # 縦線上のノード = 自身の端点 ＋ そこに端点で接する横線の位置
    for vi, (x, y0, y1) in enumerate(Vm):
        ys = [y0, y1]
        for (hx, hy) in h_endpoints:
            if y0 - eps <= hy <= y1 + eps and abs(hx - x) <= eps:
                ys.append(hy)
        for yy in ys:
            k = cluster_key(x, yy)
            node_xy[k] = (x, yy)
            line_pts.setdefault(('V', vi), []).append((yy, k))

    adj = {}
    for pts in line_pts.values():
        pts = sorted(set(pts))
        for a in range(len(pts) - 1):
            ka, kb = pts[a][1], pts[a + 1][1]
            if ka != kb:
                adj.setdefault(ka, set()).add(kb)
                adj.setdefault(kb, set()).add(ka)
    return adj, node_xy


def _peel_dangling_branches(adj, node_xy):
    """次数1のノード（行き止まり）とその辺を再帰的に除去する（2-core抽出）。

    半面探索は次数1のノードに到達すると、戻る辺が1本しかないため必ず同じ辺を
    折り返す。この往復が生のポリゴンに「同じ座標が2回連続する」アーティファクトを
    生む（面積には寄与しないが、頂点座標の表示を汚す）。真の境界閉路は必ず次数2
    以上のノードのみで構成されるため、面探索前にここで除去する。

    `adj` は呼び出し側の辞書を**直接変更**する（除去後のグラフを面探索に渡すため）。

    除去した辺は「枝（連結成分）」単位にまとめて返す。1本の枝が複数の短い線分の
    連なりで構成される場合（部品が複数回切れ目を入れている、あるいは1本の長い
    線が途中まで領域境界として使われ残りが余剰になっている等）も、先端から
    現存グラフへの取り付け点までを1つの枝として扱う（Union-Find で連結成分化）。

    戻り値: [{'edges': [(座標, 座標), ...], 'attachment': 座標 | None}, ...]

    DXF-viewer 側はこの戻り値（行き止まり枝の handle 解決・UI 表示）を消費しない
    （Search Boundary に対応するUIが無いため）が、面探索アルゴリズム本体（2-core
    抽出による頂点重複アーティファクトの除去）は DXF-extract-labels と同一に保つ
    必要があるため、戻り値の計算自体は省略しない。
    """
    peeled_pairs = []  # (leaf_key, other_key)、除去順
    changed = True
    while changed:
        changed = False
        leaves = [n for n, nbrs in adj.items() if len(nbrs) == 1]
        for leaf in leaves:
            nbrs = adj.get(leaf)
            if not nbrs:
                continue
            other = next(iter(nbrs))
            peeled_pairs.append((leaf, other))
            adj[other].discard(leaf)
            if not adj[other]:
                del adj[other]
            del adj[leaf]
            changed = True

    if not peeled_pairs:
        return []

    parent = {}

    def _uf_find(x):
        while parent.get(x, x) != x:
            x = parent[x]
        return x

    def _uf_union(a, b):
        ra, rb = _uf_find(a), _uf_find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b in peeled_pairs:
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        _uf_union(a, b)

    groups = {}
    for a, b in peeled_pairs:
        groups.setdefault(_uf_find(a), []).append((a, b))

    dangling_branches = []
    for edges in groups.values():
        keys = {k for ab in edges for k in ab}
        attach_keys = [k for k in keys if k in adj]
        dangling_branches.append({
            'edges': [(node_xy[a], node_xy[b]) for a, b in edges],
            'attachment': node_xy[attach_keys[0]] if attach_keys else None,
        })
    return dangling_branches


def _trace_faces(adj, node_xy):
    """2-core抽出済みの平面グラフ（adj, node_xy）から、半面探索で閉領域(面)を
    列挙する。各面は次数2以上のノードのみで構成される閉路（半面探索＝各有向辺を
    1回ずつ辿り、各ノードで「来た方向の直前（角度順で1つ前）」の隣接辺へ進む）。"""
    def ang(a, b):
        ax, ay = node_xy[a]
        bx, by = node_xy[b]
        return math.atan2(by - ay, bx - ax)

    order = {n: sorted(nb, key=lambda mm: ang(n, mm)) for n, nb in adj.items()}
    visited = set()
    faces = []
    for u in list(adj.keys()):
        for v in adj[u]:
            if (u, v) in visited:
                continue
            face = []
            cu, cv = u, v
            ok = True
            while True:
                visited.add((cu, cv))
                face.append(node_xy[cu])
                nb = order[cv]
                w = nb[(nb.index(cu) - 1) % len(nb)]
                cu, cv = cv, w
                if (cu, cv) == (u, v):
                    break
                if len(face) > _MAX_FACE_NODES:
                    ok = False
                    break
            if ok and len(face) >= 4:
                faces.append(face)
    return faces


def _find_rectilinear_faces(Hm, Vm, eps):
    """結合済み水平線 Hm[(y,x0,x1)]・垂直線 Vm[(x,y0,y1)] から閉領域(面)と
    行き止まり枝を求める。

    `_build_planar_graph`（平面グラフ構築）→ `_peel_dangling_branches`
    （行き止まり枝の除去・連結成分化）→ `_trace_faces`（半面探索）の3段の
    オーケストレーション。戻り値: (faces, dangling_branches)。
    """
    adj, node_xy = _build_planar_graph(Hm, Vm, eps)
    if not adj:
        return [], []
    dangling_branches = _peel_dangling_branches(adj, node_xy)
    if not adj:
        return [], dangling_branches
    faces = _trace_faces(adj, node_xy)
    return faces, dangling_branches


def _branch_leaf_points(branch, attach_tol=0.5):
    """行き止まり枝(branch)の座標グラフの中で、取り付け点(attachment)以外の
    次数1端点(leaf、枝の"先端")を返す。通常は1点（単純な行き止まり）。

    primary（DXF-extract-labels/utils/region_detector.py）からの移植。"""
    edges = branch.get('edges') or []
    deg = {}
    for (p1, p2) in edges:
        deg[p1] = deg.get(p1, 0) + 1
        deg[p2] = deg.get(p2, 0) + 1
    attachment = branch.get('attachment')
    leaves = []
    for pt, d in deg.items():
        if d != 1:
            continue
        if attachment is not None and math.hypot(pt[0] - attachment[0], pt[1] - attachment[1]) <= attach_tol:
            continue
        leaves.append(pt)
    return leaves


def _resplit_face_with_dangling(face_poly, dangling_branches, Hm, Vm, fsnap, local_tol, margin=2.0):
    """1つの閉領域(face_poly)について、その境界に取り付く行き止まり枝のうち
    「反対側の端点(leaf)も同じ face_poly の境界に近接する」ものがあれば、
    face_poly の bbox 内だけに限定して面探索をやり直し、未接続だった内部の
    仕切り線を復元する。

    グローバルな face_snap やレベル平均化方式には一切触れない——溶接が必要と
    判明した face の bbox 内という限定された範囲でだけ、より緩い許容誤差
    （`local_tol`、merge_level_tol 由来の上限）で再接続を試みる。これにより、
    無関係な遠方の線分同士を誤って結合するリスクを避ける（`EE6888-650-01C.dxf`
    の FL1F①②③、`_merge_collinear` のレベル平均化ドリフトで内部仕切りの
    T字接合が face_snap=0.1 では繋がらず、外周だけの1領域に誤マージされていた
    不具合）。グローバルな face_snap 拡大・レベル平均化方式変更はいずれも無関係な
    別ファイルの誤結合を誘発したため、この局所再トレース方式に切替。

    primary（DXF-extract-labels/utils/region_detector.py）v1.9.1 からの移植
    （2026-07-15）。

    戻り値: sub_faces | None。2面以上に分割できた場合のみ非Noneのリスト
    （元のfaceそのものも含む。合体親候補として後段のN子合体親解消に利用する）。
    """
    attach_tol = max(fsnap, 0.5)
    triggered = False
    for br in dangling_branches:
        att = br.get('attachment')
        if att is None or _dist_point_to_polygon(att, face_poly) > attach_tol:
            continue
        for leaf in _branch_leaf_points(br, attach_tol):
            if _dist_point_to_polygon(leaf, face_poly) <= local_tol:
                triggered = True
                break
        if triggered:
            break
    if not triggered:
        return None

    xs = [p[0] for p in face_poly]
    ys = [p[1] for p in face_poly]
    bx0, bx1 = min(xs) - margin, max(xs) + margin
    by0, by1 = min(ys) - margin, max(ys) + margin
    local_H = [h for h in Hm if by0 <= h[0] <= by1 and h[2] >= bx0 and h[1] <= bx1]
    local_V = [v for v in Vm if bx0 <= v[0] <= bx1 and v[2] >= by0 and v[1] <= by1]
    sub_faces, _sub_dangling = _find_rectilinear_faces(local_H, local_V, local_tol)
    result = [f for f in sub_faces
              if all(bx0 - 1 <= x <= bx1 + 1 for x, _y in f)
              and all(by0 - 1 <= y <= by1 + 1 for _x, y in f)]
    if len(result) <= 1:
        return None
    return result


def _detect_regions(RH, RV, frame, frame_area, cfg, labels=None, circles=None):
    """1つの図面枠内で、面積>=枠面積×area_ratio の閉領域を検出する。"""
    xl, xr, y0, y1 = frame
    m = _FRAME_MARGIN
    Hf = [h for h in RH if y0 - m <= h[0] <= y1 + m and h[2] >= xl - m and h[1] <= xr + m]
    Vf = [v for v in RV if xl - m <= v[0] <= xr + m and v[2] >= y0 - m and v[1] <= y1 + m]
    if not Hf or not Vf:
        return []
    # 共線セグメントの結合はレベル座標を厳密一致(merge_level_tol)で行い、別レベルの
    # 線（=別矩形）を誤って繋がない。ギャップ橋渡しは既定で縦線分のみ（部品ラベルは
    # 縦線分を途切れさせる）。横線分のギャップは既定では橋渡ししない。接続点(交点)判定
    # は face_snap。ギャップが CIRCLE で繋がっている場合は橋渡ししない（配線ループ除外）。
    # 図面全体が90°回転しているファイルでは部品が横線分を途切れさせるため、
    # bridge_horizontal_gaps=True 指定時は縦線分の端点をコーナー相手として
    # （x/y を入れ替えて）同じ安全条件で橋渡しする（_detect_regions を呼ぶ側が
    # 候補ゼロ時のフォールバックとして有効化する）。
    mtol = cfg.get('merge_level_tol', 0.5)
    fsnap = cfg.get('face_snap', 0.1)
    bridge_v = cfg.get('bridge_vertical_gaps', True)
    bridge_h = cfg.get('bridge_horizontal_gaps', False)
    cband = cfg.get('connection_point_margin', 2.0)
    ctol = cfg.get('corner_tol', 0.5)
    fcircles = [c for c in (circles or []) if xl - m <= c[0] <= xr + m and y0 - m <= c[1] <= y1 + m]
    # 横線分の端点（縦ギャップのコーナー相手判定用）
    h_endpoints = []
    for (hy, hx0, hx1) in Hf:
        h_endpoints.append((hx0, hy))
        h_endpoints.append((hx1, hy))
    # 縦線分の端点（横ギャップのコーナー相手判定用。x/y を入れ替えて _has_corner_partner
    # ／_gap_has_circle の (level, 位置) 引数順に合わせる）
    v_endpoints_swapped = []
    for (vx, vy0, vy1) in Vf:
        v_endpoints_swapped.append((vy0, vx))
        v_endpoints_swapped.append((vy1, vx))
    circles_swapped = [(cy, cx) for (cx, cy) in fcircles]
    span_levels = cfg.get('span_level_merge', False)
    Hm = _merge_collinear(Hf, mtol, bridge=bridge_h, circles=circles_swapped, circle_band=cband,
                          h_endpoints=v_endpoints_swapped, corner_tol=ctol,
                          span_levels=span_levels)
    Vm = _merge_collinear(Vf, mtol, bridge=bridge_v, circles=fcircles, circle_band=cband,
                          h_endpoints=h_endpoints, corner_tol=ctol,
                          span_levels=span_levels)
    # 端点接続ベースの面探索（中ほど交差では繋がない）ため、部品矩形の縦線は領域辺の
    # 途中を横切るだけで接続せず、回り込みは発生しない。
    faces, dangling = _find_rectilinear_faces(Hm, Vm, fsnap)
    # 局所修復（primary v1.9.1 からの移植）: 行き止まり枝の反対端点も同じ face の
    # 境界に近接する場合、その face の bbox 内だけに限定して再トレースし、内部仕切り
    # の未接続T字を復元する（`_resplit_face_with_dangling` 参照）。
    local_tol = max(mtol, 0.5)
    expanded_faces = []
    for f in faces:
        sub = _resplit_face_with_dangling(f, dangling, Hm, Vm, fsnap, local_tol)
        if sub:
            expanded_faces.extend(sub)
        else:
            expanded_faces.append(f)
    faces = expanded_faces
    thr = frame_area * cfg.get('min_face_ratio', 0.005)
    regions = []
    seen = set()
    for f in sorted(faces, key=_polygon_area, reverse=True):
        a = _polygon_area(f)
        if a < thr:
            continue
        xs = [p[0] for p in f]
        ys = [p[1] for p in f]
        bb = (round(min(xs)), round(max(xs)), round(min(ys)), round(max(ys)))
        if bb in seen:
            continue
        seen.add(bb)
        regions.append({'polygon': f, 'area': a})
    return regions


# ============================================================
# 8. 領域名称候補（Tier付き優先順位）
# ============================================================

def _is_letter(ch):
    """半角・全角の英字（大小問わず）かどうかを判定する。

    手書き回路DXFには領域名がすべて全角（例: `ＳＹＳＴＥＭ　Ｉ／Ｆ　ＢＯＸ`）で
    書かれている図面があり、ASCII 限定判定では英字0字とみなされ
    `name_min_letters` 条件で常に除外されていた（primary: DXF-extract-labels
    v1.5.24 と同じ修正）。
    """
    if ch.isascii() and ch.isalpha():
        return True
    return 'Ａ' <= ch <= 'Ｚ' or 'ａ' <= ch <= 'ｚ'


def _is_lowercase_letter(ch):
    if 'a' <= ch <= 'z':
        return True
    return 'ａ' <= ch <= 'ｚ'


def _count_letters(s):
    return sum(1 for ch in s if _is_letter(ch))


def _bottom_edges(polygon, level_tol=2.0):
    """ポリゴンの下端（最小y）にある横エッジ群 [(x0,x1,y), ...] を返す。"""
    min_y = min(p[1] for p in polygon)
    segs = []
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if abs(y1 - y2) < 0.5 and abs(y1 - min_y) <= level_tol:
            segs.append((min(x1, x2), max(x1, x2), y1))
    return segs


def _top_edges(polygon, level_tol=2.0):
    """ポリゴンの上端（最大y）にある横エッジ群 [(x0,x1,y), ...] を返す（`_bottom_edges`の上端版）。"""
    max_y = max(p[1] for p in polygon)
    segs = []
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if abs(y1 - y2) < 0.5 and abs(y1 - max_y) <= level_tol:
            segs.append((min(x1, x2), max(x1, x2), y1))
    return segs


def _notch_bottom_edges(polygon, level_tol=2.0, probe=0.5):
    """最下端レベル以外にある下向き横エッジ群 [(x0,x1,y), ...] を返す。

    「下向き」＝エッジ中点の probe 直上が領域内・probe 直下が領域外。
    長方形では常に空（下向きエッジは最下端のみ）で、L字型等の非矩形ポリゴンの
    切り欠き部の横エッジだけが該当する。実例: EE6491-039-04A.dxf の
    SYSTEM I/F BOX。FLAT CABLE 部と一体のL字型領域で、名称ラベルが切り欠き部の
    下向きエッジ（最下端ではない）の直上にあるため、最下端エッジ（Tier1）と
    上端エッジ（Tier2）だけを見る従来の探索では候補から漏れていた。
    `region_name_candidates` が Tier2 スキャンにこのエッジ群を加えて使う。
    （DXF-extract-labels v1.5.27 から移植）
    """
    min_y = min(p[1] for p in polygon)
    segs = []
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if abs(y1 - y2) >= 0.5:
            continue
        my = (y1 + y2) / 2.0
        if abs(my - min_y) <= level_tol:
            continue  # 最下端レベルは Tier1（_bottom_edges）の担当
        x0, x1s = min(x1, x2), max(x1, x2)
        if x1s - x0 < probe:  # 極小エッジは内外判定が不安定なため除外
            continue
        mx = (x0 + x1s) / 2.0
        if (_point_in_polygon((mx, my + probe), polygon)
                and not _point_in_polygon((mx, my - probe), polygon)):
            segs.append((x0, x1s, my))
    return segs


def _vertical_edges_at_extreme(polygon, side, level_tol=2.0):
    """ポリゴンの左端(side='left')または右端(side='right')にある縦エッジ群
    [(y0,y1,x), ...] を返す（図面全体が90°回転している場合の下端/上端の代替）。"""
    xs = [p[0] for p in polygon]
    target_x = min(xs) if side == 'left' else max(xs)
    segs = []
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if abs(x1 - x2) < 0.5 and abs(x1 - target_x) <= level_tol:
            segs.append((min(y1, y2), max(y1, y2), x1))
    return segs


def _dist_to_bottom_edge(pt, bottom_segs):
    """点から下端横エッジ群までの最短距離。"""
    x, y = pt
    best = float('inf')
    for (x0, x1, ey) in bottom_segs:
        if x0 <= x <= x1:
            d = abs(y - ey)
        else:
            d = math.hypot(x - (x0 if x < x0 else x1), y - ey)
        best = min(best, d)
    return best


def _dist_to_vertical_edge(pt, vertical_segs):
    """点から縦エッジ群までの最短距離（_dist_to_bottom_edge の縦版）。"""
    x, y = pt
    best = float('inf')
    for (y0, y1, ex) in vertical_segs:
        if y0 <= y <= y1:
            d = abs(x - ex)
        else:
            d = math.hypot(x - ex, y - (y0 if y < y0 else y1))
        best = min(best, d)
    return best


def _filter_eligible_labels(labels, min_letters, exclude_lowercase, exclude_terms,
                            exclude_circuit_symbols, circuit_keep_terms):
    """`region_name_candidates()` のラベル単位フィルタ（英字数・小文字・除外語・
    機器符号）を適用した (text, x, y) リストを返す。

    このフィルタはポリゴン（個々の領域）に依存せず、同一 cfg・同一ラベル集合
    （1フレーム分の `frame_labels`）であれば結果は常に同じになる。
    `analyze_dxf_regions()` はフレーム内の全領域に対して同じ `frame_labels` を
    使って `region_name_candidates()` を繰り返し呼ぶため、領域ループの外で一度
    だけ計算して `_eligible_labels` として渡すことで、領域数に比例した
    正規表現・文字種判定の再計算を避けられる（大規模図面で全体処理時間の
    半分弱を占めていたボトルネック）。
    """
    terms = [s for s in (exclude_terms or ())]
    keep_terms_upper = [k.upper() for k in (circuit_keep_terms or ())]
    out = []
    for (t, x, y) in labels:
        if _count_letters(t) < min_letters:
            continue
        if exclude_lowercase and any(_is_lowercase_letter(ch) for ch in t):
            continue
        # 除外語・keep-term の照合は半角相当で行う（機器符号フィルタ側も
        # normalize_width で判定するため、全角 ＮＯＴＥ 等が素通りする不整合を
        # 防ぐ。primary: DXF-extract-labels の同じ修正から移植、2026-07-16）。
        up = normalize_width(t).upper()
        # 矩形領域名称の1文字目に "(" が来ることはない（例: 全角 "（ＣＬＯＳＥ）" は
        # 状態表示ラベルであり領域名ではない）。途中に "(" を含む名称
        # （例 "TMP (TMP-1003LM)"）は対象外（v1.9.0、DXF-extract-labels primary から移植）。
        if up.strip().startswith('('):
            continue
        if any(term.upper() in up for term in terms):
            continue
        if exclude_circuit_symbols and not any(k in up for k in keep_terms_upper):
            matched, _ = filter_non_circuit_symbols([t])
            if matched:
                continue
        out.append((t, x, y))
    return out


def region_name_candidates(polygon, labels, max_dist=10.0, min_dist=1.0, min_letters=3,
                           limit=8, exclude_circuit_symbols=True, exclude_terms=('NOTE', '☆'),
                           exclude_lowercase=True, circuit_keep_terms=('RACK',),
                           rotated_edge_roles=None, _eligible_labels=None):
    """領域名候補ラベルを優先順位（Tier）→距離順に返す（テキスト重複除去）。

    優先順位（ユーザー確認による仕様、DXF-extract-labels から移植・2026-06-21 v1.5.9）:
      Tier 1: 矩形領域内にあり、下端横エッジの最近傍（`rotated_edge_roles` 指定時は
              その1番目の側の縦エッジ＝図面回転時の下端相当）
      Tier 2: 矩形領域内にあり、上端横エッジの最近傍（`rotated_edge_roles` 指定時は
              2番目の側の縦エッジ＝上端相当）
      Tier 3: Tier 1/2 のいずれでも候補が見つからない場合のみ、ポリゴン全体の境界
              （任意の辺）への最短距離でフォールバック評価する（領域内外を問わない）。
    各 Tier 内は距離が近い順。Tier1/2 はいずれも `min_dist`未満（境界線分上＝
    部品符号等が偶然乗っただけの無関係なラベル）を除外する。

    Tier1/2 を**領域内側のラベルに限定する**理由（2026-06-21 追加）: 領域名は
    通常その箱の内側に書かれるため、Tier1/2 が想定する「自分の箱の名前」は内側の
    ラベルである。領域の外側にある別の箱・別の注記等のラベルが、たまたま
    Tier1/2 のエッジ（下端/上端、回転時は右端/左端）に近いという理由だけで
    内側の正しいラベルより優先されてしまう不具合があった（`DE5434-553-10B.dxf`
    の回転領域で、領域外の `EFEM UPPER`〈距離3.9〉が領域内の正しい名称
    `CONTROL BOX CORE FX`〈距離5.2〉より優先されていた。Search Boundary の
    マッチングを最上位候補のみで照合するよう変更した際にユーザーが発見）。
    Tier3 のフォールバックは領域内外を問わない（Tier1/2 で候補が無い場合の
    最後の手段のため、範囲を絞らない）。
    条件:
      - 英字 min_letters 字以上
      - exclude_terms のいずれかを含むラベル（例 NOTE, ☆）は除外
      - exclude_lowercase=True のとき英小文字を含むラベルは除外（領域名は大文字）
      - exclude_circuit_symbols=True のとき機器符号（候補）パターン一致は除外

    `_eligible_labels` は `_filter_eligible_labels()` の結果を呼び出し側が
    キャッシュ済みの場合に渡す内部最適化用の引数（省略時はこの関数内で計算する
    ため、外部から呼ぶ場合は省略してよく、結果は変わらない）。

    DXF-extract-labels 版と異なり、`tier_by_text`（採用Tierの辞書）は返さない。
    DXF-viewer には領域名称選択UIが無く、Tier に基づく同期抑制（同UIの機能）に
    対応するものが無いため。
    """
    eligible = _eligible_labels
    if eligible is None:
        eligible = _filter_eligible_labels(
            labels, min_letters, exclude_lowercase, exclude_terms,
            exclude_circuit_symbols, circuit_keep_terms)

    def _scan(edge_segs, dist_fn, require_inside):
        cand = []
        for (t, x, y) in eligible:
            if require_inside and not _point_in_polygon((x, y), polygon):
                continue
            d = dist_fn((x, y), edge_segs)
            if min_dist <= d <= max_dist:
                cand.append((d, t))
        return cand

    if rotated_edge_roles:
        tier1_side, tier2_side = rotated_edge_roles
        tier1_edges = _vertical_edges_at_extreme(polygon, tier1_side)
        tier2_edges = _vertical_edges_at_extreme(polygon, tier2_side)
        dist_fn = _dist_to_vertical_edge
    else:
        tier1_edges = _bottom_edges(polygon)
        # Tier2 は上端エッジに加え、L字型等の切り欠き部の下向きエッジも対象にする
        # （切り欠き直上の名称ラベルを拾う。詳細は _notch_bottom_edges docstring）。
        tier2_edges = _top_edges(polygon) + _notch_bottom_edges(polygon)
        dist_fn = _dist_to_bottom_edge

    tiered = []
    for tier, edges in ((1, tier1_edges), (2, tier2_edges)):
        if not edges:
            continue
        for d, t in _scan(edges, dist_fn, True):
            tiered.append((tier, d, t))

    # Tier1/2 でも候補ゼロの場合のみ、ポリゴン全体の境界への最短距離でフォールバック
    if not tiered:
        for (t, x, y) in eligible:
            d = _dist_point_to_polygon((x, y), polygon)
            if min_dist <= d <= max_dist:
                tiered.append((3, d, t))

    tiered.sort(key=lambda c: (c[0], c[1]))
    seen = set()
    out = []
    for tier, d, t in tiered:
        if t in seen:
            continue
        seen.add(t)
        out.append((round(d, 1), t))
        if len(out) >= limit:
            break
    return out


# ============================================================
# 9. ラベル座標逆引き（Search Boundary のハイライト用、DXF-viewer 独自）
# ============================================================

def _group_labels_by_text(labels):
    """テキスト→座標リスト [(x,y), ...] の辞書を返す（同名ラベルが複数ある場合に対応）。

    `_label_position_for_candidate()` が同名ラベル群から最も近いものを選ぶ際に、
    毎回 `labels` 全体を線形走査しなくて済むよう、1フレーム分の `frame_labels`
    に対して一度だけ構築して再利用する。
    """
    grouped = {}
    for (t, x, y) in labels:
        grouped.setdefault(t, []).append((x, y))
    return grouped


def _label_position_for_candidate(text, polygon, positions_by_text):
    """name_candidates のテキストに対応する元ラベルの座標 (x, y) を返す。

    `region_name_candidates()` はテキストのみ返す（座標を持ち出すと流用元の
    アルゴリズムと出力契約が変わってしまうため）。同じテキストのラベルが複数
    （他領域の同名ラベル等）ある場合は、このポリゴンに最も近いものを採用する。
    DXF-viewer の Search Boundary が、マッチしたラベル本体をハイライトする際に
    実体（TEXT/MTEXT エンティティ）の位置を特定するために使う。

    `positions_by_text` は `_group_labels_by_text()` の戻り値（テキスト→座標
    リスト）。同名ラベルの件数分だけを見れば済むため、全ラベルを毎回走査する
    より高速。
    """
    candidates = positions_by_text.get(text)
    if not candidates:
        return None
    return min(candidates, key=lambda p: _dist_point_to_polygon(p, polygon))


# ============================================================
# 10. 図面回転判定（90°回転対応）
# ============================================================

def _label_rotation_angle(entity):
    """ラベルエンティティの実効回転角(度, 0-180で正規化前)を返す。
    MTEXT は rotation 属性ではなく text_direction ベクトルで回転が表現される
    ことがあるため、そちらを優先する。"""
    if entity.dxftype() == 'MTEXT':
        try:
            if entity.dxf.hasattr('text_direction'):
                td = entity.dxf.get('text_direction')
                return math.degrees(math.atan2(td[1], td[0]))
        except Exception:
            pass
    return getattr(entity.dxf, 'rotation', 0) or 0


def _is_globally_rotated(label_entities, threshold=0.5):
    """ラベル(TEXT/MTEXT)の過半数が90°(または270°)回転しているか判定する。

    図面全体が90°回転して描かれたファイルでは、部品が横線分（本来の縦線分に
    相当）を途切れさせるため、横線分ギャップ橋渡しが必要になる。しかし通常向き
    の図面で「単純に検出ゼロ件だったから」を条件に橋渡しを許可すると、無関係な
    隣接矩形を誤って結合する副作用の恐れがある。そこでラベルの回転状況から
    図面全体の回転を明示的に判定し、回転図面のときのみ橋渡しを許可する。
    通常図面ではラベル回転はほぼ0%（実データで0〜0.2%程度）、回転図面では
    大半（実データで60〜97%）が90°回転していることを確認済み。
    """
    total = 0
    rotated = 0
    for e in label_entities:
        if e.dxftype() not in ('TEXT', 'MTEXT'):
            continue
        total += 1
        ang = _label_rotation_angle(e) % 180.0
        if 80.0 <= ang <= 100.0:
            rotated += 1
    if total == 0:
        return False
    return (rotated / total) >= threshold


def _rotated_edge_roles(label_entities, threshold=0.5):
    """図面全体が90°回転している場合、下端相当/上端相当がどちら側の縦エッジに
    対応するかを判定する（DXF-extract-labels から移植）。

    `_is_globally_rotated` は回転の有無（角度が90°付近かどうか、符号を区別しない
    `% 180`）しか見ないが、名称候補の優先順位（下端相当を優先1位、上端相当を
    優先2位とする）には回転方向の符号（+90° か -90° か）が必要。

    実例で確認済みの対応（`DE5434-553-10B.dxf`、回転角+90°が多数派）:
      下端相当 = 右端の縦エッジ、上端相当 = 左端の縦エッジ
    回転角-90°が多数派の場合は左右が反転する（下端相当=左端、上端相当=右端）。

    戻り値: (tier1_side, tier2_side) のタプル（'left'/'right'）。回転していない、
    または回転方向の多数派が判定できない場合は None。
    """
    total = 0
    near_plus90 = 0
    near_minus90 = 0
    for e in label_entities:
        if e.dxftype() not in ('TEXT', 'MTEXT'):
            continue
        total += 1
        ang = _label_rotation_angle(e)
        ang = ((ang + 180.0) % 360.0) - 180.0  # (-180, 180] に正規化
        if 80.0 <= ang <= 100.0:
            near_plus90 += 1
        elif -100.0 <= ang <= -80.0:
            near_minus90 += 1
    if total == 0:
        return None
    if (near_plus90 / total) >= threshold:
        return ('right', 'left')
    if (near_minus90 / total) >= threshold:
        return ('left', 'right')
    return None


# ============================================================
# 11. タイトルブロック除外
# ============================================================

def _is_titleblock_region(polygon, labels):
    """領域内に図番パターンとタイトル系語が同居していれば図番枠とみなす。"""
    has_dn = False
    has_term = False
    terms = ('TITLE', 'REVISION', 'DWG', '流用元', '図番')
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    for (t, x, y) in labels:
        # 多角形のバウンディングボックス外なら内外判定(_point_in_polygon)自体が
        # 確実に False になるので、安価な範囲チェックで先に大半を弾く。
        if x < x0 or x > x1 or y < y0 or y > y1:
            continue
        if not _point_in_polygon((x, y), polygon):
            continue
        if not has_dn and extract_drawing_numbers(t):
            has_dn = True
        if not has_term:
            up = t.upper()
            if any(k in up or k in t for k in terms):
                has_term = True
        if has_dn and has_term:
            return True
    return False


# ============================================================
# 12. 補完面解消（兄弟矩形の部分共有辺で生じる補完面を分割）
# ============================================================

def _vertex_in_corner_set(vertex, corner_list, tol=1.0):
    """頂点 vertex が corner_list の中に許容誤差 tol 以内で一致する点があるか。"""
    vx, vy = vertex
    return any(abs(vx - px) < tol and abs(vy - py) < tol for px, py in corner_list)


def _detect_complement_pairs(regions, tol=1.0):
    """補完面ペア (large_idx, small_idx) のリストを返す。

    small の全頂点が large の頂点に含まれ、large が more vertices を持ち、かつ
    2 領域が重なるものを「補完面関係」とする。
    """
    n = len(regions)
    corners = [r['corners'] for r in regions]
    results = []
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            ci, cj = corners[i], corners[j]
            if len(ci) <= len(cj):
                continue
            if not all(_vertex_in_corner_set(v, ci, tol) for v in cj):
                continue
            if not regions_overlap(regions[i]['polygon'], regions[j]['polygon']):
                continue
            results.append((i, j))
    return results


def _extract_complement_subpolygons(large_corners, small_corners, tol=1.0):
    """補完面 large の境界を辿り、small に含まれない追加頂点列を切り出してサブ領域を返す。"""
    n = len(large_corners)

    def is_shared(v):
        return _vertex_in_corner_set(v, small_corners, tol)

    flags = [is_shared(v) for v in large_corners]
    subregions = []
    visited_starts = set()
    for i in range(n):
        if flags[i] and not flags[(i + 1) % n]:
            attachment_start = large_corners[i]
            start_idx = (i + 1) % n
            if start_idx in visited_starts:
                continue
            extra_seq = []
            k = start_idx
            while k < n + start_idx:
                cur = large_corners[k % n]
                if is_shared(cur):
                    break
                extra_seq.append(cur)
                k += 1
            if extra_seq:
                visited_starts.add(start_idx)
                subregions.append([attachment_start] + extra_seq)
    return subregions


def _resolve_complement_faces(regions, frame_area, next_id=None):
    """補完面を検出してサブ領域に分割し、補完面を除去した新リストを返す（DXF-viewer 版）。"""
    pairs = _detect_complement_pairs(regions)
    if not pairs:
        return regions

    if next_id is None:
        next_id = max((r['id'] for r in regions), default=-1) + 1

    # 同じ large_i に複数の small_i パートナーが見つかる場合がある——大きい方の
    # 兄弟との補完ペアに加え、area_ratio 引き下げ（v1.9.0）により小さい方の
    # 兄弟自体も独立採用され、同じ large_i の補完パートナーとして二重にマッチ
    # してしまうケース（`EE6313-545-01D.dxf`。primary側で確認・修正）。各 large_i
    # につき面積最大の small_i のみを基準面として差分抽出に使い、それ以外の
    # small_i は「差分抽出で正しい名称のサブ領域として再生成される側の重複」と
    # みなして除去する。
    best_small_for_large = {}
    for large_i, small_i in pairs:
        cur = best_small_for_large.get(large_i)
        if cur is None or regions[small_i]['area'] > regions[cur]['area']:
            best_small_for_large[large_i] = small_i
    redundant_small = {small_i for large_i, small_i in pairs
                       if small_i != best_small_for_large[large_i]}
    pairs = [(large_i, small_i) for large_i, small_i in pairs
             if small_i == best_small_for_large[large_i]]

    to_remove = {large_i for large_i, _ in pairs} | redundant_small
    new_regions = [r for i, r in enumerate(regions) if i not in to_remove]

    for large_i, small_i in pairs:
        comp_face = regions[large_i]
        base_face = regions[small_i]

        claimed = {t for _, t in base_face.get('name_candidates', [])}
        inherited_cands = [(d, t) for d, t in comp_face.get('name_candidates', [])
                           if t not in claimed]
        default_name = inherited_cands[0][1] if inherited_cands else ''

        sub_polys = _extract_complement_subpolygons(comp_face['corners'], base_face['corners'])
        for sub_poly in sub_polys:
            sub_area = _polygon_area(sub_poly)
            new_regions.append({
                'id': next_id,
                'frame': comp_face.get('frame', 0),
                'polygon': sub_poly,
                'corners': _polygon_corners(sub_poly),
                'area': sub_area,
                'area_pct': 100.0 * sub_area / frame_area if frame_area > 0 else 0.0,
                'name_candidates': list(inherited_cands),
                'default_name': default_name,
                'name_candidate_positions': {},
            })
            next_id += 1

    return new_regions


def _detect_union_parents(regions, tol=1.0, area_tol=1.0):
    """結合親領域（union parent）の {親インデックス: (子インデックス, ...)} を返す（DXF-viewer版）。

    子の数は2以上の任意数に対応する（v1.9.1相当、N子一般化。primary
    〈DXF-extract-labels/utils/region_detector.py〉v1.9.1 からの移植、
    2026-07-15。3分割以上の矩形、例 FL1F①②③、を正しく解消するために必要）。

    子候補の絞り込み: 親Pに内包される（regions_overlapかつ面積がPより小さい）
    候補を面積の大きい順に走査し、既に選んだ候補と重ならないものだけを貪欲に
    採用する。面積降順で走査するため、入れ子（正しい兄弟候補がたまたま無関係な
    小さな詳細領域を内部に持つ場合）があっても、外側の正しい兄弟候補が先に
    選ばれ、内側のノイズ候補は「既選択候補と重なる」として自然に除外される。

    検出条件（全て満たす）:
      1. area(P) ≈ Σ area(子)
      2. P の全コーナーが 子群.corners の和集合に含まれる
      3. 各子について regions_overlap(P, 子)
      4. 子同士は互いに重ならない（兄弟、貪欲選択により自動的に満たす）

    戻り値: {parent_idx: (child_idx, ...), ...}
    """
    n = len(regions)
    corners = [r['corners'] for r in regions]
    areas = [r['area'] for r in regions]
    polys = [r['polygon'] for r in regions]
    result = {}

    for i in range(n):
        contained = [j for j in range(n) if j != i
                     and areas[j] < areas[i] - area_tol
                     and regions_overlap(polys[i], polys[j])]
        if len(contained) < 2:
            continue
        contained.sort(key=lambda j: areas[j], reverse=True)
        selected = []
        for j in contained:
            if not any(regions_overlap(polys[j], polys[s]) for s in selected):
                selected.append(j)
        if len(selected) < 2:
            continue
        if abs(areas[i] - sum(areas[j] for j in selected)) > area_tol:
            continue
        child_corner_pool = [c for j in selected for c in corners[j]]
        if not all(_vertex_in_corner_set(v, child_corner_pool, tol) for v in corners[i]):
            continue
        result[i] = tuple(selected)

    return result


def _force_include_union_children(cands_list, frame_area, area_ratio, area_tol=1.0, corner_tol=1.0):
    """面積フィルタ未適用の生候補リスト `cands_list` に対して合体親（union parent）を
    検出し、子側候補のインデックス集合を返す（呼び出し側が面積閾値を問わず採用する
    ために使う。DXF-extract-labels 側 primary と同一実装。詳細はそちら参照）。

    通常の採用判定（単独面積>=閾値、または同名2ピース合算>=10%）は、兄弟矩形が
    互いに異なる名称を持ち、かつどちらも単独で閾値未満の場合に対応できない
    （例: `DE5434-563-03A.dxf` の `SB-1A(FX1)`/`CN I/F B.D TYPE3(CN-IF3-1A)`）。
    `_detect_union_parents` は面積一致・頂点包含・非重複という強い幾何学的根拠で
    合体関係を判定するため、採用フィルタより前（全ての生候補が揃った時点）で
    適用すれば、面積閾値に関わらず両方の子を正しく拾える。

    **合体親自身が単独面積閾値を満たす場合のみ**子をバイパス採用する
    （`frame_area`・`area_ratio` によるゲート、v1.9.0）。ゲートが無いと、単独では
    閾値未満の異名兄弟2つの合体面がたまたま結合されただけの、実体の薄い小さな
    親でも子だけが無条件採用されてしまう（primary側 area_ratio を15%→5%に
    下げたことで顕在化。DXF-extract-labels primary から移植）。
    """
    if len(cands_list) < 3:
        return set()
    enriched = [dict(cf, corners=_polygon_corners(cf['polygon'])) for cf in cands_list]
    parent_to_children = _detect_union_parents(enriched, tol=corner_tol, area_tol=area_tol)
    child_idx = set()
    for i, children in parent_to_children.items():
        if not _area_ratio_met(enriched[i]['area'], frame_area, area_ratio):
            continue
        child_idx.update(children)
    return child_idx


def _is_valid_name_candidate(t, min_letters, exclude_lowercase, exclude_terms,
                              exclude_circuit_symbols, circuit_keep_terms):
    """領域名候補ラベルとして有効かを返す（ポリゴン非依存フィルタ）。

    _name_union_parent で使われる共通判定。
    """
    if _count_letters(t) < min_letters:
        return False
    if exclude_lowercase and any(_is_lowercase_letter(ch) for ch in t):
        return False
    # 除外語・keep-term の照合は半角相当で行う（primary: DXF-extract-labels の
    # 同じ修正から移植、2026-07-16）。
    up = normalize_width(t).upper()
    # 矩形領域名称の1文字目に "(" が来ることはない（v1.9.0、primary から移植）。
    if up.strip().startswith('('):
        return False
    if any(term.upper() in up for term in (exclude_terms or ())):
        return False
    if exclude_circuit_symbols and not any(k.upper() in up for k in (circuit_keep_terms or ())):
        matched, _ = filter_non_circuit_symbols([t])
        if matched:
            return False
    return True


def _name_union_parent(parent_region, child_regions, labels, cfg,
                        exclude_names=None):
    """合体親領域の名称候補を、子領域が未採用のラベルから探索して返す（DXF-viewer版）。

    通常の `region_name_candidates` と異なる点:
      - require_inside を緩和し、領域の外側（底辺の下方向）も探索対象にする
      - 子領域がすでに採用した候補テキストを除外する
      - exclude_names に含まれるテキストを除外する（他の非子領域が使用中の名称）
      - 底辺中央 x 座標への近接度（中心距離）を距離の第2ソートキーにする

    戻り値: (name_candidates, name_candidate_positions) のタプル。
      name_candidates: [(distance, text), ...]
      name_candidate_positions: {text: (x, y)}
    """
    polygon = parent_region['polygon']
    max_dist = cfg.get('name_max_dist', 10.0)
    min_dist = cfg.get('name_min_dist', 1.0)
    min_letters = cfg.get('name_min_letters', 3)
    exclude_terms = cfg.get('name_exclude_terms', ('NOTE', '☆'))
    exclude_lowercase = cfg.get('name_exclude_lowercase', True)
    exclude_circuit_symbols = cfg.get('exclude_circuit_symbols', True)
    circuit_keep_terms = cfg.get('circuit_symbol_keep_terms', ('RACK',))

    # 子領域が採用済みのテキスト + 他の非子領域が使用中の名称 を除外対象として収集
    claimed = set(exclude_names or ())
    for child in child_regions:
        for _, t in child.get('name_candidates', []):
            claimed.add(t)

    # 底辺エッジとその x 全体中央を算出
    bottom = _bottom_edges(polygon)
    if not bottom:
        return [], {}
    all_x0 = min(seg[0] for seg in bottom)
    all_x1 = max(seg[1] for seg in bottom)
    center_x = (all_x0 + all_x1) / 2.0

    # 底辺エッジへの距離（領域外も許容）と中央距離でスコアリング
    scored = []
    for (t, x, y) in labels:
        if not _is_valid_name_candidate(t, min_letters, exclude_lowercase,
                                        exclude_terms, exclude_circuit_symbols,
                                        circuit_keep_terms) or t in claimed:
            continue
        dist = _dist_to_bottom_edge((x, y), bottom)
        if dist < min_dist or dist > max_dist:
            continue
        centrality = abs(x - center_x)
        scored.append((dist, centrality, t, x, y))

    scored.sort(key=lambda c: (c[0], c[1]))
    seen = set()
    out = []
    name_positions = {}
    for dist, _centrality, t, x, y in scored:
        if t in seen:
            continue
        seen.add(t)
        out.append((round(dist, 1), t))
        name_positions[t] = (x, y)
        if len(out) >= 8:
            break
    return out, name_positions


def _resolve_union_parents(regions, labels=None, cfg=None):
    """結合親領域を検出し、名称を再探索した上でリストを返す（DXF-viewer版）。

    子領域が採用済みの名称候補を除外し、底辺中央近接条件を加味して
    合体親固有の名称ラベルを探索する（`_name_union_parent` 参照）。
    未採用ラベルが見つかった場合は親を残して名称を更新する。
    見つからなかった場合は従来通り除去する。
    `labels` が与えられない場合は全ての結合親を除去する（後方互換）。
    """
    parent_to_children = _detect_union_parents(regions)
    if not parent_to_children:
        return regions

    to_remove = set()
    if labels is not None:
        effective_cfg = cfg or {}
        parent_indices = set(parent_to_children.keys())
        child_indices = {c for cs in parent_to_children.values() for c in cs}
        # フレーム別に「既使用名称」を管理（異なるフレームは独立して同名を許可）
        parent_claimed_by_frame = defaultdict(set)
        for parent_idx, child_idxs in parent_to_children.items():
            parent = regions[parent_idx]
            parent_frame = parent.get('frame', 0)
            children = [regions[c] for c in child_idxs]
            # 同一フレーム内の非親・非子領域が使用中の名称を除外対象とする
            same_frame_names = {
                regions[i]['default_name']
                for i in range(len(regions))
                if i not in parent_indices and i not in child_indices
                and regions[i].get('default_name')
                and regions[i].get('frame', 0) == parent_frame
            } | parent_claimed_by_frame[parent_frame]
            new_cands, new_positions = _name_union_parent(
                parent, children, labels, effective_cfg,
                exclude_names=same_frame_names)
            if new_cands:
                # 未採用ラベルが見つかった → 親を残して名称を更新
                parent['name_candidates'] = new_cands
                parent['name_candidate_positions'] = new_positions
                parent['default_name'] = new_cands[0][1]
                parent_claimed_by_frame[parent_frame].add(new_cands[0][1])
            else:
                # 未採用ラベルがない → 従来通り除去
                to_remove.add(parent_idx)
    else:
        to_remove = set(parent_to_children.keys())

    return [r for i, r in enumerate(regions) if i not in to_remove]


# ============================================================
# 13. トップレベル解析（公開API）
# ============================================================

def _run_region_detection(lines, det_cfg, frames, frame_area, frame_labels,
                          connection_points, rotated_edge_roles, labels_by_text):
    """lines から H/V 分類 → 図面枠ごとの候補面リストを返す。`analyze_dxf_regions`
    の3パス検出（LINEのみ→LWPOLYLINE追加→横ギャップ橋渡し）が、それぞれこの
    関数を1回呼んで結果を得る。

    ラベル単位フィルタ（英字数・小文字・除外語・機器符号）は領域に依存せず
    `det_cfg` と `frame_labels` だけで決まるため、領域ループの外で一度だけ
    計算する（領域数に比例した正規表現の再評価を避ける最大のボトルネック対策）。
    """
    RH, RV = _split_axis_aligned(lines, det_cfg['snap'])
    eligible_labels = _filter_eligible_labels(
        frame_labels, det_cfg['name_min_letters'], det_cfg['name_exclude_lowercase'],
        det_cfg['name_exclude_terms'], det_cfg['exclude_circuit_symbols'],
        det_cfg.get('circuit_symbol_keep_terms', ('RACK',)))
    fc = []
    for fi, frame in enumerate(frames):
        cands_list = []
        for reg in _detect_regions(RH, RV, frame, frame_area, det_cfg, frame_labels,
                                   connection_points):
            if det_cfg['exclude_titleblock'] and _is_titleblock_region(reg['polygon'], frame_labels):
                continue
            if det_cfg['exclude_connection_point_regions']:
                cp = _count_connection_points_on_boundary(
                    reg['polygon'], connection_points, det_cfg['connection_point_margin'])
                if cp >= det_cfg['connection_point_threshold']:
                    continue
            ncands = region_name_candidates(
                reg['polygon'], frame_labels,
                max_dist=det_cfg['name_max_dist'], min_dist=det_cfg['name_min_dist'],
                min_letters=det_cfg['name_min_letters'],
                rotated_edge_roles=rotated_edge_roles,
                exclude_circuit_symbols=det_cfg['exclude_circuit_symbols'],
                exclude_terms=det_cfg['name_exclude_terms'],
                exclude_lowercase=det_cfg['name_exclude_lowercase'],
                circuit_keep_terms=det_cfg.get('circuit_symbol_keep_terms', ('RACK',)),
                _eligible_labels=eligible_labels)
            name_positions = {}
            for _d, text in ncands:
                pos = _label_position_for_candidate(text, reg['polygon'], labels_by_text)
                if pos:
                    name_positions[text] = pos
            cands_list.append({
                'polygon': reg['polygon'], 'area': reg['area'],
                'name_candidates': ncands,
                'default_name': ncands[0][1] if ncands else '',
                'name_candidate_positions': name_positions,
            })
        fc.append(cands_list)
    return fc


def _remove_overlap_claimed_candidates(regions):
    """重なる領域同士で、同じ名称候補テキストをより近い側（小さい距離）の領域
    だけに残し、遠い側からは取り除く（`regions_overlap()` が True の領域間のみ）。

    `region_name_candidates()` は領域ごとに独立して評価するため、入れ子/重なる
    2領域（例 `EE6313-546-01E.dxf` の外側`B CHAMBER`・内側`BAKE HEATER UNIT RX`）
    では、内側領域の名称ラベルが外側領域の境界からも Tier1/2 の許容距離内に
    収まり、外側領域の候補リストにも内側領域の名称が残ることがある。内側領域が
    その名称をより高い確信度（小さい距離）で持っている以上、外側領域の default
    がそれになるのは誤り。同じテキストについて、重なる領域の中で最小距離を持つ
    領域だけに候補を残し、他の重なる領域からは除去する。`default_name` も
    除去結果に応じて再計算する。距離が等しい場合はどちらからも除去しない。

    Search Boundary は `default_name` のみ照合するため、この整理が無いと
    L字型領域（EE6491-039-04A.dxf）で、ネストされた HEATER CTRL B.D の名称が
    L字側の default に残り、本来の名称 SYSTEM I/F BOX が検索でヒットしない。
    （DXF-extract-labels v1.5.14 相当から移植。`default_name_tier` を持たない
    DXF-viewer 版に合わせ Tier 再計算は省略）
    """
    n = len(regions)
    original = [r['name_candidates'] for r in regions]  # 比較は変更前のスナップショットで行う
    overlap_cache = {}

    def _overlap(i, j):
        key = (i, j) if i < j else (j, i)
        if key not in overlap_cache:
            overlap_cache[key] = regions_overlap(regions[i]['polygon'], regions[j]['polygon'])
        return overlap_cache[key]

    for i in range(n):
        cands = original[i]
        if not cands:
            continue
        kept = []
        for d, t in cands:
            claimed_by_closer = False
            for j in range(n):
                if j == i or not _overlap(i, j):
                    continue
                if any(t2 == t and d2 < d for d2, t2 in original[j]):
                    claimed_by_closer = True
                    break
            if not claimed_by_closer:
                kept.append((d, t))
        if len(kept) != len(cands):
            regions[i]['name_candidates'] = kept
            regions[i]['default_name'] = kept[0][1] if kept else ''


def analyze_dxf_regions(dxf_file, config=None):
    """DXFファイルを解析し、図面枠・閉領域（名称候補つき）・図面枠内ラベルを返す。

    戻り値 dict:
      frames: [(xl,xr,y0,y1), ...]
      frame_area: float
      labels: [(text, x, y), ...]  （図面枠内のみ）
      regions: [{id, frame, polygon, area, area_pct, name_candidates, default_name,
                 name_candidate_positions}]
      error: str | None
    """
    cfg = dict(DEFAULT_REGION_CONFIG)
    if config:
        cfg.update(config)
    result = {'frames': [], 'frame_area': 0.0, 'labels': [], 'regions': [], 'error': None}
    try:
        doc = ezdxf.readfile(dxf_file)
        msp = doc.modelspace()
        frame_lines, region_lines, region_lines_lp, label_entities, connection_points = \
            _collect_region_geometry(msp, cfg)

        frames = detect_drawing_frames(frame_lines, cfg['snap'])
        result['frames'] = frames
        if not frames:
            # 「何が実施できなかったか」を明確に伝える文言（primary v1.8.3 から移植、2026-07-16）。
            result['error'] = ('図面枠（太さ %d の線で囲まれた枠）が見つからなかったため、'
                               '領域探索を実施することができませんでした。'
                               % cfg['frame_lineweight'])
            # 領域探索自体はできないが、ラベル抽出は図面枠に依存しないため、
            # 枠制約なし・重複除去のみでresult['labels']を埋める
            # （primaryのDXF-extract-labelsから移植、2026-07-23。図面枠が
            # 見つからない図面のラベルが analysis['labels'] 依存の呼び出し元で
            # 丸ごと消える不具合の修正）。
            seen = set()
            fallback_labels = []
            for it in label_entities:
                _, clean_text, (x, y) = extract_text_from_entity(it)
                if not clean_text:
                    continue
                key = (clean_text, round(x, 1), round(y, 1))
                if key in seen:
                    continue
                seen.add(key)
                fallback_labels.append((clean_text, x, y))
            result['labels'] = fallback_labels
            return result
        frame_area = (frames[0][1] - frames[0][0]) * (frames[0][3] - frames[0][2])
        result['frame_area'] = frame_area

        # 図面枠内ラベル（重複除去）
        seen = set()
        frame_labels = []
        for it in label_entities:
            _, clean_text, (x, y) = extract_text_from_entity(it)
            if not clean_text:
                continue
            in_frame = any(xl - 1 <= x <= xr + 1 and y0 - 1 <= y <= y1 + 1
                           for (xl, xr, y0, y1) in frames)
            if not in_frame:
                continue
            key = (clean_text, round(x, 1), round(y, 1))
            if key in seen:
                continue
            seen.add(key)
            frame_labels.append((clean_text, x, y))
        result['labels'] = frame_labels

        area_ratio = cfg['area_ratio']                      # 単独領域の閾値（整数%比較）
        group_ratio = cfg.get('group_area_ratio', 0.10)      # 同名複数ピース合算の閾値（整数%比較）
        # エスカレーション（LWPOLYLINE追加・90°回転橋渡し・レベル汚染フォールバック）の
        # 発動判定は、単独採用閾値(area_ratio)とは独立の gate_ratio を用いる（v1.9.0、
        # primary から移植）。area_ratio の既定値を15%→5%に下げたことで、単独採用には
        # 満たない小さな候補（従来なら「ゼロ件」扱いでエスカレーションが発動していた）が
        # 5%以上というだけでヒット扱いになり、エスカレーションが発動しなくなる副作用が
        # あった。gate_ratio は area_ratio と 0.15（エスカレーション機構が実データで
        # 検証された時点の既定値）の大きい方とする。
        gate_ratio = max(area_ratio, 0.15)
        rotated = _is_globally_rotated(label_entities)
        rotated_edge_roles = _rotated_edge_roles(label_entities) if rotated else None
        # frame_labels はこの後の全パス・全領域で不変なので、テキスト→座標の逆引き
        # 辞書は一度だけ構築して再利用する（_label_position_for_candidate 用）。
        labels_by_text = _group_labels_by_text(frame_labels)

        # 1) LINE のみで領域検出を試みる
        lines_for_detection = region_lines
        frame_cands = _run_region_detection(
            lines_for_detection, cfg, frames, frame_area, frame_labels,
            connection_points, rotated_edge_roles, labels_by_text)

        def _zero_hit_frame_indices(cands, ratio):
            return [fi for fi, cl in enumerate(cands)
                    if not any(_area_ratio_met(cf['area'], frame_area, ratio) for cf in cl)]

        def _bbox_key(cf):
            xs = [p[0] for p in cf['polygon']]
            ys = [p[1] for p in cf['polygon']]
            return (round(min(xs)), round(max(xs)), round(min(ys)), round(max(ys)))

        def _merge_cands_lists(base_list, extra_list):
            """base_list を優先しつつ、extra_list にのみ存在する候補(bbox基準)を
            追加する（置き換えではなく合算。v1.9.0、primary から移植）。"""
            seen = {_bbox_key(cf) for cf in base_list}
            merged = list(base_list)
            for cf in extra_list:
                k = _bbox_key(cf)
                if k not in seen:
                    seen.add(k)
                    merged.append(cf)
            return merged

        # LINE だけで閾値超え候補がゼロだった図面枠に限り、LWPOLYLINE を追加して
        # 再検出する（例: EE6888-631-01A.dxf など境界が LWPOLYLINE で描かれた図面
        # への対応）。判定・再検出とも図面枠単位（zero_fis のみ）で行う——ファイル
        # 全体で1件でも候補があれば以降のパスを丸ごとスキップする実装だと、同じ
        # ファイル内の「別の図面枠がたまたま先に見つかる」だけで、本来
        # LWPOLYLINE/回転対応が必要な図面枠が永久に救済されないバグがあった
        # （`DE5434-553-10B.dxf` の `CONTROL BOX CORE FX`/`RX` で確認。area_ratio を
        # 10%→15% に変えるだけで検出有無が反転するという閾値依存の非単調な挙動が
        # 発覚の手がかりだった。DXF-extract-labels v1.7.11 から移植）。
        # LINE でも十分な候補がある図面枠には LWPOLYLINE を追加しない
        # （小部品の LWPOLYLINE が境界線の corner-partner 判定を誤らせるため）。
        # このゲートは gate_ratio で判定し（v1.9.0）、採用は「置き換え」ではなく
        # 「合算」（`_merge_cands_lists`）で行う——LWPOLYLINE追加は corner-partner
        # 判定を乱し、LINE-onlyで既に正しく検出できていた候補を壊れた別の候補に
        # 化けさせて消してしまうことがあるため（primary の `SYSTEM I/F BOX **` で
        # 確認）。
        zero_fis = _zero_hit_frame_indices(frame_cands, gate_ratio)
        if zero_fis and region_lines_lp:
            lines_for_detection = region_lines + region_lines_lp
            sub_frames = [frames[fi] for fi in zero_fis]
            fc2 = _run_region_detection(
                lines_for_detection, cfg, sub_frames, frame_area, frame_labels,
                connection_points, rotated_edge_roles, labels_by_text)
            for j, fi in enumerate(zero_fis):
                frame_cands[fi] = _merge_cands_lists(frame_cands[fi], fc2[j])

        # それでも閾値超え候補がゼロだった図面枠に限り、かつラベルの過半数が90°回転
        # している（=図面全体が90°回転して描かれている）場合のみ、横線分のギャップ
        # 橋渡しを有効にして再検出する（安全条件＝縦線分の端点とのコーナー一致無し・
        # CIRCLE無し、は橋渡し縦線分と同じ）。判定・再検出とも図面枠単位（zero_fis の
        # み）で行う理由は上記 LWPOLYLINE パスと同じ（1ファイル内の一部の図面枠だけが
        # 回転コンテンツを持つケースを取りこぼさない）。
        # 回転判定（`rotated`）はファイル全体のラベル集計に基づく既存の判定のまま
        # 維持する——通常向きの図面枠で「単に検出ゼロ件だったから」をトリガーに横線分
        # も橋渡ししてしまうと、無関係な隣接矩形を誤って結合する副作用があるため
        # （`_is_globally_rotated` 参照）。
        det_cfg = cfg
        zero_fis = _zero_hit_frame_indices(frame_cands, gate_ratio)
        if zero_fis and rotated:
            det_cfg = dict(cfg)
            det_cfg['bridge_horizontal_gaps'] = True
            sub_frames = [frames[fi] for fi in zero_fis]
            fc3 = _run_region_detection(
                lines_for_detection, det_cfg, sub_frames, frame_area, frame_labels,
                connection_points, rotated_edge_roles, labels_by_text)
            for j, fi in enumerate(zero_fis):
                frame_cands[fi] = fc3[j]

        # 4パス目（レベル汚染フォールバック・図面枠単位）: 領域境界線と同属性の無関係な
        # 近接線分（例: 境界線 y=122.00 の 0.37 上のコネクタ箱底辺 y=122.37）が共線結合の
        # レベルクラスタ平均を汚染して境界線をシフトさせ、縦線端点との接続が切れて閉領域が
        # 不成立になる枠がある（EE6892-039-05B.dxf の2枠目、SYSTEM I/F BOX）。
        # そのような「閾値超え候補ゼロの枠」に限り、スパン単位レベル（汚染なし）で再検出する。
        # 発動条件: (a) 閾値超えゼロの枠がある、(b) 他の枠には閾値超えの領域がある
        #   （全枠ゼロの図面タイプ〔電源基板の回路図等〕では発動しない）
        # 採用条件: 回復した領域の名称が他枠で検出済みの名称と一致する枠のみ置き換える
        zero_fis = [fi for fi, cl in enumerate(frame_cands)
                    if not any(_area_ratio_met(cf['area'], frame_area, gate_ratio) for cf in cl)]
        hit_names = {cf['default_name']
                     for fi, cl in enumerate(frame_cands) if fi not in zero_fis
                     for cf in cl
                     if _area_ratio_met(cf['area'], frame_area, gate_ratio) and cf['default_name']}
        if zero_fis and hit_names:
            cfg_span = dict(det_cfg)
            cfg_span['span_level_merge'] = True
            sub_frames = [frames[fi] for fi in zero_fis]
            fc2 = _run_region_detection(
                lines_for_detection, cfg_span, sub_frames, frame_area, frame_labels,
                connection_points, rotated_edge_roles, labels_by_text)
            for j, fi in enumerate(zero_fis):
                if any(_area_ratio_met(cf['area'], frame_area, gate_ratio) and cf['default_name'] in hit_names
                       for cf in fc2[j]):
                    frame_cands[fi] = fc2[j]

        # 2) 第1図面（最左フレーム）で「同名複数ピース合算>=group_ratio」となる名称を
        #    ターゲットとする（MPD RACK2 のように2矩形で合算が閾値超のケース）。
        #    他図面では、このターゲット名称の矩形を面積に関係なく抽出する。
        target_names = set()
        if frame_cands:
            by_name = defaultdict(list)
            for cf in frame_cands[0]:
                if cf['default_name']:
                    by_name[cf['default_name']].append(cf['area'])
            for nm, areas in by_name.items():
                if len(areas) >= 2 and _area_ratio_met(sum(areas), frame_area, group_ratio):
                    target_names.add(nm)

        # 3) 採用条件: 個別面積>=単独閾値、または 名称がターゲット（複数ピース合算で
        #    第1図面が閾値超）、または合体親（union parent）の子と確認された候補
        #    （`_force_include_union_children`、面積閾値を問わず採用。後述）。
        #    ターゲット名称は他図面でも面積に関係なく採用。
        regions = []
        rid = 0
        for fi, cands_list in enumerate(frame_cands):
            force_idx = _force_include_union_children(cands_list, frame_area, area_ratio)
            for cidx, cf in enumerate(cands_list):
                if not (_area_ratio_met(cf['area'], frame_area, area_ratio)
                        or (cf['default_name'] and cf['default_name'] in target_names)
                        or cidx in force_idx):
                    continue
                regions.append({
                    'id': rid,
                    'frame': fi,
                    'polygon': cf['polygon'],
                    'corners': _polygon_corners(cf['polygon']),
                    'area': cf['area'],
                    'area_pct': 100.0 * cf['area'] / frame_area,
                    'name_candidates': cf['name_candidates'],
                    'default_name': cf['default_name'],
                    'name_candidate_positions': cf['name_candidate_positions'],
                })
                rid += 1
        regions = _resolve_complement_faces(regions, frame_area, next_id=rid)
        regions = _resolve_union_parents(regions, labels=frame_labels, cfg=cfg)
        _remove_overlap_claimed_candidates(regions)
        result['regions'] = regions

        del doc, msp
        gc.collect()
    except Exception as e:
        result['error'] = str(e)
        gc.collect()
    return result


def assign_region_labels(labels, named_regions):
    """各ラベル(text,x,y)が内包される領域名のリストを返す。

    named_regions: [{'polygon': [...], 'name': str}]（名称確定済み）。
    戻り値: [(text, x, y, [region_name, ...]), ...]
    """
    out = []
    for (t, x, y) in labels:
        names = []
        for reg in named_regions:
            nm = reg.get('name')
            if nm and _point_in_polygon((x, y), reg['polygon']) and nm not in names:
                names.append(nm)
        out.append((t, x, y, names))
    return out
