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
│   ├── main_window.py      # DXFViewerApp: タブ管理と各機能のオーケストレーション
│   ├── main_window_actions.py  # メニュー/ツールバー/ステータスバーの構築（ビルダー関数）
│   ├── boundary_overlay.py # 境界ハイライトのシーン描画（overlay・dim・zoom）
│   ├── viewer_widget.py    # PinchZoomCADViewer: 拡大縮小・パン・ジェスチャー対応
│   └── dialogs.py          # 全ダイアログ（検索・色変更・エクスポート等）を集約
├── core/
│   ├── tab_manager.py      # DXFTab: タブごとの状態管理
│   ├── color_manager.py    # エンティティ色操作（静的メソッド中心）
│   ├── search_manager.py   # テキスト検索・Handle検索・ハイライトロジック
│   ├── region_detector.py  # 矩形領域（直交ポリゴン）検出（DXF-extract-labels より移植）
│   ├── region_search_manager.py  # 領域検索（解析キャッシュ＋名称マッチ）
│   └── layer_consolidator.py  # レイヤー統合（Boundaries / Imported 化）
├── workers/
│   └── ezdxf_worker.py     # バックグラウンドスレッド（ezdxf コマンド実行）
└── utils/
    ├── file_utils.py       # ファイル検証・パス処理
    ├── app_utils.py        # アプリケーション初期化・シグナル定義
    ├── text_utils.py       # MTEXT/TEXT 書式コード除去・全角/半角正規化（検索一致用）
    └── export_utils.py     # DXF→画像エクスポート（PIL合成による背景色保証）
```

> 各パッケージの `__init__.py` は docstring のみ（re-export しない）。import は
> 常にサブモジュールを直接指定する（例: `from core.search_manager import SearchManager`）。

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
| `DXFViewerApp` | `ui/main_window.py` | メインウィンドウ、タブ管理、各機能のオーケストレーション |
| `PinchZoomCADViewer` | `ui/viewer_widget.py` | ezdxf の CAD ウィジェット拡張、ジェスチャー対応 |
| `DXFTab` | `core/tab_manager.py` | タブ 1 枚分の状態（ファイルパス・選択エンティティ等）|
| `ColorManager` | `core/color_manager.py` | エンティティ色の取得・変更（静的メソッド）|
| `SearchManager` | `core/search_manager.py` | テキスト検索・Handle検索・ハイライト（静的メソッド）|
| `RegionSearchManager` | `core/region_search_manager.py` | 領域検索：解析キャッシュ・名称マッチ（UI 非依存）|
| `EzdxfWorker` | `workers/ezdxf_worker.py` | ezdxf コマンドをバックグラウンドスレッドで実行 |

**`ui/main_window.py` 内の共通ヘルパー（2026-07-03 リファクタリング）:**

- `_current_tab_data(require_doc=False)` — アクティブタブの `DXFTab` 取得＋
  （必要なら）DXF 読込済み確認と "No File" 警告。各機能メソッド冒頭の共通処理。
- `_update_search_actions(tab_data)` — 検索系アクション（Clear/Next/Prev 等）の
  enabled 状態を tab_data の状態から一括更新。タブ切り替え時と各検索モードの
  開始・クリア後の両方から呼ぶ（個別 setEnabled の散在による更新漏れを防止）。
- `_step_search_result(results_attr, index_attr, step)` — テキスト検索と
  Handle 検索で共用する検索結果の巡回ナビゲーション。

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

**方針: すべての機能をツールバーのボタンから操作可能にする。** `ui/main_window_actions.py` の `create_toolbar()` は
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

### サイドバー（レイヤー表示・要素属性表示）の初期横幅縮小と固定幅化（2026-07-09 追加）

ezdxf `CADViewer.__init__` は右側パネル（`self.sidebar`。上下2段の垂直 `QSplitter` で、
上段がレイヤー一覧 `self.layers`（`QListWidget`）、下段が選択要素の属性・マウス座標
表示 `info_container`）を、外側の水平 `QSplitter`（`self.centralWidget()`。ezdxf 側では
ローカル変数 `container` で、`self` の属性としては保存されない）でコンテナ幅の 1/4 幅に
初期配置する。DXF-viewer はこれを `PinchZoomCADViewer._shrink_sidebar_width()`
（`ui/viewer_widget.py`）で2点調整する:

1. **初期横幅を ezdxf デフォルトの `SIDEBAR_WIDTH_SCALE`（65%）に縮小**
2. **ウィンドウリサイズでサイドバーの絶対幅が変わらないよう固定**
   （`container.setStretchFactor(0, 1)` で CAD ビュー側に、
   `container.setStretchFactor(1, 0)` でサイドバー側にリサイズ時の伸縮を割り当てる。
   `QSplitter.setStretchFactor()` は**リサイズ時**の余剰/不足スペースの配分にのみ効き、
   初回表示時のサイズには影響しない——そのため手動でのスプリッターハンドルのドラッグは
   引き続き可能）

```python
def _shrink_sidebar_width(self):
    container = self.centralWidget()
    sizes = container.sizes()
    cad_width, sidebar_width = sizes
    new_sidebar_width = int(sidebar_width * SIDEBAR_WIDTH_SCALE)
    new_cad_width = cad_width + (sidebar_width - new_sidebar_width)
    container.setSizes([new_cad_width, new_sidebar_width])
    container.setStretchFactor(0, 1)
    container.setStretchFactor(1, 0)
```

**なぜ `__init__` 内で同期的に呼べないか**: この時点ではまだ `PinchZoomCADViewer`
インスタンスは `main_window.create_new_tab()` の `tab_widget.addTab(tab.cad_viewer, ...)`
でタブに追加されておらず（`DXFTab()` コンストラクタ内で生成され、その戻り値を使って
呼び出し元がタブに追加する流れのため）、`self.centralWidget().width()` はまだ 0 を返す
（実測: ezdxf 自身の `container.setSizes([int(3*w/4), int(w/4)])` も `w=0` の状態で
呼ばれており、この時点の値は無意味）。`QTimer.singleShot(0, self._shrink_sidebar_width)`
で次のイベントループまで遅延させることで、タブに追加され実際にレイアウトされた後の
本当の幅を使って計算できる（実測: 1200×800 ウィンドウでタブ追加直後 `container.sizes()`
は `[894, 298]` ≈ 3:1 で確定しており、遅延実行後は正しくこの値を基準に縮小できる）。

回帰テスト: `tests/regression/test_sidebar_width.py`（起動時に65%へ縮小されること・
複数回のウィンドウリサイズでサイドバー幅が不変であること・複数タブそれぞれが独立して
縮小されること、の3ケース）。

### 要素属性表示・マウス座標表示の座標を小数点2桁に丸める（表示のみ、2026-07-09 追加）

ezdxf `CADViewer._on_element_hovered()` / `_on_mouse_moved()` は、選択エンティティの
DXF属性一覧（`selected_info`）・マウス座標ラベル（`mouse_pos`）の X/Y/Z 座標を
フル精度（`Vec3.__str__()` の桁数そのまま、マウス座標は `.4f`）で表示する。
`PinchZoomCADViewer` はこの2メソッドをオーバーライドし、座標のみ
`COORDINATE_DISPLAY_DECIMALS`（2）桁に丸める。半径・文字高さ・尺度・レイヤー名・
色番号等の非座標属性は ezdxf の元の精度のまま変更しない。

**表示専用であり内部処理には一切影響しない**: `_on_element_hovered()` は
`dxf_entity.dxf.all_existing_dxf_attribs()` を毎回その場で読み直すだけの
読み取り専用の文字列整形処理であり、結果をどこにも保存・キャッシュしない。
検索（`core/search_manager.py`）・領域検出（`core/region_detector.py`）・
ヒットテスト（`_ClickThroughBackend` 等の描画バックエンド）・エクスポート
（`utils/export_utils.py`）は、いずれもこのパネルの表示テキストとは無関係に、
ezdxf のドキュメントオブジェクトから座標を直接読み取る別経路であるため、
このパネルの表示桁数をいくら変えても他の処理の分解能には一切影響しない
（＝「表示だけを丸める」と「実際の座標データも丸める」は独立した話であり、
後者を追加で行う技術的必要性は無い。DXFファイルの実座標データ自体を書き換える
のは、画面上でのレンダリング精度・将来のエクスポート精度・ヒットテスト精度を
不必要に犠牲にするだけでメリットが無いため、あえて行わない）。

```python
def _format_dxf_attrib_value(value):
    """Vec2/Vec3（座標）値のみ2桁に丸める。radius/char_height 等の非座標
    float・str・int はそのまま。ezdxf 自身の表示（f"{value}" は Vec3.__str__()
    を呼び、"Vec3(x, y, z)" ではなく素の "(x, y, z)" タプル形式を返す）と
    同じ見た目を保ったまま丸める。"""
    if isinstance(value, (Vec2, Vec3)):
        ...  # 各成分を round() してから str(tuple) で ezdxf と同じ表記に戻す
    if isinstance(value, tuple) and 2 <= len(value) <= 3 and all(...):
        ...  # 念のため素の座標タプルも同様に扱う
    return str(value)  # 非座標属性はそのまま
