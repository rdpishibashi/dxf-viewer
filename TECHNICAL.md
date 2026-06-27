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

### ツールバー（全機能のボタン化・2段、2026-06-23 構成変更）

**方針: すべての機能をツールバーのボタンから操作可能にする。** `create_toolbar()` は
`addToolBarBreak()` で**2段**に分け、以下を配置する。

- **1段目**: Open / **[Search Text / Clear / Next / Prev]** /
  **[Search Handle / Clear / Next / Prev]** / **[Search Boundary / Clear]**
- **2段目**: Change Colors / Restore Colors / Background Color / Consolidate Layers /
  Export / Info

（3つの検索系を区切り線でグループ化。各グループ内の Clear/Next/Prev はグループ名で
意味が一意に決まるため、ボタン上は短いラベルで揃える。Info/Export はユーザー希望で
2段目の末尾に移動）

**自動折り返しに関する注意**: Search Handle 機能追加直後、Open/Info/Export + 検索3
グループを全て1段目に詰め込んだところ、`sizeHint` 幅がウィンドウ幅（既定1200px）の
1112pxに達し、実機の実フォントメトリクスではウィンドウ幅を超えて Qt の自動折り返しが
発生、ボタンの表示順が視覚的に破綻した（"Consolidate Layers" の後ろに "Export"・
"Info" が来るように見える、という形でユーザーから報告）。現在の1段目（Open + 検索3
グループ、Info/Export を含まない）の `sizeHint` は945px（既定ウィンドウ幅1200pxの
約79%）まで抑えられている。**各段の `sizeHint` 幅をウィンドウ幅より十分小さく保つこと**
が、`addToolBarBreak()` による明示的な行分割を機能させ自動折り返しによる表示崩れを
避ける鉄則（ウィンドウを大きく縮小する・ボタンがさらに増える場合は要再確認）。

検索ナビ・境界検索・handle検索・レイヤー統合はメニュー用 `QAction` を**再利用**して
ツールバーに追加しており（同一アクションを menu と toolbar の両方に add）、有効/無効
状態は自動で連動する（重複した状態管理コードは持たない）。メニューバーは併存
（キーボードショートカットと項目の探索性のため）。

**ツールバーとメニューでラベルを分ける（`QAction.setIconText()`、2026-06-23 追加）**:
上記のように menu と toolbar で同一 `QAction` を共有しつつ、表示テキストだけ変えたい
場合（menu は探索性重視で `'Find Next'`、toolbar はスペース節約で `'Next'` 等）は、
`action.setText(...)` の他に `action.setIconText(...)` を呼ぶ。`text()` は menu 表示に、
`iconText()`（未設定なら `text()` から自動生成）は アイコン無しの `QToolButton` 表示に
使われる、という Qt の役割分担をそのまま利用しており、有効/無効状態の自動連動を保った
まま表示だけを分離できる（新しい状態管理は不要）。

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

### Handle 検索 / Search Handle（`core/search_manager.py`、2026-06-23 追加）

DXF の handle（例 `212A`）を直接指定して、その1エンティティ（複数指定も可）を
ハイライトする。テキスト検索・境界検索と並列の第3の検索モード。

- **解決**: `SearchManager.find_entities_by_handles(doc, handles_text)`。
  `doc.entitydb.get(handle)` で直接引く（modelspace・paperspace・block 定義のどこに
  あっても1回の lookup で取得できる。スキャン不要）。入力はスペース／カンマ区切りで
  複数指定可能、各トークンは先頭の `#` を除去・大文字化してから lookup する（`doc.entitydb`
  は大文字小文字を区別する厳密一致のため）。重複は除去、見つからなかった handle は
  `not_found` リストで返す。
  - **位置の決定**: `ezdxf.bbox.extents([entity], fast=True)` の中心点を使う。bbox が
    計算できないエンティティ（例: 可視テキストが空白のみの MTEXT）は `entity.dxf.insert`
    （アンカー点）にフォールバックする。
- **ハイライト**: `SearchManager.apply_highlighting(tab_data, results, dim_color)` という
  汎用版を新設し、既存の `apply_search_highlighting(tab_data)`（テキスト検索用）はこれに
  委譲するよう変更（dim/highlight のロジック自体は変更なし、結果セットと dim color を
  外から渡せるようにしただけ）。`restore_original_colors()` は元々どの検索モードにも
  依存しない実装だったため変更不要、そのまま共用。
- **状態（`DXFTab`）**: `handle_search_results`・`current_handle_search_index`・
  `handle_search_active`・`handle_search_dim_color`。テキスト検索の `search_results` 系とは
  独立（ナビゲーション（Next/Prev）の対象が異なるため）。
