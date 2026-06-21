# TECHNICAL.md — DXF-viewer

## 概要

PyQt5 ベースのデスクトップ DXF ビューア。マルチタブでの複数ファイル同時表示、テキスト検索、エンティティ色変更、PNG/SVG/PDF エクスポートを備える。
元は 1683 行の単一ファイル（`../DXF-processor/dxf_viewer.py`）をリファクタリングした版。

> **Streamlit アプリではない。** ローカル実行専用。

---

## ディレクトリ構成

```
DXF-viewer/
├── dxf_viewer.py           # エントリポイント（引数: DXF ファイルパス可）
├── requirements.txt
├── ui/
│   ├── main_window.py      # DXFViewerApp: メインウィンドウ・メニュー・ツールバー
│   ├── viewer_widget.py    # PinchZoomCADViewer: 拡大縮小・パン・ジェスチャー対応
│   └── dialogs.py          # 全ダイアログ（検索・色変更・エクスポート等）を集約
├── core/
│   ├── tab_manager.py      # DXFTab: タブごとの状態管理
│   ├── color_manager.py    # エンティティ色操作（静的メソッド中心）
│   ├── search_manager.py   # テキスト検索・ハイライトロジック
│   ├── region_detector.py  # 矩形領域（直交ポリゴン）検出（DXF-extract-labels より移植）
│   ├── region_search_manager.py  # 領域検索（解析キャッシュ＋名称マッチ）
│   └── layer_consolidator.py  # レイヤー統合（Boundaries / Imported 化）
├── workers/
│   └── ezdxf_worker.py     # バックグラウンドスレッド（ezdxf コマンド実行）
└── utils/
    ├── file_utils.py       # ファイル検証・パス処理
    ├── app_utils.py        # アプリケーション初期化・シグナル定義
    ├── text_utils.py       # MTEXT/TEXT 書式コード除去（検索一致用・plain_mtext）
    ├── export_utils.py     # エクスポート機能（旧版・後方互換のため残存）
    └── export_utils_v2.py  # エクスポート機能（新版・matplotlib 使用）
```

---

## アーキテクチャ

### レイヤー構造

```
UI Layer (ui/)
  ↔ Core Layer (core/)    ← ビジネスロジック（UI 非依存）
  ↔ Workers (workers/)    ← バックグラウンドスレッド
  ↔ Utils (utils/)        ← 共通ユーティリティ
```

### 主要クラス

| クラス | ファイル | 役割 |
|--------|---------|------|
| `DXFViewerApp` | `ui/main_window.py` | メインウィンドウ、タブ管理、メニュー |
| `PinchZoomCADViewer` | `ui/viewer_widget.py` | ezdxf の CAD ウィジェット拡張、ジェスチャー対応 |
| `DXFTab` | `core/tab_manager.py` | タブ 1 枚分の状態（ファイルパス・選択エンティティ等）|
| `ColorManager` | `core/color_manager.py` | エンティティ色の取得・変更（静的メソッド）|
| `SearchManager` | `core/search_manager.py` | テキスト検索・ハイライト（静的メソッド）|
| `RegionSearchManager` | `core/region_search_manager.py` | 領域検索：解析キャッシュ・名称マッチ（UI 非依存）|
| `EzdxfWorker` | `workers/ezdxf_worker.py` | ezdxf コマンドをバックグラウンドスレッドで実行 |

---

## 起動方法

```bash
# 依存インストール
pip install -r requirements.txt

# 起動（ファイルなし）
python dxf_viewer.py

# ファイル指定起動（拡張子省略可）
python dxf_viewer.py drawing1 drawing2.dxf
```

---

## 主要機能の実装

### ツールバー（全機能のボタン化・2段）

**方針: すべての機能をツールバーのボタンから操作可能にする。** `create_toolbar()` は
`addToolBarBreak()` で**2段**に分け、以下を配置する。

- **1段目**: Open / Info / Export / Search / Clear Search / Find Next / Find Previous /
  Search Boundary / Clear Boundary Highlight
- **2段目**: Change Colors / Restore Colors / Background Color / Consolidate Layers

検索ナビ・境界検索・レイヤー統合はメニュー用 `QAction` を**再利用**してツールバーに
追加しており（同一アクションを menu と toolbar の両方に add）、有効/無効状態は自動で
連動する（重複した状態管理コードは持たない）。メニューバーは併存（キーボード
ショートカットと項目の探索性のため）。