```

**なぜテキストの正規表現置換ではなく値の型で判定するか**: ezdxf の表示コードは
DXF属性値を `f"{indent}- {key}: {value}\n"` で埋め込む——これは `value` の
`__str__()` を呼ぶ（`__repr__()` ではない）。`Vec3.__str__()` は `"Vec3(x, y, z)"`
ではなく素の `"(x, y, z)"` タプル形式を返す（`repr()` との違いを取り違えて
`"Vec3(...)"` 文字列にマッチする正規表現で最初に実装し、実データで検証した際に
誤りに気づいた）。この形式は非座標のプレーンタプル属性があった場合と文字列上
区別できないため、正規表現ではなく値の実際の Python 型で判定する。

`_on_element_hovered()` 自体は ezdxf `CADViewer._on_element_hovered()` の複製
（site-packages 内のサードパーティコードは直接編集できないため）。座標整形部分
（`_entity_attribs_string()` → `_entity_attribs_string_rounded()`）のみ差し替えて
おり、それ以外のロジックは元のまま。ezdxf 側の将来のフォーマット変更はここには
自動反映されない。

回帰テスト: `tests/regression/test_coordinate_display_rounding.py`
（`_format_dxf_attrib_value()`/`_entity_attribs_string_rounded()` の純粋関数
テスト＋実サンプルDXF5件でのヘッドレスGUIスモークテスト。直接配置エンティティ・
ブロック(INSERT)展開エンティティの両方、非座標属性が変更されないことを確認）。

### マルチタブ

- `QTabWidget` + `DXFTab` データクラスで管理
- タブ切り替え時に `DXFTab.viewer_widget` の参照を差し替える

**最後のタブを閉じてもアプリは終了しない（2026-07-09 修正）**:

`DXFViewerApp.close_tab(index)` は以前、`tab_widget.count() <= 1`（最後の1枚）の場合に
`self.close()` を呼んでいた。Qt の既定 `quitOnLastWindowClosed` によりメインウィンドウが
閉じるとアプリ全体が終了してしまい、「全タブを閉じたら起動時と同じブランク状態に
戻ってほしい」という期待と食い違っていた。

修正後は特別扱いをやめ、常に通常の `removeTab()` + `deleteLater()` のみを行う。
`QTabWidget` はタブが 0 枚になると `currentChanged(-1)` を自動発火し、既存の
`on_tab_changed` → `update_ui_for_active_tab()` の「現在タブなし」分岐
（`get_current_tab()` が `None` を返すケース）が、ウィンドウタイトルを `"DXF Viewer"`、
ステータスバーを `"Ready"` に戻し、ファイル依存アクションを無効化する——これは
`DXFViewerApp.__init__()` の起動直後と全く同じ状態（`create_status_bar()` の初期メッセージも
`"Ready"`）であるため、追加のリセット処理は不要だった。

`close_tab()` の呼び出し元は2箇所あり、どちらもこの修正で挙動が揃う:
1. `tab_widget.tabCloseRequested`（タブの × クリック）
2. `load_dxf()` のエラー復旧パス（`ezdxf.readfile()` 失敗時、作成直後のタブを削除）
   — 副次的に、他にタブが無い状態で不正なDXFファイルを開こうとした場合もアプリが
   終了しなくなった。

明示的な終了操作（File > Exit、`QKeySequence.Quit`）は `window.close` を直接呼ぶ別の
アクションで、この修正の影響を受けない。

回帰テスト: `tests/regression/test_close_all_tabs.py`（複数タブから最後の1枚を閉じる／
単独タブを閉じる／`load_dxf()` エラー復旧パスの3ケース。`QApplication` インスタンスを
モジュールレベル変数に保持する必要がある点に注意——`QApplication.instance() or
QApplication([])` を式文のまま（変数に代入せず）実行すると参照がすぐガベージコレクトされ、
直後の `QWidget` 生成が `"QWidget: Must construct a QApplication before a QWidget"` で
fatal crash する PyQt5 の既知の落とし穴）。

### レイアウト切替（`ui/viewer_widget.py` + `ui/main_window.py`、2026-07-12 追加）

**背景**: 一部のDXFファイルは、タイトルブロック（図番・タイトル文字）をModel空間ではなく
別のペーパースペース・レイアウトに配置している（例: `EE6492-464-01B.dxf` は
"ICADSX Layout" というレイアウト内のINSERTブロック `JZB_0001` にタイトルブロックを持つ。
`doc.layouts.names_in_taborder()` → `['Model', 'ICADSX Layout']`）。DXF-extract-labelsの
`determine_drawing_number_types()` はMODEL_SPACE/PAPER_SPACE/BLOCKSを横断的に走査するため
これを抽出できるが、DXF-viewerは`ezdxf.addons.drawing.qtviewer.CADViewer.set_document()`が
既定で描画する `layout="Model"` のみを表示しており、かつ`PinchZoomCADViewer.__init__()`が
ezdxf純正の「Select Layout」メニューをmacOSのグローバルメニューバーに紛れ込ませないために
`self.menuBar().hide()` していたため、Paperレイアウトへ切り替える手段がUI上に一切
存在しなかった（描画エンジンの限界ではなく、メニュー非表示化の際に代替UIを用意していな
かったことが原因）。

**実装**:
- `ui/main_window_actions.py` の `create_toolbar()` に `QComboBox`
  （`window.layout_combo`）を2段目ツールバーの末尾（Infoの後ろ）に追加。
- `ui/viewer_widget.py` の `PinchZoomCADViewer.current_layout_name()`（新規）は
  `self._cad.current_layout`（ezdxfの`CADWidget`が持つ公開プロパティ）を返す薄い
  ヘルパー。`_cad`自体はezdxf `CADViewer`の非公開属性だが、既存の
  `_install_click_through_backend()` が同じ属性を直接参照している前例を踏襲。
- `ui/main_window.py`:
  - `_sync_layout_combo(tab_data)`（新規）: `tab_data.dxf_doc.layouts.names_in_taborder()`
    でコンボを再構築し、現在のレイアウトを選択状態にする。`update_ui_for_active_tab()`
    から呼ばれるため、タブ切替時・ファイルを開いた直後の両方で同期される。各タブは
    自前の`PinchZoomCADViewer`（＝ezdxfの`CADWidget`）を持ち、現在のレイアウトも
    タブごとに独立して保持されるため、タブ間の状態混線を気にする必要はない。
    コンボ再構築中は`blockSignals(True)`で`on_layout_changed`の誤発火を防ぐ。
  - `on_layout_changed(name)`（新規）: `tab_data.cad_viewer.draw_layout(name,
    reset_view=True)` を呼ぶ（`draw_layout`はezdxf `CADViewer`の公開メソッド）。

**`refresh_viewer()` のレイアウト保持修正（重要・既存機能への回帰防止）**:

`refresh_viewer()` はSearch Text/Handle/Boundary・Color変更/復元・Consolidate Layers・
Clear系など**9箇所**から呼ばれる共通の再描画処理で、修正前は
`tab_data.cad_viewer.set_document(tab_data.dxf_doc, auditor)` と`layout`引数を
省略していた（＝常に`"Model"`を描画）。レイアウト切替機能を追加する前はModel以外を
表示する手段が無かったため問題化していなかったが、そのまま追加すると
**Paperレイアウト表示中にこれら9箇所のいずれかを実行するたびに画面が黙ってModelへ
戻ってしまう**という回帰を生む。修正は次の1箇所:

```python
tab_data.cad_viewer.set_document(
    tab_data.dxf_doc, auditor,
    layout=tab_data.cad_viewer.current_layout_name())
