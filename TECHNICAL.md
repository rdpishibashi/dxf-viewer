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
  領域境界線（lineweight=25 / color=2＝ACI黄）を識別キーに、端点接続ベースの半面探索で
  閉領域を列挙し、下端横エッジ近傍のラベルから名称候補を付与する。DXF-extract-labels の
  同名モジュールを移植したもの（依存関数のみ自己完結化、アルゴリズム本体は同一）。
  設定は `DEFAULT_REGION_CONFIG`（DXF-extract-labels のデフォルト値）。

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

  この順序が必要な理由: EE6888-602-01A.dxf では小部品（コネクタ端子 9×15 等）が
  LWPOLYLINE/lw=25/color=2 で描かれており、これを境界線に混ぜると水平辺が縦境界線の
  corner-partner 判定を誤らせ gap-bridging を妨げる。LINE 優先で十分な図面では
  LWPOLYLINE を混入しないことで、この干渉を回避する。
- **マッチ**: `RegionSearchManager.find_matching_regions()` が入力名称を各領域の
  `default_name`＋`name_candidates` と照合（case sensitive / whole word 対応）。
- **キャッシュ**: `RegionSearchManager.get_analysis()` が解析結果を `DXFTab.region_analysis`
  に保持。初回のみ実行（大ファイルで数秒、ビジーカーソル表示）、2 回目以降は即時。
  解析は**ディスク上のファイルを読む**ため、ビューア上の dim（色書換え）の影響を受けない。
- **ハイライト（オーバーレイ方式）**: マッチ領域のポリゴンを QGraphicsItem の赤い輪郭線として
  シーンに重ね描画（`DXFViewerApp.draw_boundary_overlays()`）。doc を書き換えないため
  非破壊。非マッチ要素は既存の色書換え機構で dim。全マッチを一括表示し zoom-to-fit する。
- **永続ハイライト**: ダイアログの「Keep boundary highlight after Clear Search」が ON の場合、
  Clear Search で dim を戻した後も境界オーバーレイを残す。残した輪郭は
  `Search > Clear Boundary Highlight` で消去する。検索がアクティブな状態（dim 中）で
  Clear Boundary Highlight を押した場合は、オーバーレイ除去に加えて**元の色も復元**する
  （図面が dim 一色のまま残らないようにする）。
- **操作**: ツールバーの「Search Boundary...」「Clear Boundary Highlight」ボタン
  （`Search` メニューにも同項目あり。Ctrl+B でも起動）。
- **状態（`DXFTab`）**: `region_analysis`・`matched_regions`・`boundary_overlay_items`・
  `boundary_search_active`・`boundary_keep_highlight`。
- 回帰テスト: `tests/regression/test_region_search.py`（検出枠数・領域数・名称マッチ件数）。

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

*最終更新: 2026-06-17（LWPOLYLINE ホバーブロック修正 + Search Boundary の図面枠検出・LWPOLYLINE 境界 LINE 優先 2 パス対応 + Consolidate Layers LWPOLYLINE 制限を明記）*