### LWPOLYLINE 内側エンティティのホバー検出（`ui/viewer_widget.py`）

Qt の `qt_graphicsItem_shapeFromPath()` は、stroked outline に `addPath(path)` を加えるため、
**閉じた QPainterPath のヒット領域が内部エリア全体**を含む。閉じた LWPOLYLINE が
`draw_path()` → `QGraphicsPathItem` に変換されると、その内側のエンティティが
マウスホバーで拾えなくなる（LWPOLYLINE が最前面として捕捉される）。

**修正（`_ClickThroughPathItem` + `_ClickThroughBackend`）:**
- `_ClickThroughPathItem`（`QGraphicsPathItem` サブクラス）: `shape()` を outline のみに
  限定（`QPainterPathStroker` で `_HIT_WIDTH=3.0` の帯を返す）
- `_ClickThroughBackend`（`PyQtBackend` サブクラス）: `draw_path()` で
  `_ClickThroughPathItem` を使用する
- `PinchZoomCADViewer._install_click_through_backend()`: `CADWidget._reset_backend` を
  monkey-patch して、ファイルロード・リフレッシュのたびに `_ClickThroughBackend` が
  使われるよう注入する

LWPOLYLINE の輪郭線上はホバー可能（`_HIT_WIDTH=3.0` の帯が hit area）、
内側は click-through となり内部エンティティのホバーが機能する。
`_OverlayPolygonItem` と同じ `shape()` オーバーライドパターン。

### ホバーハイライトを輪郭のみに限定（`_OutlineHighlightGraphicsView`、2026-06-21 追加）

ezdxf の `CADGraphicsViewWithOverlay.drawForeground()` は、ホバー中アイテムの
**`boundingRect()` 全体**を緑（`QColor(0,255,0,100)`）で塗る。閉じた `QGraphicsPathItem`
（上記の `_ClickThroughPathItem`、典型的には lineweight=25/color=2 の閉じた LWPOLYLINE
で描かれた矩形領域の境界）は、`shape()` を outline のみに絞っていても
**`boundingRect()` は依然としてパス全体（矩形の全域）を返す**ため、辺にホバーすると
領域全体が緑で塗り潰され、ホバー中の辺そのものが見えなくなっていた。

**修正**: `CADGraphicsViewWithOverlay` を継承する `_OutlineHighlightGraphicsView` を追加し、
`drawForeground()` を `item.boundingRect()` ではなく `item.shape()`（実際にヒットテストされた
輪郭の帯）を塗るよう上書き。`PinchZoomCADViewer.__init__` は `CADViewer.__init__(cad=...)` に
`CADWidget(_OutlineHighlightGraphicsView(), config=Configuration())` を渡すことでこのビューを
注入する（`CADViewer.__init__` が `cad` 引数を受け付ける既存のフックを利用、monkey-patch 不要）。
通常の `LINE`（`QGraphicsLineItem`）は `shape()` と `boundingRect()` がほぼ同じ細い帯なので
見た目は変わらない。ヒット判定・選択ロジック（`_selected_items` 等）・サイドバーの属性表示は
変更していない。

### ezdxf CADViewer メニューの非表示化

`CADViewer`（ezdxf）は `QMainWindow` サブクラスであり、`__init__` で
`Select Document` / `Select Layout` / `Toggle Sidebar` / `Toggle Entity Marker` / `Reload`
の 5 項目をメニューバーに追加する。macOS ではこのメニューがグローバルメニューバーに
マージされて表示されてしまう。

`PinchZoomCADViewer.__init__` で `super().__init__()` の直後に以下を呼んで非表示にする:

```python
self.menuBar().setNativeMenuBar(False)  # macOS グローバルメニューバーへの統合を無効化
self.menuBar().hide()                   # ウィジェットとしても非表示
```

`setNativeMenuBar(False)` を省いても `hide()` のみで動作するが、両方指定すると確実。
ezdxf 側の機能（Reload / Watch / Select Layout）はメニューから使えなくなるが、
DXF-viewer 独自のツールバー／メニューで代替できる。

### マルチタブ

- `QTabWidget` + `DXFTab` データクラスで管理
- タブ切り替え時に `DXFTab.viewer_widget` の参照を差し替える

### 検索（`core/search_manager.py`）