```

なお、Search Text/Handle/Boundary・Color変更・Consolidate Layersは**今回意図的に
拡張していない**——従来通りmodelspace専用のまま。レイアウト切替はあくまで「表示」
機能であり、これらの検索/色変更/レイヤー統合ロジックの対象範囲を広げるものではない。
Paperレイアウト表示中にこれらを実行しても表示は維持されるが、対象エンティティが
画面上に存在しないため見た目の変化はない（クラッシュはしない。回帰テストで確認済み）。

**ACI色7（黒/白自動切替）がPaperレイアウトで黒に解決され不可視になる不具合の修正**:

上記の実装をユーザーが実際に試したところ、"ICADSX Layout" に切り替えてもタイトル文字
（`ＳＴＡＮＤＡＲＤ＿ＤＲＡＷＩＮＧ...`）が表示されない、という報告を受けた。
原因はレイアウト機能そのものではなく、ezdxfの`RenderContext`が持つ既定の背景色前提との
不整合だった: ezdxfの`LayoutProperties.from_layout()`はModel空間を「暗い背景」、
ペーパースペースのレイアウトを「明るい背景（印刷用紙）」と仮定しており、ACI色7
（"adapts to background"）はこの仮定に応じて解決される——Model空間では白、
ペーパースペースでは黒。一方DXF-viewerは常に固定の黒背景（`set_background_color
(QColor(0,0,0))`）を使っており、`set_background_color()`はQtの描画ブラシを変えるだけで
ezdxfの`RenderContext`には一切伝わらない。`EE6492-464-01B.dxf`の"ICADSX Layout"の
タイトルブロック（罫線・文字全て）はACI色7で統一されていたため、切り替えた瞬間に
黒背景の上で黒色に解決され完全に不可視になっていた（実際にレンダリング結果の
`QGraphicsItem.pen()/brush()`を検証し、全アイテムが`#000000`であることを確認）。
Model空間はこれまでこの前提とDXF-viewerの黒背景がたまたま一致していたため
表面化していなかった。

修正: `PinchZoomCADViewer._install_dark_background_render_context()`（新規）で
`CADWidget._make_render_context()`をラップし、生成された`RenderContext`の
`set_current_layout()`をさらにラップして、呼び出しのたびに
`current_layout_properties`を`LayoutProperties(layout.name, "#000000", units=...)`
（暗い背景・白前景）へ強制的に上書きする。レイヤープロパティに既存の
`set_layer_properties_override()`のような上書きフックが無いため、
`_install_click_through_backend()`と同じ「メソッドをラップして差し替える」
パターンを踏襲。Model空間の挙動は変わらない（元々暗い背景前提のため無変更）。

**既知の未対応範囲（意図的にスコープ外）**: 「Change Background Color」で背景色を
ユーザーが変更しても、ezdxfの`RenderContext`側の色解決には反映されない
（`change_background_color()`はQtブラシを変えるだけ）。これはModel空間側にも
今回の変更前から存在する潜在的な不具合（例えば背景を白に変えるとACI色7のエンティティが
白のまま＝白背景に白文字で見えなくなる）だが、今回の修正は「DXF-viewerが常に使う
固定の黒背景」という現状の実際の既定値にPaperレイアウトの解決を合わせることに
限定し、背景色変更機能とezdxfの色解決を動的に連動させる対応は行っていない
（今回の報告の再現に不要かつ別範囲の課題のため）。

回帰テスト: `tests/regression/test_layout_switching.py`
`run_switching_layout_shows_title_block_text()`にタイトルブロック領域内の
`QGraphicsItem`のpen/brush色を検証するチェックを追加（意図的に修正を無効化した
コピーで実際に検出できることを確認済み）。

回帰テスト: `tests/regression/test_layout_switching.py`（コンボのレイアウト一覧・
デフォルトModel選択・レイアウト切替・`refresh_viewer()`のレイアウト保持・
マルチタブでのコンボ独立性・Export/File Info相当のアクセスが無干渉であることを確認）。

### レイアウトの初期選択自動化（`ui/main_window.py`、2026-07-13 追加）

**背景**: 組立図等、ICADSXというCADツールで作成されたDXFファイルは、罫線・
タイトルブロック・寸法込みの完成図が Model空間ではなく "ICADSX Layout" という
名前のペーパースペースレイアウトに、VIEWPORTエンティティ（Model空間の内容を
正しい縮尺・配置で参照・合成する）経由で構成されている。Model空間自体には
同じ部品図形が罫線・タイトルブロック・寸法なしのまま未整理で散在しているだけで、
単独では閲覧に適さない。レイアウト切替コンボ（上記節）は既に手段としては
存在していたが、既定表示が常に"Model"だったため、該当ファイルを開くたびに
手動でコンボを"ICADSX Layout"に切り替える必要があった。

**検証**: 実サンプル20ファイル（`339_Unit内結線図`フォルダ、`EE6492-464-01B.dxf`を
含む）全てで、"ICADSX Layout"という名前のレイアウトが存在する場合は必ず
VIEWPORTエンティティを1個以上持ち、実際にレンダリングして視覚確認したところ
罫線・タイトルブロック・寸法込みの完成図であることを確認した。一方、回路図系
（`405_展開接続図`フォルダ、23ファイル）は1件も"ICADSX Layout"を持たない。
このため「"ICADSX Layout"という名前のレイアウトが存在するかどうか」のみで
判定して問題ない（VIEWPORT数や実体数による判定は不要——エンティティ数で見ると
ICADSX Layout側はModel空間よりむしろ少ないため、素朴なエンティティ数比較では
誤判定する）。

**実装**: `ui/main_window.py`の`_initial_layout_name(doc)`が
`doc.layouts.names_in_taborder()`に`"ICADSX Layout"`が含まれていればそれを、
無ければ`"Model"`を返す。`load_dxf()`が`set_document()`を呼ぶ際にこの結果を
`layout=`引数として渡す（変更箇所はここ1箇所のみ——`refresh_viewer()`は
既存のレイアウトを保持する実装のため無影響）。レイアウト選択コンボは手動での
確認・上書き手段として残置（実運用の全ファイルを網羅検証したわけではないため）。

サンプル236ファイル（組立図系71・回路図系23・`sample-dxf`142）全件で
自動判定を検証し、エラー0件・"ICADSX Layout"自動選択20件・"Model"維持216件を
確認済み。