- **ナビゲーション**: `navigate_to_result(tab_data, results, index)` は対象の `results`
  リストを明示的に受け取るよう汎用化（旧実装は `tab_data.search_results` を直接参照して
  いた）。テキスト検索・handle検索の両方の Find Next/Previous がこの1つの実装を共有する。
- **排他制御**: テキスト検索・境界検索・handle検索は同時に1つだけアクティブになる
  （各検索の開始時に他の2つを `clear_search()` / `clear_boundary_highlight()` で解除）。
  `clear_search()` 自体もテキスト検索とhandle検索の両方の状態をまとめて解除するよう拡張
  した（元々テキスト検索＋境界検索の両方を解除していた箇所に handle検索を追加）。
- **UI**: メニュー「Search Handle...」「Clear Search Handle」「Find Next Handle」
  「Find Previous Handle」。ツールバーは同じ `QAction` を再利用し `setIconText()` で
  短縮表示（前述）。キーボードショートカットは割り当てていない（`Ctrl+H` は macOS の
  「アプリを隠す」とシステムレベルで衝突するため意図的に避けた）。
- 回帰テスト: `tests/regression/test_handle_search.py`（`#` 付き／小文字／カンマ区切り・
  重複・未解決 handle の解決ロジックに加え、`DXFViewerApp.search_handle()`/`clear_search()`
  を headless（`QT_QPA_PLATFORM=offscreen`）で実行し、ダイムハイライト・色復元・UI状態の
  有効/無効までを検証）。

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

  **Search Boundary のマッチング精度修正（2026-06-21 追加）**

  `EE6313-546-01E.dxf` を Search Boundary で "B CHAMBER" 検索すると、境界線が
  交わらない領域1（外側、`B CHAMBER`）・領域2（内側、`BAKE HEATER UNIT RX`、
  完全内包）の**両方**がハイライトされる不具合をユーザーが報告。"BAKE HEATER
  UNIT RX" 検索でも同様。原因は `region_name_candidates()` が境界近傍の全ラベル
  を確信度付きで列挙するだけで、入れ子/隣接領域は互いの候補リストに相手の名称も
  持つこと、かつ `find_matching_regions()` がその `name_candidates` 全体と照合
  していたこと。

  対策として `find_matching_regions()` を、各領域の最上位候補（`default_name`。
  ユーザー確認: DXF-extract-labels の Tier 優先順位制と同じ仕組みで選ばれる
  「一番優先順位が高いラベル」）のみと照合するよう変更。これにより、各領域は
  自分自身の最有力候補にのみマッチし、上記の入れ子ケースは正しく1領域だけが
  マッチするようになった。

  この変更を機に、`region_name_candidates()` 自体の Tier1/2 判定に既存バグが
  あることが判明: Tier1/2 のスキャンが「領域の内側にあるラベルか」を確認して
  いなかったため、`DE5434-553-10B.dxf` の回転領域で、領域の**外側**にある
  ラベル `EFEM UPPER`（距離3.9）が、領域の**内側**にある正しいラベル
  `CONTROL BOX CORE FX`（距離5.2）より単純な距離比較で優先されてしまっていた
  （ユーザー指摘: "EFEM UPPER は領域の外側なので、優先順位は CONTROL BOX CORE FX
  よりも低いはず"）。`region_name_candidates()` の `_scan()` に `require_inside`
  引数を追加し、Tier1/2 では `_point_in_polygon()` で領域内側のラベルのみを
  対象にするよう修正（Tier3 フォールバックは内外を問わず従来通り）。
  `tests/regression/test_region_search.py` の `EE6313-546-01E.dxf`・
  `EE6888-631-01A.dxf`・`EE6492-631-02A.dxf` 期待値を更新（後2者は、SB-1A
  領域が領域外のラベル `SYSTEM I/F BOX` を弱い候補として持っていたため
  `'SYSTEM'` 検索が4件→2件に変化。DXF-extract-labels 側にも同じ修正を移植済み）。

  **図面枠検出 (`detect_drawing_frames`)**

  lineweight=100 の縦線分を `_merge_collinear(bridge=False)` で統合（接触/重複のみ結合、
  隙間は橋渡しせず）してから高さ判定する。`bridge=False` にしている理由: 枠縦辺が
  接触点で分割されているケース（例: EE6888-631-01A.dxf 右辺が y=367.5 で2分割）は
  接触結合だけで高さ 400 が確保できる。`bridge=True` にすると無関係セグメントが
  橋渡しされ余分なフレームが生じる（EE6868-500-01C.dxf で 13→19 フレームの退行が
  確認されたため False に戻した）。

  **図面枠の識別条件に color=7 を追加、高さ閾値 `min_side` を撤廃（2026-06-24）**

  従来は lineweight=100 のみで図面枠線を識別し、`detect_drawing_frames` の
  `min_side=400.0`（縦辺の高さがこれ未満なら除外）で無関係な短い線分を弾いていた。
  この固定閾値のせいで、枠の縦辺がそれより小さい図面（例: `EE6097-039-06C.dxf`、
  高さ277。INSERT `#E02`/`#E03`/`#E04` 内の lineweight=100 LINE 4本×3枠で構成）が
  「図面枠が見つかりませんでした」エラーになっていた。

  ユーザーが実図面を調査した結果「図面枠はすべて lineweight=100 かつ color=7（ACI白）」
  との報告を受け、`_collect_region_geometry()` の図面枠線収集条件に `color == 7`
  （`DEFAULT_REGION_CONFIG['frame_color']`）を追加。サンプル137件（`sample-dxf/`
  非pairC 27件 + `pairC/` 110件）で検証した結果:
  - lineweight=100 のみでは、枠とは無関係な短い線分（実例: `EE6868-500-01C.dxf` の
    色5・高さ10.2/55.2の線分群48+170本）が多数混在しており、これらが偶然ペアになって
    偽の枠を作っていた（同ファイルで `min_side` を単純に撤廃すると13→31フレームに
    崩壊することを確認）。
  - 一方、color=7 を条件に加えると、これらの無関係な線分はすべて色5以下で除外され、
    実際の枠線（色7）だけが残る。137件中、既存の正しい検出に退行は0件、従来「枠が
    見つからない」スキップだった22件（非pairC 9件 + pairC 13件）すべてが正しく
    検出されるようになった。
  - これにより `min_side` による高さでの足切りは不要になったため既定値を `0.0`
    （フィルタなし）に変更。`detect_drawing_frames(frame_lines, eps, min_side=0.0)`。
  - DXF-extract-labels の `utils/region_detector.py` にも同じ修正（`frame_color`
    設定キー追加・`handle_line` の色判定追加・`min_side` 既定値変更）を移植済み
    （pytest 44件 green を確認）。

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
  modelspace の **LINE** で、領域線種（lineweight=25 / color=2）かつ**領域ポリゴンの辺と
  重なる**ものを幾何判定（`_is_region_boundary_line` → `_line_on_edges`、エッジは最大区間に
  併合）。