- `SearchManager.find_text_entities()` で TEXT/MTEXT エンティティを走査（modelspace + ブロック定義）
- マッチしたエンティティをハイライト色に変更
- **テキスト正規化**: `utils/text_utils.clean_mtext_format_codes()` で書式コードを除去してから一致判定する。
  ezdxf の `plain_mtext()` ベース。TEXT/MTEXT 両経路に適用。
  - 旧実装は `\H \P \L \p \f \F \c \C` のみを正規表現で除去しており、ULVAC EE 図面でほぼ全 MTEXT が持つ
    `\A`（整列）・`\W`（幅）・`\T`（トラッキング）コードを取りこぼし、可視文字列（例 `MPD RACK1`）が
    検索ヒットしなかった。`plain_mtext` 化でこれを解消（EE6868/EE6888 計 12,159 件で書式コード漏れゼロ・退行なしを確認）。
  - 副次効果: 前後空白・全角空白・`\P` 段落跨ぎの正規化。`%%c`/`%%d`/`%%p` は Ø/°/± へ変換。
  - 回帰テスト: `tests/regression/test_mtext_clean_search.py`

### 領域検索 / Boundary Search（`core/region_detector.py` + `core/region_search_manager.py`）

手書き電気回路図中の矩形領域（ラック・ボックス等の機能領域）を**名称で検索**し、
該当する境界をハイライトする。テキスト検索と並列の機能。