回帰テスト: `tests/regression/test_layout_switching.py`
（`run_combo_populated_with_layouts()`の既定選択アサーションを"ICADSX Layout"に
更新、`run_file_without_icadsx_layout_still_defaults_to_model()`を新設）。

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
- **全角/半角非依存マッチング（`utils/text_utils.normalize_width()`、2026-07-03 追加）**:
  検索語・比較対象の両方に `unicodedata.normalize('NFKC', ...)` を適用してから比較する
  （`Ａ`→`A`、`１`→`1`、全角スペース/スラッシュ→半角 等。かな・漢字は対象外）。半角で
  入力した検索語が全角のみのラベル（例 `ＳＹＳＴＥＭ　Ｉ／Ｆ　ＢＯＸ`）にヒットし、
  逆に全角で入力した検索語が半角ラベルにもヒットする。表示・ハイライト対象の
  `entity_text` 自体は元の全角/半角のまま変更しない（比較用のローカルコピーのみ正規化）。
  `RegionSearchManager.find_matching_regions()`（Search Boundary）にも同じ正規化を適用。
  回帰テスト: `tests/regression/test_mtext_clean_search.py`（`WIDTH_CASES`・
  `check_width_insensitive_search`）、`tests/regression/test_region_search.py`
  （`EE6868-500-01C.dxf`/`EE6492-039-38A.dxf` に双方向クエリを追加）。

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

  **L字型領域の名称検出（2026-07-03 追加・DXF-extract-labels v1.5.27 から移植）**

  `EE6491-039-04A.dxf` の `SYSTEM I/F BOX`（FLAT CABLE 部と一体のL字型領域、71.3%）
  が Search Boundary でヒットしない問題への対応として2点を移植:

  1. `_notch_bottom_edges()`: L字型等の非矩形ポリゴンの「切り欠き部の下向き横エッジ」
     （最下端レベル以外にある、エッジ中点の直上が領域内・直下が領域外のエッジ）を
     検出し、`region_name_candidates()` の Tier2 スキャン対象を
     `_top_edges() + _notch_bottom_edges()` に拡張。この図面の名称ラベルは切り欠き
     水平線（LINE #7DE、y=124.76。最下端は y=13.24）の直上 3.5 にあり、最下端/
     最上端しか見ない従来の Tier1/2 では候補から漏れていた。長方形では下向き
     エッジは最下端にしか存在しないため挙動不変。
  2. `_remove_overlap_claimed_candidates()`: 重なる（`regions_overlap`）領域間で
     同じ候補テキストを距離の近い側にのみ残す整理（DXF-extract-labels v1.5.14
     相当。`default_name_tier` を持たない viewer 版に合わせ Tier 再計算は省略）。
     `analyze_dxf_regions()` の最終段（`_resolve_union_parents` の後）で呼ぶ。
     これが無いと、L字の最下端エッジ近傍（Tier1）にあるネスト領域
     `HEATER CTRL B.D` の名称がL字側の default に残り、`default_name` のみ照合
     する `find_matching_regions()` で `SYSTEM I/F BOX` がヒットしない。整理後は
     各名称がそれを最も近距離で持つ領域の default になる（`SYSTEM I/F BOX` →
     L字領域、`HEATER CTRL B.D` → ネスト領域、各1件ヒット）。

  `tests/regression/test_region_search.py` に `EE6491-039-04A.dxf` の期待値
  （frames=1 / min_regions=2 / `SYSTEM I/F BOX`=1件・`HEATER CTRL`=1件・
  `FLAT CABLE`=0件〔第2候補には残るが default ではない〕）を追加。既存図面の
  検出件数・検索結果は全て不変（回帰テスト4スクリプト PASS）。

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
  `analyze_dxf_regions()` は次の順で検出する（**「候補ゼロ」判定は図面枠単位**。下記
  「フォールバック発動判定を図面枠単位に修正」参照）:
  1. **LINE のみ**で検出。
  2. 閾値超え候補ゼロだった図面枠に限り、LWPOLYLINE 境界線があれば **LINE+LWPOLYLINE**
     で再検出。
  3. それでも閾値超え候補ゼロだった図面枠に限り、図面全体が90°回転している場合のみ
     横線分ギャップ橋渡しを有効にして再検出（下記「90°回転図面対応」参照）。

  **フォールバック発動判定を図面枠単位に修正（2026-07-12・DXF-extract-labels v1.7.11 から移植）**

  上記2)3)のフォールバックは、修正前は「**ファイル全体**を合算して1件でも閾値超え
  候補があるか」で発動を判定していた（`_count_threshold_hits(frame_cands,
  single_thr) == 0`）。この場合、1ファイルに複数図面枠を含むファイルで、フォール
  バックを必要としない図面枠（通常向きで普通に検出できる図面枠）が1つでも先に閾値を
  超えると、ファイル全体では「候補あり」と判定され、実際にフォールバックを必要と
  する**別の**図面枠（90°回転コンテンツを持つ図面枠等）が永久に救済されない不具合が
  あった。

  DXF-viewer の Search Boundary で `DE5434-553-10B.dxf`（図面枠5個）の図面2/3にある
  `CONTROL BOX CORE FX`/`RX` が検出されない、とユーザーが報告して発覚。この図面は
  90°回転コンテンツ（フォールバック3が必要）だが、同じファイル内の別図面枠
  （LA/LB CHAMBER 等）が先に閾値を超えるため、`analyze_dxf_regions()` の既定値
  `area_ratio=0.15`（`DEFAULT_REGION_CONFIG`）では偶然フォールバック不要なだけの
  候補が全体判定を「候補あり」にせず正しく動いていたが、Search Boundary が実際に
  使う既定値 `area_ratio=0.10`（`RegionSearchManager._DEFAULT_AREA_RATIO`）では、
  この低い閾値でファイル内の他の図面枠がより多くの候補を拾ってしまい、フォール
  バック自体が発動しなくなっていた。「面積閾値を下げると検出できなくなる」という
  非単調な挙動が原因調査の手がかりになった。

  修正: 4パス目（レベル汚染フォールバック、下記参照）が既に使っている
  「`zero_fis`（閾値超えゼロの図面枠インデックスのみ）で再検出し `frame_cands` へ
  差し戻す」パターンを、2)3)のフォールバックにも適用。4パス目と異なり「採用条件
  （名称が他枠の既検出名と一致）」は課さない（2)3)は検出完全性のためのパスであり、
  4パス目のノイズ除去とは性質が異なるため）。副産物として、発動判定にのみ使われて
  いた `_count_threshold_hits()` ヘルパーは完全に不要になったため削除。

  回帰テスト: `tests/regression/test_region_search.py` に
  `check_search_boundary_default_area_ratio()` を新設。`EXPECTED` の
  `DE5434-553-10B.dxf` チェック（`analyze_dxf_regions()` の既定値 `area_ratio=0.15`
  を使う）は修正前から通っていたため、Search Boundary が実際に使う
  `area_ratio=0.10` を明示的に検証しないと退行を検知できない。修正前のコードで
  確実に失敗することも確認済み。

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
  （`ui/boundary_overlay.py` の `draw_boundary_overlays()`）。doc を書き換えないため非破壊。
  加えて `highlight_matched_labels()`（同モジュール）が `matched_labels` の座標を使い、検索した文字列
  そのもの（領域名のラベルエンティティ）も赤に色書換えする（プレーンテキスト検索の
  `SearchManager.apply_search_highlighting()` と同じ赤＝color index 1 / true_color
  0xFF0000）。`dim_all_entities()` の直後・`refresh_viewer()` の前に呼ぶことで dim 後に
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
    領域には `matched_labels` が無いため、`highlight_matched_labels()` はラベル文字列の
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