- **Imported**: それ以外のすべてのエンティティ（block 定義・paperspace 含む）。
  block 内のエンティティは block 共有のため幾何分類せず一律 Imported。
- 統合後、未使用になった元レイヤーをレイヤーテーブルから削除（`0`・`Defpoints`・
  2 つの対象レイヤーは保護）。
- **非破壊**: メモリ上の doc のみ変更。ファイルは無変更で、**再オープンで元のレイヤーに復元**。
  ビューアのレイヤーパネルと画像エクスポートに反映される。
- 解析はキャッシュ（`RegionSearchManager.get_analysis`）を再利用、ビジーカーソル表示。

**LWPOLYLINE 境界線の分解（`_explode_region_style_lwpolylines`、2026-06-24 追加）**

`_is_region_boundary_line` は元々 LINE エンティティしか判定できず、領域線種
（lineweight=25/color=2）の LWPOLYLINE で描かれた境界（例: `EE6492-631-02A.dxf`・
`EE6888-631-01A.dxf`。境界線の大半が LWPOLYLINE 64本に対し LINE はわずか10本）は
Boundaries に分類されず Imported に取り残されていた（`boundaries=0`）。LWPOLYLINE
は1エンティティ全体が一括で1レイヤーに属するため、辺の一部だけを Boundaries に
移すような分割はできない。

対策として `consolidate_layers()` の冒頭で、領域線種の modelspace LWPOLYLINE を
`LWPolyline.virtual_entities()`（LINE/ARC のプリミティブを元の位置・layer/color/
lineweight/linetype を継承した形で生成。bulge のある区間は ARC になる）で展開し、
`msp.add_line()`/`msp.add_arc()` で実体化（実 handle を持つ通常のエンティティとして
追加）した上で元の LWPOLYLINE を削除する。これにより、展開後の LINE は既存の
`_is_region_boundary_line` でセグメント単位に判定され、辺に乗る部分だけが
Boundaries に、それ以外は Imported に正しく分かれる（ARC は元々 Boundaries 判定の
対象外なので、bulge 区間は常に Imported になる＝既存の ARC の扱いと同じ）。
領域線種に一致しない LWPOLYLINE は展開せずそのまま Imported に分類する（変更前と同じ）。