- **検出**: `region_detector.analyze_dxf_regions(file_path)`。図面枠（lineweight=100）と
  領域境界線（lineweight=25 / color=2＝ACI黄、かつ線種が実質的に Continuous＝実線である
  こと。`_is_continuous_linetype()`、2026-06-21 v1.5.10・DXF-extract-labels から移植）を
  識別キーに、端点接続ベースの半面探索で閉領域を列挙し、下端横エッジ近傍のラベルから
  名称候補を付与する。DXF-extract-labels の同名モジュールを移植したもの（依存関数のみ
  自己完結化、アルゴリズム本体は同一）。設定は `DEFAULT_REGION_CONFIG`（DXF-extract-labels
  のデフォルト値）。

  **線種(linetype)フィルタの追加理由**: lineweight/color が境界線条件に一致していても、
  線種がPHANTOM（二点鎖線）等の装飾的な線種は閉領域の壁を表すものではない。
  `EE6313-546-01E.dxf` で、実体の小さな矩形（handle 21AB/21AC/219A/219E、Continuous）の
  周囲に、別の handle（21AE/21A1/21A9/2198等、PHANTOM）で描かれた二点鎖線の矩形が重なって
  存在しており、これも境界線として誤認識され、実体矩形を「くり抜いた」形状の存在しない
  領域が誤検出されていた（DXF-extract-labels側でユーザーが報告。Search Boundary の
  座標リスト機能で頂点座標を確認した際に発覚）。`linetype='ByLayer'` の場合はレイヤーの
  既定線種まで解決する。

  **コード構造のリファクタリング（2026-06-21 追加・DXF-extract-labels から移植）**

  上記の機能追加が積み重なり `region_detector.py` が大規模化したため、モジュール性・
  可読性向けの整理を実施（ロジック変更なし、検出結果は不変）。セクション見出しコメント
  で12ブロック（依存関数／設定／ジオメトリ収集／ポリゴン幾何ユーティリティ／線分結合／
  図面枠検出／閉領域検出／名称候補／ラベル座標逆引き／回転判定／タイトルブロック除外／
  トップレベル解析）に整理し、最も複雑だった `_find_rectilinear_faces`（旧175行）を
  `_build_planar_graph`（平面グラフ構築）・`_peel_dangling_branches`（行き止まり枝の
  除去・連結成分化）・`_trace_faces`（半面探索）の3関数に分割。`analyze_dxf_regions`
  内の入れ子クロージャ（`_run_detection`/`_hits`）も `_run_region_detection`/
  `_count_threshold_hits` としてモジュールレベルに抽出した。DXF-viewer 独自の最適化
  （`_filter_eligible_labels` の事前計算キャッシュ・`block_has_relevant_content` による
  INSERT展開スキップ）・Search Boundary 用のラベル座標逆引き（`_group_labels_by_text`/
  `_label_position_for_candidate`）はそのまま保持。`tests/regression/test_region_search.py`
  等、回帰テストは全て同じ検出件数・出力で通過を確認済み。

  **図面枠検出 (`detect_drawing_frames`)**

  lineweight=100 の縦線分を `_merge_collinear(bridge=False)` で統合（接触/重複のみ結合、
  隙間は橋渡しせず）してから高さ判定する。`bridge=False` にしている理由: 枠縦辺が
  接触点で分割されているケース（例: EE6888-631-01A.dxf 右辺が y=367.5 で2分割）は
  接触結合だけで高さ 400 が確保できる。`bridge=True` にすると無関係セグメントが
  橋渡しされ余分なフレームが生じる（EE6868-500-01C.dxf で 13→19 フレームの退行が
  確認されたため False に戻した）。

  **LWPOLYLINE 境界対応 — LINE 優先 2 パス検出**

  境界線を LINE で描く図面（例: EE6888-602-01A.dxf）と LWPOLYLINE で描く図面
  （例: EE6888-631-01A.dxf）が混在するため、2 パス戦略を採用する。

  `_collect_region_geometry()` は LINE 由来と LWPOLYLINE 由来の境界線を別リストに収集し、
  `analyze_dxf_regions()` は次の順で検出する:
  1. **LINE のみ**で検出 → 閾値超え候補が 1 件以上あればその結果を採用して終了。
  2. 候補ゼロかつ LWPOLYLINE 境界線がある場合 → **LINE+LWPOLYLINE** で再検出。
  3. それでも候補ゼロ、かつ図面全体が90°回転している場合 → 横線分ギャップ橋渡しを
     有効にして再検出（下記「90°回転図面対応」参照）。

  **90°回転図面対応（2026-06-18 追加・DXF-extract-labels から移植）**

  手書き回路 DXF の一部は、図面枠は通常向きのまま、枠内の回路内容（ラベル・部品）だけが
  90°回転して描かれている（例: `DE5434-553-10B.dxf`）。この場合、移植元には無かった
  以下の2つの暗黙の前提が崩れ、領域が1件も検出できなくなる（修正前は実測で
  frames=5・regions=0）。

  - 「名称は下端/上端の**横**エッジ脇にある」→ 回転図面では左右いずれかの**縦**エッジ脇。
  - 「部品は**縦**線分だけを途切れさせる」→ 図面全体が回転していると逆に**横**線分を
    途切れさせる。

  対応として `_is_globally_rotated(label_entities)` がラベル(TEXT/MTEXT)の過半数の
  回転角(`_label_rotation_angle`、MTEXT は `text_direction` ベクトル優先)から図面全体の
  回転を明示的に判定し、回転図面と判定された場合のみ:
  - `region_name_candidates()` の Tier1/2（下端相当/上端相当の最近傍）を、横エッジ
    （下端/上端）ではなく左右いずれかの縦エッジに切り替える（`rotated_edge_roles`。
    詳細は後述の v1.5.9 セクション参照。旧実装の `also_scan_vertical=True`〈横エッジ
    候補に縦エッジ候補を常時合算〉は v1.5.9 でこの Tier 制に置き換えた）。
  - `_detect_regions()` で `bridge_horizontal_gaps=True` を有効化し、縦ギャップ橋渡しと
    同じ安全条件（コーナー相手なし・CIRCLEなし、x/y入れ替えで判定）で横線分のギャップも
    橋渡しする。

  回転判定を明示的な条件にしているのは、「検出ゼロ件だったから」だけをトリガーにすると、
  通常向きの図面が別の理由でゼロ件になったときに無関係な隣接矩形を誤って結合する副作用が
  あるため。通常向き図面では回転判定が常に False になるため既存の検出結果に影響しない
  （既存回帰テスト `tests/regression/test_region_search.py` で確認済み）。

  この順序が必要な理由: EE6888-602-01A.dxf では小部品（コネクタ端子 9×15 等）が
  LWPOLYLINE/lw=25/color=2 で描かれており、これを境界線に混ぜると水平辺が縦境界線の
  corner-partner 判定を誤らせ gap-bridging を妨げる。LINE 優先で十分な図面では
  LWPOLYLINE を混入しないことで、この干渉を回避する。

  **行き止まり枝（dangling edge）の除去（2026-06-21 追加・DXF-extract-labels から移植）**

  境界線と同じ線種（lineweight=25/color=2）を持ちながら、どこにも閉じていない線分
  （次数1のノードに繋がる枝）があると、`_find_rectilinear_faces()` の半面探索は
  その枝を折り返すしかなく（次数1のノードでは戻る辺が1本しかないため）、生の
  ポリゴンに「同じ頂点が2回連続する」アーティファクトを生む（実例:
  `EE6313-546-01E.dxf` の `頂点の座標` リストに `(660.53, 129.56)` が2回連続して
  現れる不具合として報告。原因は handle `214F`/`2199` の2本の短い枝線が、本来
  繋がるべき相手まで約5単位届かず行き止まりになっていたこと）。

  対策として、面探索前に次数1のノードとその辺を再帰的に除去する2-core抽出を
  `_find_rectilinear_faces()` に追加した（戻り値が `faces` 単独から
  `(faces, dangling_branches)` に変更。DXF-viewer は `dangling_branches` を
  使わず破棄するが、戻り値の形は DXF-extract-labels と揃えている）。

  除去した辺は単純なフラットなリストではなく、Union-Find で**連結成分（枝）**に
  まとめている（1本の枝が複数の短い線分の連なりで構成される場合に対応。
  DXF-extract-labels 側でこの枝単位に対し「現存する境界グラフへの取り付け点
  (`attachment`) が各領域のポリゴン境界上に乗るか」で領域ごとの関連付けを行う
  ため。DXF-viewer はその先（handle解決・領域絞り込み・UI表示）は持たないが、
  アルゴリズム本体は同一に保つ方針のため `_find_rectilinear_faces()` のこの部分
  だけ移植した）。

  **副次効果（同一領域の重複検出バグも解消）**: 行き止まり枝の往復は面積には
  正味ゼロしか寄与しないため、同一の物理境界が「綺麗な内側面」と「枝の往復で
  座標が汚れ bounding box が変わった外側面」の2つの別領域として重複検出される
  ケースがあった（座標の汚れにより既存の bbox 重複除外をすり抜けていた）。
  除去後は両者が同一 bbox になり正しく1領域に統合される
  （`EE6313-546-01E.dxf`: regions 6→5。`DE5434-553-10B.dxf`: regions 9→8。
  汚れた版は迂回経路上の無関係なラベル `SB-1A(L1)` 等まで誤って名称候補に
  取り込んでいたため、名称候補も正しくなった）。
  `tests/regression/test_region_search.py` の `DE5434-553-10B.dxf` 期待値を
  `min_regions` 9→8 に更新済み。他サンプルの検出結果は変化なし。

  **領域名候補の優先順位（Tier）制（2026-06-21 追加・DXF-extract-labels から移植）**

  `region_name_candidates()` を「候補ゼロのときだけ次のフォールバックを試す」
  という旧構造から、明示的な優先順位（Tier）制に置き換えた:
  - Tier1: 下端横エッジ最近傍（回転図面では `_rotated_edge_roles()` が判定した
    側の縦エッジ＝下端相当。実例: `DE5434-553-10B.dxf`〈回転角+90°多数派〉では右端）
  - Tier2: 上端横エッジ最近傍（回転図面ではもう一方の縦エッジ＝上端相当）
  - Tier3: Tier1/2 のいずれでも候補ゼロの場合のみ、ポリゴン境界全体（任意の辺）
    への最短距離でフォールバック評価する（`_dist_point_to_polygon`）。

  DXF-extract-labels 側はこの変更を「入れ子/隣接する2領域が互いの候補リストに
  相手の名称を含む場合、領域選択UIの他領域同期ロジックが片方の領域自身の最有力
  候補（下端最近傍）を誤って上書きする」不具合の修正として導入した
  （`EE6313-546-01E.dxf` の図面1/領域1,2 が同じ選択に同期される報告）。DXF-viewer
  には対応する領域選択UI自体が無いため同期ロジックの修正対象は無いが、
  「アルゴリズム本体は同一に保つ」方針に従い `region_name_candidates()` の
  Tier 化と `_rotated_edge_roles()` のみ移植した（`default_name_tier` の付与は
  DXF-viewer 側に消費者が無いため移植していない）。回帰テスト
  `tests/regression/test_region_search.py` の既存期待値（`DE5434-553-10B.dxf` の
  `LA CHAMBER`/`CONTROL BOX CORE FX`/`CONTROL BOX CORE RX` 一致件数）に変化が
  無いことを確認済み。