**境界線ちょうどのラベルが領域から漏れる不具合の修正（2026-07-23・DXF-extract-labels
から移植）**

`_point_in_polygon`（ラベルの領域内包判定、ray casting）は境界線ちょうどにある点を
浮動小数点誤差（1e-7オーダー）次第で内外どちらにも倒す実装だった。DXF-extract-labels
側で、同一図面フォーマットの2図面（`EE6888-637-01A.dxf`／`EE6491-039-21A.dxf`）で
`CNPG01`の座標が前者は領域境界から0.375離れているのに後者はちょうど境界線上（差
約2e-7）となっており、後者だけ領域外と誤判定されて出力の個数が0になる不具合が
ユーザーから報告された。`_dist_point_to_polygon`で境界からの距離が`boundary_eps`
(1e-4)以内なら無条件に内側と判定するよう変更して解消。`_point_in_polygon`の他の
呼び出し元（`regions_overlap`用の`tol=1.0`、`_notch_bottom_edges`用の`probe=0.5`、
名称候補の領域内判定）はいずれも許容誤差が桁違いに大きく、この変更による影響を
受けない。DXF-viewer側にも同一の脆弱な実装が存在したため同じ修正を移植し、
`tests/regression/test_region_search.py`に回帰チェックを追加。

**図面枠が見つからない図面で`labels`が空になる不具合の修正（2026-07-23・
DXF-extract-labelsから移植）**

`analyze_dxf_regions()`は図面枠が見つからない場合、`result['labels']`を空の
まま return していた（「領域探索は図面枠が無いと続行できない」という理由で、
ラベル収集自体もまとめて諦めていた）。DXF-extract-labels側で、`build_region_results()`
（同プロジェクトの「機器符号（候補）以外も抽出」ON時に使用、`analysis['labels']`
のみでラベルを集計する）がこの図面のラベルを一切集計できず、複数図面を一括入力
すると図面枠が見つからない図面だけラベルが0件になり出力から消える不具合として
発覚した（`EE6892-455B.dxf`、Model/Paper Space分離で図面枠が見つからない図面）。
`_collect_all_labels_fallback()`（DXF-extract-labels側）と同じ「枠制約なし・
重複除去のみ」の方針で`labels`を埋めるよう修正し、DXF-viewer側にも同じ変更を
移植した。ただし**DXF-viewer には`analysis['labels']`を消費する機能が無いため
（Search Boundaryは領域が検出できて初めて機能する）、この移植は実際の挙動には
影響しない**——将来`labels`単体を使う機能が追加された際の一貫性のための移植。
また DXF-viewer の `_collect_region_geometry()` は Model Space のみを対象とし
（DXF-extract-labels 側の Model/Paper Space 自動選択 `select_layout_result()` は
未移植）、このフォールバックの対象も Model Space に限られる。

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

### エクスポート（`utils/export_utils.py`）

- `matplotlib` レンダリング＋ PIL 合成でカスタム背景色を保証
- 出力形式: PNG / SVG / PDF
- 旧 `export_utils_v2.py` を改名したもの（未使用だった旧版は 2026-07-03 に削除）

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
| Streamlit Cloud 非対応 | デスクトップ GUI アプリのためクラウドデプロイ不可 |
| `EE6313-545-01D.dxf` の `B CHAMBER` 重複検出（疑い） | 同名 `B CHAMBER` 領域が2件、わずかに異なるポリゴンで検出される。`test_layer_consolidation.py` の周長カバレッジチェックで判明。`region_detector.py` 側の閉領域検出（重複除外ロジック）の調査が必要（未着手）。 |
| **LINE 矩形の部品輪郭（未対応課題）** | `DE5434-563-03A.dxf` のように、lw=25/color=2 の LINE エンティティ 4 本で形成された「細い閉じた矩形（部品輪郭）」（実例: x=81~90, y=98~394.5、幅9単位）が領域境界線と同じ属性を持つ場合、アルゴリズムが部品輪郭と領域境界線を区別できない。部品輪郭の両端が縦仕切りを形成するケースでは、左右の子領域を独立した閉領域として検出できない。**将来対応案**: lw=25/color=2 が形成する「縦横比が高い閉矩形」を部品輪郭として自動判定し検出対象から除外する。あわせて、合体親領域の名称探索に「子領域の名称候補を除外した上で、底辺中央により近いラベルを優先する」ロジックを追加する（DXF-extract-labels v1.5.19 既知課題参照）。 |
| Search/Color/Consolidate Layers はペーパースペースを対象としない | レイアウト切替（2026-07-12追加）はあくまで表示機能。Search Text/Handle/Boundary・Color変更/復元・Consolidate Layersは従来通りmodelspace専用のまま拡張していないため、Paperレイアウト表示中にこれらを実行してもクラッシュはしないが、対象エンティティが画面上に存在せず見た目の変化がない。詳細は「レイアウト切替」節参照。 |

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

*最終更新: 2026-07-16（ユーザー報告: DXF-extract-labelsでは最小領域サイズ3%で
`CM DRV`領域を抽出できるのに、DXF-viewerでは1%にしても認識できない。原因は
`core/region_detector.py`の領域名候補フィルタが3箇所で正規化（`normalize_width`）
未適用のままだったこと（全角/半角対応は`_count_letters`のみ移植され、
`filter_non_circuit_symbols()`・`_filter_eligible_labels()`・
`_is_valid_name_candidate()`の判定文字列`up`の正規化が漏れていた——2026-07-03の
全角/半角対応が部分的にしか移植されていなかった）。全角の機器符号
（`ＤＯＵＴ４（ＭＯＶＥ）`等）・全角除外語（`ＮＯＴＥ`）が正規化なしのASCII前提
パターンに一切マッチせず素通りし、`CM DRV`領域の正しい名称候補を押しのけて
誤った候補が採用されていた。3箇所に`normalize_width()`適用を追加し
primaryと同一の判定に統一。あわせて`DEFAULT_REGION_CONFIG['connection_point_margin']`
を0.1→0.05に変更しprimaryと統一（気づかれていなかった別の設定値drift）。
`EE6888-650-01C.dxf`で`CM DRV`領域名がprimaryと完全一致することを確認、
全回帰テストPASS。再発防止として、`DXF-extract-labels/tests/regression/`に
両プロジェクトの領域名検出結果を実データで突き合わせるクロスプロジェクト
一貫性テストを新設（詳細は`DXF-extract-labels/TECHNICAL.md`参照）。）*

*最終更新: 2026-07-15（`core/region_detector.py` に DXF-extract-labels primary
v1.9.0 の変更を移植。**(1)** 面積比較を整数%（四捨五入）・`>=` で行う
`_area_ratio_met()` を導入し、`DEFAULT_REGION_CONFIG['area_ratio']` を
0.15→0.05に変更。**(2)** area_ratio引き下げに伴い、90°回転橋渡しパス・
レベル汚染フォールバック・LWPOLYLINE追加パスの発動ゲートが、単独採用には
満たない小さな候補だけでヒット扱いされ発動しなくなる副作用が生じたため、
area_ratioとは独立の`gate_ratio = max(area_ratio, 0.15)`で判定するよう変更。
LWPOLYLINE追加パスは、corner-partner判定を乱して既存の正しい検出結果を
壊す副作用があるため、「置き換え」ではなく「bboxが未出現の候補だけ追加する」
合算方式（`_merge_cands_lists`）に変更。**(3)** `_force_include_union_children`
（合体親バイパス採用）に、合体親自身が単独面積閾値を満たす場合のみという
ゲートを追加。**(4)** 領域名称候補（`_filter_eligible_labels`・
`_is_valid_name_candidate`の両方）に、1文字目が"("（全角"（"含む）のラベルを
除外する判定を追加。**(5)** `_resolve_complement_faces`を、同じ合体面
（large_i）に対して複数のsmall_iパートナーが二重マッチする場合に、面積最大の
small_iのみを基準面として使うよう修正（二重領域・誤命名を防止）。
`RegionSearchManager._DEFAULT_AREA_RATIO`・ダイアログ spinbox デフォルト・
`get_analysis`呼び出し側のデフォルト渡し（計3箇所）も 0.10→0.05 に変更
（primaryのarea_ratio既定値変更に合わせてSearch Boundaryの既定値も引き下げ、
ユーザー指示）。`EE6868-500-01C.dxf`でarea_ratio=5%化により新たに検出される
2領域（'RACK1'・'MPD RACK2 PANEL LIMIT'）分、`test_region_search.py`の
'RACK1'/'MPD'クエリ期待値を更新。全回帰テスト（8スクリプト）PASS。詳細は
「領域検索 / Boundary Search」節参照。）*