**境界エッジの分類精度修正（2026-06-24）**

`_collect_region_edges` の軸（垂直/水平）判定が固定許容誤差 `1e-6` を使っていたため、
上流のクラスタリング処理（`region_detector.py` 側で 0.1〜2.0 程度の許容誤差を使用）由来の
浮動小数点ノイズで頂点が「水平でも垂直でもない」と誤判定され、辺ごとマージ対象リストから
丸ごと漏れることがあった（実例: `EE6313-546-01E.dxf` の `B CHAMBER` 領域上辺、隣接する2頂点
の y 座標が `4.3e-6` ずれていた）。許容誤差を `_AXIS_TOL=1e-3` に緩和（実際の辺マッチング
許容誤差 `tol`、既定 0.6、よりは十分小さく、斜め線を誤って軸平行と判定する心配はない）。

加えて `_line_on_edges` の判定を「LINE が辺の範囲に完全に内包される」から「LINE が辺の
範囲と重なる」に変更した。実際の境界 LINE は、隣接領域との接合点（T字交差等）の都合で
ポリゴンの厳密な角座標より少し外側まで伸びていることがあり（同じ `B CHAMBER` 上辺の例で、
実体の LINE が領域ポリゴンの角より左右に数十単位ずつ余分に伸びていた）、完全内包を要求すると
そうした実在の境界線を取りこぼす。本テストの周長カバレッジチェック
（`tests/regression/test_layer_consolidation.py::_region_perimeter_covered`）は元々この
「重なり」判定を使っており、実装側もこれに合わせたことで両者の「辺に乗っている」の定義が
一致した。

- **制限**:
  - 領域境界線が block 内にある場合は Boundaries に含まれない（LWPOLYLINE 展開も
    modelspace のみが対象）。
  - 実サンプル EE6868-500-01C.dxf・EE6888-602-01A.dxf・EE6492-631-02A.dxf・
    EE6888-631-01A.dxf・EE6313-546-01E.dxf は全領域の境界が完全捕捉されることを確認済み
    （後ろ3つは LWPOLYLINE 分解・軸判定許容誤差緩和・重なり判定化のいずれかが必要だった
    ケース）。`EE6313-545-01D.dxf` の `B CHAMBER`（2領域）は本コミットの対象外の別問題
    として残っている（region_detector 側で同名の領域が2件、わずかに異なるポリゴンとして
    重複検出されている可能性があり、layer_consolidator の修正では解消しなかった。別途調査
    が必要）。
- 回帰テスト: `tests/regression/test_layer_consolidation.py`（残存レイヤー・周の被覆・本数）。

### 回帰テストのサンプルDXF探索（共有プール対応、2026-06-23〜24）

サンプル DXF は `DXF-viewer`/`DXF-extract-labels`/`DXF-diff-manager` の3プロジェクトで
共用するため `Tools/sample-dxf/` に集約し、各プロジェクト直下に `sample-dxf -> ../sample-dxf`
の symlink を置いている（`.gitignore` 対象・非コミット）。`tests/regression/*.py` の
`_SAMPLE_DIR = os.path.join(_ROOT, 'sample-dxf')` 経由で参照する。

**sample-dxf/ は今後もファイル・フォルダの両方が増える前提**（まとまりが重要なセットは
新規サブフォルダとして保存される運用）。これに対応するため、汎用の自動探索（引数なし実行時）
は**トップレベルの `EE*.dxf`/`DE*.dxf` のみ**を見る（サブフォルダは見ない）。サブフォルダ
（`problems/`・`viewer-error/`・`pairC/` 等）は「まとまりが重要な特定用途のセット」という
意味で意図的に作られるものなので、汎用の自動探索が無差別に吸い込むべきではない、という方針。

一方、`EXPECTED`（`test_region_search.py`）・`EXPECTED_MIN_BOUNDARIES`
（`test_layer_consolidation.py`）のように**特定のファイル名を直接ハードコードしている
フィクスチャ**は、ユーザーが後からそのファイルを別サブフォルダに整理し直しても見つかる
必要がある。そのため `_find_sample(name)` という小さなヘルパー（直接パスを先に試し、
無ければ `os.walk(_SAMPLE_DIR)` で再帰的にファイル名一致を探す）を用意し、`main()` で
「トップレベルの自動探索結果」∪「`EXPECTED`系辞書のキーを `_find_sample` で解決した結果」
の和集合をテスト対象にしている。同じ `_find_sample` パターンを `DXF-extract-labels` の
`test_region_extraction.py`（`MULTI`/`SINGLE`/`ROTATED`/`DANGLING`）・
`test_drawing_number_types.py`（`EE6888-602-01A.dxf`）にも適用済み（各プロジェクトは
独立 git リポジトリのため、ヘルパー自体は小さくそれぞれのテストファイルに個別実装している）。