- **マッチ**: `RegionSearchManager.find_matching_regions()` が入力名称を各領域の
  `name_candidates`（`default_name` は常にその先頭要素なので別チェック不要）と照合
  （case sensitive / whole word 対応）。戻り値は `analysis['regions']` 各要素の浅いコピー
  に `matched_labels: [(text, x, y), ...]`（マッチした候補テキストとその元ラベルの座標）
  を追加したもの。座標は `region_detector.analyze_dxf_regions()` が各領域の
  `name_candidate_positions`（`{候補テキスト: (x, y)}`）として併せて算出している
  （`region_name_candidates()` 自体の戻り値は DXF-extract-labels と揃えるため変更せず、
  `_label_position_for_candidate()` で同テキストのラベルからポリゴンに最も近いものを
  逆引きする）。
- **キャッシュ**: `RegionSearchManager.get_analysis()` が解析結果を `DXFTab.region_analysis`
  に保持。初回のみ実行（大ファイルで数秒、ビジーカーソル表示）、2 回目以降は即時。
  解析は**ディスク上のファイルを読む**ため、ビューア上の dim（色書換え）の影響を受けない。
- **ハイライト（オーバーレイ方式 + ラベル本体の色書換え、2026-06-18 追加）**: マッチ領域の
  ポリゴンを QGraphicsItem の赤い輪郭線としてシーンに重ね描画
  （`DXFViewerApp.draw_boundary_overlays()`）。doc を書き換えないため非破壊。
  加えて `_highlight_matched_labels()` が `matched_labels` の座標を使い、検索した文字列
  そのもの（領域名のラベルエンティティ）も赤に色書換えする（プレーンテキスト検索の
  `SearchManager.apply_search_highlighting()` と同じ赤＝color index 1 / true_color
  0xFF0000）。`_dim_all_entities()` の直後・`refresh_viewer()` の前に呼ぶことで dim 後に
  上書きする。**直接 modelspace に置かれた TEXT/MTEXT のみ**対象（クリーン済みテキスト＋
  座標の一致で照合）。INSERT 展開で得たブロック内ラベルは、実体がブロック定義側に
  ブロックローカル座標で存在し全 INSERT 参照で共有されるため、個別インスタンスだけを
  色書換えできない（プレーンテキスト検索の `SearchManager.find_text_entities()` に既存の
  同種の制限と同じ）。非マッチ要素（ラベル含む）は既存の色書換え機構で dim。全マッチを
  一括表示し zoom-to-fit する。