*過去の更新: 2026-07-13（"ICADSX Layout"を持つファイル（組立図等）を開いた際、
初期表示レイアウトを従来の"Model"から"ICADSX Layout"へ自動選択するよう変更。
Model空間には罫線・タイトルブロック・寸法を持たない未整理の部品図形しかなく、
完成図はVIEWPORT経由で"ICADSX Layout"側に構成されているため、従来は毎回手動での
レイアウト切替が必要だった。実サンプル20ファイルで検証しVIEWPORT数によらず
"ICADSX Layout"という名前の存在のみで判定できることを確認。レイアウト選択
コンボ自体は手動上書き用に残置。詳細は「レイアウトの初期選択自動化」節参照。）*

*過去の更新: 2026-07-12（`core/region_detector.py`: 矩形領域検出の3パスフォールバック
（LWPOLYLINE追加・横線分ギャップ橋渡し）の発動判定をファイル全体からフレーム
（図面枠）単位に修正（DXF-extract-labels v1.7.11 から移植）。ファイル全体の
合算判定では、フォールバック不要な図面枠が1つでも先に閾値を超えると、本当に
フォールバックが必要な別の図面枠（90°回転コンテンツ等）が永久に救済されない
不具合があった。Search Boundaryで`DE5434-553-10B.dxf`の`CONTROL BOX CORE FX`/
`RX`が検出されない報告（area_ratioを10%→15%に変えると検出できるという非単調な
挙動が手がかり）を調査して発覚。`tests/regression/test_region_search.py`に
`check_search_boundary_default_area_ratio()`を新設、修正前コードで確実に失敗
することも確認済み。詳細は「LWPOLYLINE 境界対応」節の「フォールバック発動判定を
図面枠単位に修正」参照。）*

*過去の更新: 2026-07-12（レイアウト切替機能を追加。一部のDXFファイル（例:
`EE6492-464-01B.dxf`）はタイトルブロックをModel空間ではなくペーパースペースの
レイアウト（"ICADSX Layout"）に配置しており、DXF-viewerは`layout="Model"`しか
描画せず、かつezdxf純正の「Select Layout」メニューをmacOSグローバルメニュー
バー対策で非表示にしていたため、その内容を表示する手段がUI上に存在しなかった
（描画エンジンの限界ではなく代替UIの不足）。`ui/main_window_actions.py`の
ツールバーに`QComboBox`（レイアウト選択）を追加、`ui/viewer_widget.py`に
`PinchZoomCADViewer.current_layout_name()`ヘルパーを追加、`ui/main_window.py`に
`on_layout_changed()`/`_sync_layout_combo()`を追加しタブごとに独立して
レイアウト選択状態を同期。**重要な既存機能への回帰防止**: Search Text/Handle/
Boundary・Color変更/復元・Consolidate Layersが共有する`refresh_viewer()`
（9箇所から呼び出し）が`layout`引数を省略し常に`"Model"`を再描画していたため、
このまま放置するとPaperレイアウト表示中にこれらの操作を1つでも実行すると画面が
黙ってModelへ戻ってしまう回帰を生むところだった。`layout=tab_data.cad_viewer.
current_layout_name()`を明示的に渡すよう修正して回避。Search/Color/Consolidate
Layers自体は今回拡張せず、従来通りmodelspace専用のまま。回帰テスト
`tests/regression/test_layout_switching.py`を新設（コンボのレイアウト一覧・
デフォルトModel選択・レイアウト切替・`refresh_viewer()`のレイアウト保持・
マルチタブでのコンボ独立性を確認）。詳細は「レイアウト切替」節参照。）*

*（同日: 上記レイアウト切替機能をユーザーが実際に試したところ、Paperレイアウトへ
切り替えてもタイトル文字が表示されない不具合が発覚し追加修正。原因はezdxfの
`RenderContext`がModel空間を「暗い背景」・ペーパースペースを「明るい背景（印刷用紙）」
と仮定しており、ACI色7（黒/白自動切替）をこの前提で解決するため——DXF-viewerは
常に固定の黒背景を使うが`set_background_color()`はQtの描画ブラシを変えるだけで
ezdxfには伝わらず、"ICADSX Layout"のタイトルブロック（罫線・文字全てACI色7）が
黒背景の上で黒色に解決され不可視になっていた。`PinchZoomCADViewer
._install_dark_background_render_context()`を追加し、`CADWidget
._make_render_context()`をラップして`RenderContext.set_current_layout()`が
毎回`current_layout_properties`を暗い背景・白前景に上書きするよう修正
（`_install_click_through_backend()`と同じラップパターン）。Model空間は元々
この前提と一致していたため無変更。回帰テストに色検証を追加し、修正を無効化した
コピーで実際に検出できることを確認済み。詳細は「レイアウト切替」節参照。）*

*（同日: `core/region_detector.py`: 単独面積が閾値未満・かつ互いに異なる
名称を持つ兄弟矩形が Search Boundary の検出結果から消える不具合を修正
（DXF-extract-labels v1.7.5 から移植）。実例: `DE5434-563-03A.dxf` の
`CN I/F B.D TYPE3 (CN-IF3-1A)`（面積比7.63%）が `SB-1A(FX1)`（7.7%）と並ぶ
兄弟矩形で、どちらも単独の面積閾値未満・名称が異なるため同名2ピース合算の
対象にもならず検出されなかった（合体親〈15.3%〉がたまたま `SB-1A(FX1)` と
同名候補を共有した場合のみその兄弟だけが救済され、もう一方は候補にすら
残らなかった）。`_force_include_union_children()` を新設し、合体親検出
（`_detect_union_parents`）を面積フィルタより前の生候補リストに適用、確認できた
合体親の子は面積閾値を問わず採用する。補完面ペア（`_detect_complement_pairs`）と
競合する三つ組は対象から除外し、`EE6313-545-01D.dxf` の B CHAMBER 二重検出を
回避。`DEFAULT_REGION_CONFIG['area_ratio']` の既定値も 0.20→0.15 に変更（primary
側と同期。ただし Search Boundary は既に `RegionSearchManager._DEFAULT_AREA_RATIO`
=0.10 を独自に使っており、この既定値変更自体の実挙動への影響は無い）。
アルゴリズム本体は primary（DXF-extract-labels）と同一に保つ方針のため、
テストは primary 側の回帰テスト
`test_under_threshold_named_siblings_both_recovered_via_union_parent` で担保。）*