**実例**: 2026-06-23 にユーザーが `sample-dxf/` 内のファイルを `viewer-error/`・`problems/`・
`pairC/` へ再編成した際、上記の対応をしていなかったため `DXF-extract-labels` の
`test_region_extraction.py` で2件 FAIL・9件 skip が発生した（`EE6313-546-01E.dxf` 等が
`viewer-error/` に移動し、フラットパス固定の参照が解決できなくなったため）。`_find_sample`
導入後は再編成後も全件 pass に復旧することを確認済み。

**副次的に見つけた `all()` の短絡評価バグ**: `test_layer_consolidation.py`・
`test_region_search.py` の `main()` はいずれも `all(check_file(p) for p in paths)`
（ジェネレータ式）を使っていたため、最初に `False` を返したファイル以降は実際には
`check_file()` が呼ばれていなかった（`all()` の短絡評価）。リスト内包表記で全件を先に
評価してから `all()` に渡すよう修正し、隠れていた追加の失敗（`region_lines_lp` の
LWPOLYLINE 分解漏れ等、本節で先述の問題）を可視化した。

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
| `EE6313-545-01D.dxf` の `B CHAMBER` 重複検出（疑い） | 同名 `B CHAMBER` 領域が2件、わずかに異なるポリゴンで検出される。`test_layer_consolidation.py` の周長カバレッジチェックで判明。`region_detector.py` 側の閉領域検出（重複除外ロジック）の調査が必要（未着手）。 |

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

*最終更新: 2026-06-27（結合親矩形の除去（`_resolve_union_parents`）を追加。横/縦線分で2分割された兄弟矩形の合体親が planar graph の半面として誤検出されるケースを自動除去（`DE5401-405-21B.dxf` の L CHAMBER 重複、DXF-extract-labels v1.5.18 から移植）。`_detect_union_parents` + `_resolve_union_parents` を `_resolve_complement_faces` の直後（`analyze_dxf_regions` 内）に呼ぶ + 補完面解消（`_resolve_complement_faces`）を追加。兄弟矩形が縦辺を部分共有すると生じる補完面を検出・除去し、サブ領域に名称候補を継承する（`EE6313-545-01D.dxf` の B CHAMBER 重複検出バグを修正、DXF-extract-labels v1.5.17 から移植） + 図面枠の識別条件に color=7 を追加し `detect_drawing_frames` の
`min_side=400` 固定閾値を撤廃（サンプル137件で検証、退行0件・従来検出不可22件が解消。
DXF-extract-labels にも同じ修正を移植） + Consolidate Layers が領域線種の LWPOLYLINE を LINE/ARC に分解して
境界判定できるよう対応 + `_collect_region_edges` の軸判定許容誤差を `1e-6`→`1e-3` に緩和し
浮動小数点ノイズによる辺の取り落としを修正 + `_line_on_edges` を完全内包判定から重なり判定に
変更（テスト側の周長カバレッジチェックと定義を統一） + 回帰テストのサンプルDXF探索を
`sample-dxf/` 直下のみの自動探索＋`EXPECTED`系辞書の `_find_sample` 再帰解決の組み合わせに
変更し、サブフォルダへのファイル移動・新規フォルダ追加に追従できるようにした +
`test_layer_consolidation.py`/`test_region_search.py` の `all()` 短絡評価バグを修正 +
DXF handle 直接指定によるエンティティ検索「Search Handle」を追加（テキスト検索・境界検索と並列の第3モード、複数handle対応、`QAction.setIconText()` でツールバー3グループのラベルを短縮表示）+ ツールバーをユーザー希望の配置（1段目: Open+検索3グループ、2段目: 色変更系+Consolidate Layers+Export+Info）に再構成 + 矩形領域の辺ホバーハイライトを輪郭のみに限定 + Search Boundary に頂点座標リストでの検索を追加 + 閉領域検出で行き止まり枝を除去し頂点座標の重複アーティファクト・領域重複検出バグを解消 + 行き止まり枝を連結成分単位でグルーピング + 領域名候補の優先順位(Tier)制を導入 + 領域境界線の収集にPHANTOM等の線種除外を追加 + region_detector.py のモジュール性・可読性向けリファクタ + Search Boundary が最上位候補のみで照合するよう修正し領域名候補のTier1/2を領域内側のラベルに限定）*