- **永続ハイライト**: ダイアログの「Keep boundary highlight after Clear Search」が ON の場合、
  Clear Search で dim を戻した後も境界オーバーレイを残す。残した輪郭は
  `Search > Clear Boundary Highlight` で消去する。検索がアクティブな状態（dim 中）で
  Clear Boundary Highlight を押した場合は、オーバーレイ除去に加えて**元の色も復元**する
  （図面が dim 一色のまま残らないようにする）。
- **頂点座標リストによる検索（2026-06-21 追加）**: 名称検索の代わりに、矩形領域の頂点座標
  リストを直接貼り付けて該当領域をハイライトできる。DXF-extract-labels の領域カードの
  「📐」ポップオーバーに表示される「頂点の座標（左下から / N点）」のテキスト
  （`1: (185.19, 23.07)` 形式、1行1頂点）をそのままコピーして
  `BoundarySearchDialog` の「Or Search by Vertex Coordinates」欄に貼り付ける想定。
  - `RegionSearchManager.parse_corner_list(text)`: 各行から `(数値, 数値)` のペアを正規表現
    で抜き出す（行頭の番号・括弧の有無は問わない）。1点も抜き出せなければ呼び出し側
    （`DXFViewerApp.search_boundary()`）が警告ダイアログを出して中断する（空の名称検索に
    フォールバックしない）。
  - `RegionSearchManager.find_region_by_corners(analysis, corners, tol=0.15)`: 各領域が
    既に保持している `corners`（`region_detector._polygon_corners()` の出力、左下から順）
    と照合する。点数が一致し、かつ貼り付けた各点が許容誤差 `tol` 以内で領域側のいずれか
    異なる頂点に対応付けられる（最近接点への貪欲な一対一割り当て）ことを要求する。
    `tol=0.15` は貼り付けテキストの小数2桁四捨五入誤差（最大0.005）より十分大きく、
    領域内の頂点間距離（通常数十単位以上）より十分小さいため、誤マッチの恐れはない。
    順序・回転方向に依存しないため、DXF-extract-labels 側と DXF-viewer 側で
    `_polygon_corners()` の開始点・巻き方向に将来ズレが生じても頑健。
  - **入力の優先順位**: ダイアログの座標欄が空でなければ名称欄は無視される（座標貼り付けは
    明示的でより具体的な操作のため）。マッチ後の処理（オーバーレイ描画・dim・zoom-to-fit）
    は名称検索と完全に共通（`_apply_boundary_highlight()`）。ただし座標検索でマッチした
    領域には `matched_labels` が無いため、`_highlight_matched_labels()` はラベル文字列の
    色書換えをスキップする（境界線のみ赤くハイライトされる）。