*過去の更新: 2026-07-09（`ui/viewer_widget.py`: 要素属性表示パネル・マウス座標表示の
X/Y/Z座標を小数点2桁（`COORDINATE_DISPLAY_DECIMALS`）に丸めて表示するようにした
（`PinchZoomCADViewer._on_element_hovered()`/`_on_mouse_moved()` が ezdxf 本体の
同名メソッドをオーバーライド。Vec2/Vec3型の値のみ丸め、radius/char_height等の
非座標属性は元の精度を維持）。**表示のみの変更で内部処理・保存データには一切
影響しない**——エンティティ属性はホバーの都度 ezdxf ドキュメントから読み直す
だけの読み取り専用処理で、検索・領域検出・ヒットテスト・エクスポートは
いずれもこのパネルとは無関係に座標を直接読み取るため、実座標データを
追加で丸める技術的必要性は無いと判断し行っていない（ユーザーからの
「内部処理も丸めるべきか」という問いに対する検討結果）。当初は `"Vec3(...)"`
文字列に対する正規表現置換で実装しようとしたが、ezdxf の表示コードは
`Vec3.__str__()`（`"Vec3(...)"`ではなく素の`"(x, y, z)"`タプル形式を返す）を
呼んでおり、`__repr__()`との違いを取り違えていたことに実データ検証で気づき、
値の実際のPython型で判定する方式に変更した。回帰テスト
`tests/regression/test_coordinate_display_rounding.py` を新設（純粋関数テスト＋
実サンプルDXF5件でのGUIスモークテスト）。詳細は「要素属性表示・マウス座標表示の
座標を小数点2桁に丸める」節参照。）*

*過去の更新: 2026-07-09（`ui/viewer_widget.py`: 右側サイドバー（レイヤー表示・要素属性表示）の
初期横幅を ezdxf デフォルトの65%（`SIDEBAR_WIDTH_SCALE`）に縮小し、ウィンドウのリサイズでは
絶対幅が変わらないよう固定した（`QSplitter.setStretchFactor()` で CAD ビュー側にのみ
リサイズ時の伸縮を割り当てる）。`PinchZoomCADViewer.__init__` 実行時点ではまだタブに
追加されておらずコンテナ幅が0のため、`QTimer.singleShot(0, ...)` で実際にレイアウトされた
後まで調整を遅延させる必要があった。手動でのスプリッターハンドルドラッグは引き続き可能。
回帰テスト `tests/regression/test_sidebar_width.py` を新設（3ケース）。詳細は「サイドバー
（レイヤー表示・要素属性表示）の初期横幅縮小と固定幅化」節参照。）*

*過去の更新: 2026-07-09（`ui/main_window.py`: 最後のタブを閉じるとアプリが終了してしまう
不具合を修正。`DXFViewerApp.close_tab()` の「最後の1枚なら `self.close()`」特別扱いを削除し、
常に通常のタブ削除のみを行うようにした。`QTabWidget` がタブ0枚になると自動発火する
`currentChanged(-1)` を既存の `on_tab_changed`/`update_ui_for_active_tab()` がそのまま
処理し、起動直後と同じブランク状態（タイトル `"DXF Viewer"`・ステータス `"Ready"`・
ファイル依存アクション無効）に戻す。`close_tab()` のもう1つの呼び出し元
（`load_dxf()` のエラー復旧パス）も同じ修正の恩恵を受け、他にタブが無い状態で不正な
DXFファイルを開こうとしてもアプリが終了しなくなった。File > Exit（`QKeySequence.Quit`）は
別経路のため影響なし。回帰テスト `tests/regression/test_close_all_tabs.py` を新設
（3ケース）。詳細は「マルチタブ」節参照。）*

*過去の更新: 2026-07-03（`core/region_detector.py`: L字型領域の名称検出を改善（DXF-extract-labels v1.5.27 から移植）。`EE6491-039-04A.dxf` の `SYSTEM I/F BOX`（FLAT CABLE 部と一体のL字型領域）が Search Boundary でヒットしない問題を修正。①`_notch_bottom_edges()` を追加し、切り欠き部の下向き横エッジ（最下端レベル以外）を `region_name_candidates()` の Tier2 スキャン対象に追加（長方形では挙動不変）。②viewer 未移植だった `_remove_overlap_claimed_candidates()`（DXF-extract-labels v1.5.14 相当、Tier 再計算は省略）を移植し `analyze_dxf_regions()` の最終段で呼ぶ。default_name のみ照合する Search Boundary では、これが無いとネスト領域 `HEATER CTRL B.D` の名称がL字側 default に残り `SYSTEM I/F BOX` が検索不能だった。`tests/regression/test_region_search.py` に `EE6491-039-04A.dxf` の期待値を追加、既存図面の検出件数・検索結果は不変（回帰テスト4スクリプト PASS）。詳細は「Search Boundary」節の「L字型領域の名称検出」参照。）*

*（同日: `ui/viewer_widget.py`: 複数図面 DXF でカーソルを動かすだけで画面がパンする不具合を修正。`_OutlineHighlightGraphicsView` に `mouseMoveEvent` オーバーライドを追加し、左ボタン未押下時は `super().mouseMoveEvent()` 呼び出し前後のスクロール位置を保存・復元することで、ホバー検出は維持しつつカーソル移動による意図しないパンを防ぐ。加えて `PinchZoomCADViewer.__init__` で `setResizeAnchor(AnchorViewCenter)` を設定し、ビューポートサイズ変化時のパン（`AnchorUnderMouse` のデフォルト動作）を無効化（多図面の大スクロール範囲では 1px のビューポート変化でも大幅なパンになっていた）。`TransformationAnchor` は `AnchorUnderMouse` のまま維持（ホイールズームはカーソル位置を中心に行う）。回帰テスト PASS。）*

*（同日: `core/region_detector.py` にレベル汚染フォールバック（4パス目）を追加（DXF-extract-labels v1.5.23 と同期）。`_merge_collinear` に `span_levels` 引数を追加しスパン単位レベル算出に対応。`DEFAULT_REGION_CONFIG` に `span_level_merge: False` を追加。`analyze_dxf_regions` に4パス目を追加（ゲート条件: 閾値超えゼロの枠があり かつ 他枠に閾値超え領域がある場合のみ発動）: 「閾値超え候補ゼロの枠」に限りスパン単位レベルで再検出し、回復した領域の名称が他枠の検出済み名称と一致する枠のみ置き換える。EE6892-039-05B.dxf 2ページ目 SYSTEM I/F BOX の検出漏れを解消。回帰テスト PASS（EE6868/EE6888/EE6492/EE6313 各ファイル確認）。）*

*（同日: `core/region_detector.py` の領域名候補の英字判定（`_count_letters`）を全角英字（Ａ-Ｚ, ａ-ｚ）にも対応（DXF-extract-labels v1.5.24 と同期）。従来は ASCII 半角英字のみを英字と判定していたため、領域名ラベルが全角文字のみで書かれた図面（例: `ＳＹＳＴＥＭ　Ｉ／Ｆ　ＢＯＸ`）では `name_min_letters`(3) 条件を常に満たせず、名称候補が一切検出できなかった（DXF-extract-labelsでのユーザー報告により発覚。region 検出機能導入時点から一貫した未対応で退行ではないことを確認済み）。`_is_letter()`（全角対応の英字判定）・`_is_lowercase_letter()`（全角小文字も含む小文字判定）を追加し、`_count_letters()`・`_filter_eligible_labels()`・`_is_valid_name_candidate()` の3箇所を更新。`sample-dxf/problems/EE6492-039-38A.dxf` を対象に `tests/regression/test_region_search.py` の `EXPECTED` へケースを追加、全回帰テスト PASS。）*

*（同日: コード全体のリファクタリング（保守性・モジュール構成の整理。挙動は不変）。①`ui/main_window.py` に残っていた旧実装の重複4メソッド（`find_text_entities`/`store_all_entity_colors`/`apply_search_highlighting`/`restore_original_colors`、`core/search_manager.py` へ移設済みで `self.` 経由の呼び出しゼロ、計229行）を削除。②未使用の `utils/export_utils.py`（旧版）を削除し `export_utils_v2.py` を `export_utils.py` に改名（import 更新は `workers/ezdxf_worker.py` の1箇所）。③全パッケージの `__init__.py` を docstring のみに簡素化（re-export はどこからも使われておらず、`utils/__init__` は改名で壊れる状態だった）。④境界ハイライトのシーン描画（`_OverlayPolygonItem`・`draw_boundary_overlays`・`remove_boundary_overlays`・`zoom_to_regions`・`dim_all_entities`・`highlight_matched_labels`）を `ui/boundary_overlay.py` へ分離（いずれも tab_data のみに依存し window 状態不要）。⑤メニュー/ツールバー/ステータスバー構築（約290行）を `ui/main_window_actions.py` のビルダー関数へ分離し、反復的な QAction 生成を `_make_action` ヘルパーに集約（アクションは従来と同じ属性名で window にセットバック）。⑥`main_window.py` の検索制御を共通化: `_current_tab_data()`（タブ取得ボイラープレート10箇所）、`_step_search_result()`（find_next/prev × テキスト/handle の4メソッド統合）、`_update_search_actions()`（enabled 状態更新の一元化）。⑦`ui/dialogs.py` の重複部品（dim色コンボ＋10色マップ×3・検索オプション行×2・ボタン行×5）を共通ヘルパーへ抽出（公開APIは不変）。main_window.py は 1566行→843行。回帰テスト4本 PASS・offscreen での通しスモークテスト（読込→検索→ナビゲート→クリア→境界ハイライト→クリア）で検証済み。`core/region_detector.py` は DXF-extract-labels との移植同期対象のため構造変更せず。）*

*（同日: Search Text（`core/search_manager.py`）・Search Boundary（`core/region_search_manager.py`）を全角/半角非依存マッチングに対応（ユーザー報告: 半角で検索語を入力しても全角ラベルを検出したい、逆に全角検索語でも半角ラベルを検出したい）。`utils/text_utils.py` に `normalize_width()`（`unicodedata.normalize('NFKC', ...)` による全角→半角折り畳み。かな・漢字は対象外）を追加し、`SearchManager.find_text_entities()` の `search_text`/`compare_text` と `RegionSearchManager._name_matches()` の `query`/`haystack`（`whole_word` の正規表現含む）に適用。ハイライト・表示に使う `entity_text`/`default_name` 自体は元の全角/半角のまま変更しない（比較用のローカルコピーのみ正規化）。回帰テスト: `test_mtext_clean_search.py` に `WIDTH_CASES`（`normalize_width` 単体）・`check_width_insensitive_search`（`EE6492-039-38A.dxf` の全角のみラベルへ半角クエリがヒットすることを確認）を追加、`test_region_search.py` の `EE6868-500-01C.dxf`（半角ラベル）・`EE6492-039-38A.dxf`（全角ラベル）に双方向クエリを追加。全回帰テスト PASS。）*

---

*(旧最終更新: 2026-06-28（`core/region_detector.py` コード品質リファクタリング（DXF-extract-labels v1.5.22 ①-⑤ と同期、ロジック変更なし）: `_label_ok()` クロージャを module-level の `_is_valid_name_candidate()` に統合（①）・module-level `import math` / `from collections import defaultdict` に整理しインライン import を削除（②③④）・`_FRAME_MARGIN = 5` / `_MAX_FACE_NODES = 200_000` 定数化（⑤）。全回帰テスト pass 確認済み。 + `_name_union_parent()` に `exclude_names` パラメータを追加し同一フレーム内の既使用名称を除外（DXF-extract-labels v1.5.21 と同内容、EE6888-631-01A.dxf の 'SYSTEM' クエリ回帰を修正）。Search Boundary のデフォルト最小面積を 20%→10% に変更（`RegionSearchManager._DEFAULT_AREA_RATIO`・ダイアログ spinbox デフォルト・`get_analysis` キャッシュパスのデフォルト渡し、計3箇所）。 + `_resolve_union_parents()` を除去から命名に変更（DXF-extract-labels v1.5.20 と同内容）。合体親が検出された場合、子領域の採用済み候補を除外し底辺中央近接条件で親固有ラベルを探索する `_name_union_parent()` を追加。未採用ラベルがある場合は親を残して名称を更新（例: `DE5434-563-03A.dxf` で 'FX CHAMBER' を付与）、ない場合は従来通り除去。`_detect_union_parents()` の戻り値を dict 形式に変更。 + `_split_axis_aligned` の長さ比較を `> eps` → `>= eps` に変更し、長さがちょうど snap(2.0) ユニットの極短スタブを V/H 線分として検出するよう修正（DXF-extract-labels v1.5.19 と同内容）。LINE 矩形の部品輪郭課題を既知の制限に追記。 + 結合親矩形の除去（`_resolve_union_parents`）を追加。横/縦線分で2分割された兄弟矩形の合体親が planar graph の半面として誤検出されるケースを自動除去（`DE5401-405-21B.dxf` の L CHAMBER 重複、DXF-extract-labels v1.5.18 から移植）。`_detect_union_parents` + `_resolve_union_parents` を `_resolve_complement_faces` の直後（`analyze_dxf_regions` 内）に呼ぶ + 補完面解消（`_resolve_complement_faces`）を追加。兄弟矩形が縦辺を部分共有すると生じる補完面を検出・除去し、サブ領域に名称候補を継承する（`EE6313-545-01D.dxf` の B CHAMBER 重複検出バグを修正、DXF-extract-labels v1.5.17 から移植） + 図面枠の識別条件に color=7 を追加し `detect_drawing_frames` の
`min_side=400` 固定閾値を撤廃（サンプル137件で検証、退行0件・従来検出不可22件が解消。
DXF-extract-labels にも同じ修正を移植） + Consolidate Layers が領域線種の LWPOLYLINE を LINE/ARC に分解して
境界判定できるよう対応 + `_collect_region_edges` の軸判定許容誤差を `1e-6`→`1e-3` に緩和し
浮動小数点ノイズによる辺の取り落としを修正 + `_line_on_edges` を完全内包判定から重なり判定に
変更（テスト側の周長カバレッジチェックと定義を統一） + 回帰テストのサンプルDXF探索を
`sample-dxf/` 直下のみの自動探索＋`EXPECTED`系辞書の `_find_sample` 再帰解決の組み合わせに
変更し、サブフォルダへのファイル移動・新規フォルダ追加に追従できるようにした +
`test_layer_consolidation.py`/`test_region_search.py` の `all()` 短絡評価バグを修正 +
DXF handle 直接指定によるエンティティ検索「Search Handle」を追加（テキスト検索・境界検索と並列の第3モード、複数handle対応、`QAction.setIconText()` でツールバー3グループのラベルを短縮表示）+ ツールバーをユーザー希望の配置（1段目: Open+検索3グループ、2段目: 色変更系+Consolidate Layers+Export+Info）に再構成 + 矩形領域の辺ホバーハイライトを輪郭のみに限定 + Search Boundary に頂点座標リストでの検索を追加 + 閉領域検出で行き止まり枝を除去し頂点座標の重複アーティファクト・領域重複検出バグを解消 + 行き止まり枝を連結成分単位でグルーピング + 領域名候補の優先順位(Tier)制を導入 + 領域境界線の収集にPHANTOM等の線種除外を追加 + region_detector.py のモジュール性・可読性向けリファクタ + Search Boundary が最上位候補のみで照合するよう修正し領域名候補のTier1/2を領域内側のラベルに限定）*