- **操作**: ツールバーの「Search Boundary...」「Clear Boundary Highlight」ボタン
  （`Search` メニューにも同項目あり。Ctrl+B でも起動）。
- **状態（`DXFTab`）**: `region_analysis`・`matched_regions`・`boundary_overlay_items`・
  `boundary_search_active`・`boundary_keep_highlight`。
- 回帰テスト: `tests/regression/test_region_search.py`（検出枠数・領域数・名称マッチ件数・
  `matched_labels` が実在の modelspace エンティティへ解決できること、各サンプルの先頭5領域
  について「`corners` を `頂点の座標` と同じ書式に整形→`parse_corner_list`→
  `find_region_by_corners`」のラウンドトリップで元の領域 1 件にのみ一致すること、
  無関係な座標では一致しないこと）。

**パフォーマンス最適化（2026-06-18 追加）**

大規模図面（数万エンティティ・数万 INSERT 規模）で `analyze_dxf_regions()` が遅い問題に対応。
プロファイリングで判明したボトルネックは大きく3つ（実測: EE6868-500-01C.dxf で
4.80秒→2.41秒、DE5434-553-10B.dxf で1.05秒→0.47秒、いずれも約2倍。出力は最適化前後で
完全に同一であることを JSON 比較で確認済み）。アルゴリズムの判定結果やしきい値は
一切変更していない（同じ計算を無駄なく1回で済ませるだけ）。

1. **ラベル単位フィルタの前計算（`_filter_eligible_labels`）**: `region_name_candidates()`
   は英字数・小文字・除外語・機器符号といったラベル単位の判定を、領域（ポリゴン）に
   一切依存せず行っていたにもかかわらず、領域ごとに呼ばれるたびに全ラベルへ再計算していた
   （1フレームの領域数 × ラベル数）。`analyze_dxf_regions()` 側で1パスにつき一度だけ
   `_filter_eligible_labels()` を計算し、`region_name_candidates(..., _eligible_labels=...)`
   に渡すことで再計算を排除した。`_eligible_labels` 省略時は関数内で計算するため、外部から
   単体で呼ぶ場合の挙動・結果は変わらない。
2. **無関係なブロックの `virtual_entities()` 展開スキップ（`block_has_relevant_content`）**:
   `_collect_region_geometry()` は INSERT ごとに `e.virtual_entities()`（ブロック内容を複製・
   変換する重い処理）を呼んでいたが、手描き回路図では「無関係な図形しか持たないブロックの
   INSERT」が極めて多い（実測ファイルで6万件超）。lineweight/color はブロック定義側の静的な
   属性で INSERT の変換の影響を受けないため、ブロック定義の直接の子だけを見て「図面枠/領域
   境界線になり得る LINE・LWPOLYLINE」または「常に収集対象の TEXT/MTEXT」が1つもないことが
   分かれば、`virtual_entities()` 自体を呼ばずにスキップする（ブロック名単位でキャッシュ）。
3. **`_is_titleblock_region` のバウンディングボックス事前判定**: 領域ごとに全ラベルへ
   `_point_in_polygon`（多角形内外判定）を呼んでいたが、大半のラベルは明らかにポリゴンの
   外（バウンディングボックス外）にあるため、安価な範囲チェックで先に弾いてから
   `_point_in_polygon` を呼ぶようにした。

これらは内部実装のみの変更で、`analyze_dxf_regions()` の戻り値・公開関数の挙動は変えていない
（`tests/regression/test_region_search.py` の既存期待値もそのまま全て成立）。

### レイヤー統合 / Consolidate Layers（`core/layer_consolidator.py`）

入力 DXF に多数存在する `NoLayerName_xxx` などのレイヤーを、英語名の **2 レイヤー**へ
統合する。`Tools > Consolidate Layers`（ツールバーの「Consolidate Layers」ボタンからも実行可）。

- **Boundaries**: 検出された全矩形領域（`analyze_dxf_regions` の `regions`）の境界線。
  modelspace の **LINE** で、領域線種（lineweight=25 / color=2）かつ**領域ポリゴンの辺上に
  乗る**ものを幾何判定（`_is_region_boundary_line` → `_line_on_edges`、エッジは最大区間に
  併合）。
- **Imported**: それ以外のすべてのエンティティ（block 定義・paperspace 含む）。
  block 内のエンティティは block 共有のため幾何分類せず一律 Imported。
- 統合後、未使用になった元レイヤーをレイヤーテーブルから削除（`0`・`Defpoints`・
  2 つの対象レイヤーは保護）。
- **非破壊**: メモリ上の doc のみ変更。ファイルは無変更で、**再オープンで元のレイヤーに復元**。
  ビューアのレイヤーパネルと画像エクスポートに反映される。
- 解析はキャッシュ（`RegionSearchManager.get_analysis`）を再利用、ビジーカーソル表示。
- **制限**:
  - 領域境界線が block 内にある場合は Boundaries に含まれない。
  - `_is_region_boundary_line` は LINE エンティティのみ判定する。LWPOLYLINE で描かれた
    境界線（例: EE6888-631-01A.dxf）は LINE ではないため、領域ポリゴンの辺に一致しても
    Boundaries にならず Imported に分類される。Search Boundary の検出自体は 2 パス戦略で
    正しく動作するが、レイヤー統合での分類が期待どおりにならない点は既知の制限。
  - 実サンプル EE6868-500-01C.dxf は全 23 領域の境界が modelspace の LINE で描かれており
    完全捕捉。EE6888-602-01A.dxf も LINE 境界で完全捕捉。
- 回帰テスト: `tests/regression/test_layer_consolidation.py`（残存レイヤー・周の被覆・本数）。

### 色変更（`core/color_manager.py`）

- `ColorManager.set_entity_color()` でエンティティ色を変更
- 背景色に応じた視認性チェック機能あり

### エクスポート（`utils/export_utils_v2.py`）

- `matplotlib` でカスタム背景色付きレンダリング
- 出力形式: PNG / SVG / PDF
- `export_utils.py`（旧版）は後方互換のため残存

### バックグラウンド処理（`workers/ezdxf_worker.py`）

- `QThread` サブクラス
- ezdxf の重い処理（大ファイル読み込み等）を UI スレッドから分離

---

## 依存パッケージ

```
PyQt5>=5.15.0
ezdxf>=1.4.2
matplotlib       # エクスポート機能で使用
```

---

## 既知の制限

| 制限 | 詳細 |
|------|------|
| Windows/Linux でのジェスチャー | PinchZoom ジェスチャーは macOS でのみ動作確認済み |
| 大ファイルの初期表示 | 数万エンティティ以上で初期レンダリングが遅い |
| export_utils.py の旧版 | `export_utils_v2.py` に置き換えられているが削除されていない |
| Streamlit Cloud 非対応 | デスクトップ GUI アプリのためクラウドデプロイ不可 |

---

## 機能拡張ポイント

| テーマ | 実装アプローチ |
|--------|--------------|
| レイヤーフィルタ UI | `ui/dialogs.py` にレイヤー一覧の `QListWidget` ダイアログを追加 |
| 差分比較表示 | `core/` に diff ロジックを追加し、2 ファイルを並列タブで表示 |
| ブックマーク機能 | `DXFTab` に座標リストを保持し、ジャンプボタンを `ui/` に追加 |
| ズームレベルの保持 | `DXFTab.zoom_level` フィールドを追加してタブ切り替え時に復元 |
| 設定の永続化 | `QSettings` で背景色・ウィンドウサイズ等をアプリ設定に保存 |

---

*最終更新: 2026-06-21（矩形領域の辺ホバーハイライトを輪郭のみに限定 + Search Boundary に頂点座標リストでの検索を追加 + 閉領域検出で行き止まり枝を除去し頂点座標の重複アーティファクト・領域重複検出バグを解消 + 行き止まり枝を連結成分単位でグルーピング + 領域名候補の優先順位(Tier)制を導入 + 領域境界線の収集にPHANTOM等の線種除外を追加 + region_detector.py のモジュール性・可読性向けリファクタ）*
